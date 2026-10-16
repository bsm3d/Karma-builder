# hdrireader.py - BSM Karma Builder - small readers for the HDRI preview: Radiance .hdr and OpenEXR, which Qt cannot open
# Version : 2026.10.15.1 | Revision : 16-10-2026 | Auteur : BSM

import os
import struct
import zlib

PREVIEW_COLUMNS = 1024


# ------------------------------------------------------------
class UnsupportedImage(Exception):
    pass


# ------------------------------------------------------------
def _sample(count, wanted):
    import numpy as np
    return np.unique(np.linspace(0, count - 1, min(count, wanted)).astype(np.int64))


# ------------------------------------------------------------
# The rows and the columns to keep so that the preview has the ratio of the picture and at most `columns` columns.
def _kept(width, height, columns):
    kept_columns = _sample(width, columns)
    kept_rows = _sample(height, max(1, int(round(height * len(kept_columns) / float(width)))))
    return kept_rows, kept_columns


# ------------------------------------------------------------
# Radiance .hdr: RGBE pixels, flat or run-length coded per scanline. Rows are read one after the other (their length is
# not known before), only the sampled ones are kept.
def _read_hdr(path, columns):
    import numpy as np
    with open(path, "rb") as handle:
        if not handle.readline().startswith(b"#?"):
            raise UnsupportedImage("not a Radiance file")
        while True:
            line = handle.readline()
            if not line:
                raise UnsupportedImage("the header of the file is cut")
            if line.strip() == b"":
                break
            if line.startswith(b"FORMAT=") and b"rgbe" not in line:
                raise UnsupportedImage("a Radiance file that is not RGBE")
        size = handle.readline().split()
        if len(size) != 4 or size[0] not in (b"-Y", b"+Y") or size[2] not in (b"+X", b"-X"):
            raise UnsupportedImage("a Radiance picture in an unusual orientation")
        height, width = int(size[1]), int(size[3])
        data = handle.read()
    if height < 1 or width < 1:
        raise UnsupportedImage("an empty picture")

    rows_kept, columns_kept = _kept(width, height, columns)
    keep = set(int(y) for y in rows_kept)
    picture = []
    position = 0
    coded = 8 <= width < 32768
    for y in range(height):
        wanted = y in keep
        if coded and data[position:position + 2] == b"\x02\x02" and not data[position + 2] & 0x80:
            if (data[position + 2] << 8 | data[position + 3]) != width:
                raise UnsupportedImage("a scanline of another width")
            position += 4
            row = np.zeros((4, width), dtype=np.uint8) if wanted else None
            for channel in range(4):
                x = 0
                while x < width:
                    code = data[position]
                    position += 1
                    if code > 128:
                        count = code - 128
                        if wanted:
                            row[channel, x:x + count] = data[position]
                        position += 1
                    else:
                        count = code
                        if count == 0:
                            raise UnsupportedImage("a damaged run")
                        if wanted:
                            row[channel, x:x + count] = np.frombuffer(data, dtype=np.uint8, count=count, offset=position)
                        position += count
                    x += count
            if wanted:
                picture.append(row.T)
        else:
            if width * 4 > len(data) - position:
                raise UnsupportedImage("the file ends early")
            if wanted:
                picture.append(np.frombuffer(data, dtype=np.uint8, count=width * 4, offset=position).reshape(width, 4))
            position += width * 4
    rgbe = np.stack(picture)[:, columns_kept]
    scale = np.where(rgbe[..., 3] > 0, np.ldexp(1.0, rgbe[..., 3].astype(np.int32) - 136), 0.0).astype(np.float32)
    return rgbe[..., :3].astype(np.float32) * scale[..., None]


# ------------------------------------------------------------
# OpenEXR, scanline files with no compression, RLE, ZIPS or ZIP (the others, tiles and deep data are left alone). Only
# the first line of some of the blocks is decoded.
_EXR_LINES = {0: 1, 1: 1, 2: 1, 3: 16}
_EXR_SIZES = {0: 4, 1: 2, 2: 4}


def _exr_unpack(block, compression, limit):
    import numpy as np
    if compression in (2, 3):
        # never inflate more than a block can hold: a damaged or hostile file must not fill the memory
        inflater = zlib.decompressobj()
        data = inflater.decompress(block, limit)
        if inflater.unconsumed_tail:
            raise UnsupportedImage("a block that inflates beyond its size")
        raw = np.frombuffer(data, dtype=np.uint8)
    elif compression == 1:
        out, i = bytearray(), 0
        while i < len(block) and len(out) <= limit:
            n = block[i] - 256 if block[i] > 127 else block[i]
            i += 1
            if n < 0:
                out += block[i:i - n]
                i += -n
            else:
                out += bytes([block[i]]) * (n + 1)
                i += 1
        raw = np.frombuffer(bytes(out), dtype=np.uint8)
    else:
        return np.frombuffer(block, dtype=np.uint8)
    # undo the predictor, then put the two halves back byte by byte
    delta = raw.astype(np.int16)
    delta[1:] -= 128
    flat = (np.cumsum(delta) & 255).astype(np.uint8)
    half = (len(flat) + 1) // 2
    restored = np.empty(len(flat), dtype=np.uint8)
    restored[0::2] = flat[:half]
    restored[1::2] = flat[half:]
    return restored


def _exr_header(handle):
    if handle.read(4) != b"\x76\x2f\x31\x01":
        raise UnsupportedImage("not an OpenEXR file")
    version = struct.unpack("<I", handle.read(4))[0]
    if version & 0x200 or version & 0x1000 or version & 0x2000:
        raise UnsupportedImage("a tiled, deep or multipart OpenEXR file")
    attributes = {}
    while True:
        name = b""
        while True:
            byte = handle.read(1)
            if byte == b"":
                raise UnsupportedImage("the header of the file is cut")
            if byte == b"\x00":
                break
            name += byte
        if name == b"":
            return attributes
        kind = b""
        while True:
            byte = handle.read(1)
            if byte in (b"", b"\x00"):
                break
            kind += byte
        size = struct.unpack("<i", handle.read(4))[0]
        if size < 0 or size > 1 << 24:
            raise UnsupportedImage("an attribute of an odd size")
        attributes[name.decode("latin-1")] = handle.read(size)


def _read_exr(path, columns):
    import numpy as np
    with open(path, "rb") as handle:
        attributes = _exr_header(handle)
        compression = attributes["compression"][0]
        if compression not in _EXR_LINES:
            raise UnsupportedImage("OpenEXR compression {} (supported: none, RLE, ZIP)".format(
                ("none", "RLE", "ZIPS", "ZIP", "PIZ", "PXR24", "B44", "B44A", "DWAA", "DWAB")[compression] if compression < 10 else compression))
        x_min, y_min, x_max, y_max = struct.unpack("<iiii", attributes["dataWindow"])
        width, height = x_max - x_min + 1, y_max - y_min + 1
        if width < 1 or height < 1 or width * height > 1 << 28:
            raise UnsupportedImage("an odd picture size")

        channels, data, pos = [], attributes["channels"], 0
        while data[pos] != 0:
            end = data.index(b"\x00", pos)
            name = data[pos:end].decode("latin-1")
            kind, _linear, x_sampling, y_sampling = struct.unpack("<iBxxxii", data[end + 1:end + 17])
            if x_sampling != 1 or y_sampling != 1:
                raise UnsupportedImage("a subsampled channel")
            channels.append((name, kind))
            pos = end + 17
        offsets_at = {}
        running = 0
        for name, kind in channels:
            offsets_at[name] = running
            running += _EXR_SIZES[kind] * width
        line_bytes = running
        wanted = [n for n in ("R", "G", "B") if n in offsets_at] or [n for n in ("Y", "A") if n in offsets_at][:1] or [channels[0][0]]
        kinds = dict(channels)

        per_block = _EXR_LINES[compression]
        block_count = (height + per_block - 1) // per_block
        table = struct.unpack("<{}Q".format(block_count), handle.read(8 * block_count))
        rows_kept, columns_kept = _kept(width, height, columns)
        by_block = {}
        for y in rows_kept:
            by_block.setdefault(int(y) // per_block, []).append(int(y) % per_block)
        picture = []
        for index in sorted(by_block):
            handle.seek(table[index])
            _y, size = struct.unpack("<ii", handle.read(8))
            if size < 0 or size > line_bytes * per_block + 1024:
                raise UnsupportedImage("a damaged block")
            payload = handle.read(size)
            expected = line_bytes * min(per_block, height - index * per_block)
            # a block that did not shrink is stored as it is
            raw = payload if compression == 0 or size >= expected else bytes(_exr_unpack(payload, compression, expected))
            for line_number in by_block[index]:
                line = []
                for name in wanted:
                    start = line_number * line_bytes + offsets_at[name]
                    kind = kinds[name]
                    if kind == 1:
                        values = np.frombuffer(raw, dtype="<f2", count=width, offset=start).astype(np.float32)
                    elif kind == 2:
                        values = np.frombuffer(raw, dtype="<f4", count=width, offset=start)
                    else:
                        raise UnsupportedImage("an integer channel")
                    line.append(values[columns_kept])
                while len(line) < 3:
                    line.append(line[0])
                picture.append(np.stack(line, axis=-1))
    return np.stack(picture).astype(np.float32)


# ------------------------------------------------------------
# Linear light to 8-bit: exposure so that the middle of the picture is a mid grey, a soft shoulder, then gamma.
def tone_map(rgb):
    import numpy as np
    rgb = np.nan_to_num(np.asarray(rgb, dtype=np.float32), nan=0.0, posinf=1e6, neginf=0.0)
    luminance = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    lit = luminance[luminance > 1e-6]
    middle = float(np.median(lit)) if lit.size else 0.18
    scaled = np.clip(rgb, 0.0, None) * (0.25 / min(max(middle, 1e-4), 1e4))
    soft = scaled / (1.0 + scaled)
    return (np.power(soft, 1.0 / 2.2) * 255.0 + 0.5).clip(0, 255).astype(np.uint8)


# ------------------------------------------------------------
# (8-bit RGB array with the ratio of the picture and at most `columns` columns, "") or (None, what is wrong)
def read_preview(path, columns=PREVIEW_COLUMNS):
    extension = os.path.splitext(path)[1].lower()
    try:
        if extension == ".hdr":
            return tone_map(_read_hdr(path, columns)), ""
        if extension == ".exr":
            return tone_map(_read_exr(path, columns)), ""
    except UnsupportedImage as exc:
        return None, str(exc)
    except (OSError, ValueError, KeyError, IndexError, struct.error, zlib.error, MemoryError, ImportError) as exc:
        return None, "{}: {}".format(type(exc).__name__, exc)
    return None, "no reader for {} files".format(extension or "this kind of")
