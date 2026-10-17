# Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Procedural 2D cloud layer (a lat-long texture for a dome light)
# Houdini : 21 and 22
# Version : 1.0.0

import hashlib
import hou
import os
import struct
import zlib
from .debuglog import _debug
from .util import _has_expression, _private_temp_dir

CLOUD_TEXTURE_SIZE = (2048, 1024)
CLOUD_FILE_PREFIX = "bsm_clouds_"
CLOUD_FILES_KEPT = 6


# ------------------------------------------------------------
def _cache_folder():
    folders = []
    try:
        pref_dir = hou.text.expandString("$HOUDINI_USER_PREF_DIR")
        if pref_dir and not pref_dir.startswith("$"):
            folders.append(os.path.join(pref_dir, "bsm_karma", "clouds"))
    except (hou.Error, AttributeError):
        pass
    folders.append(os.path.join(_private_temp_dir(), "clouds"))
    for folder in folders:
        if _has_expression(folder):
            continue
        try:
            os.makedirs(folder, exist_ok=True)
            return folder.replace("\\", "/")
        except OSError:
            continue
    raise OSError("no folder to write the cloud texture to")


# ------------------------------------------------------------
# Periodic (tileable) noise: white noise shaped in the Fourier domain, so the texture closes on itself around the
# horizon. `freq` is the number of big features around it; `stretch` widens them along the horizon.
def _shaped_noise(np, rng, height, width, freq, stretch, falloff):
    spectrum = np.fft.rfft2(rng.standard_normal((height, width)).astype(np.float32))
    fy = np.fft.fftfreq(height).astype(np.float32)[:, None] * width / max(stretch, 0.1)
    fx = np.fft.rfftfreq(width).astype(np.float32)[None, :] * width
    radius = np.sqrt(fx * fx + fy * fy) / max(freq, 0.5)
    spectrum *= 1.0 / (1.0 + radius * radius) ** (falloff / 2.0)
    spectrum[0, 0] = 0.0
    field = np.fft.irfft2(spectrum, s=(height, width))
    return (field / (field.std() + 1e-9)).astype(np.float32)


# ------------------------------------------------------------
def _smoothstep(np, low, high, values):
    t = np.clip((values - low) / max(high - low, 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ------------------------------------------------------------
def render_cloud_layer(coverage, softness, scale, seed, size=CLOUD_TEXTURE_SIZE):
    import numpy as np
    width, height = size
    rng = np.random.default_rng(int(seed))
    base = _shaped_noise(np, rng, height, width, scale, 2.0, 2.6)
    detail = _shaped_noise(np, rng, height, width, scale * 6.0, 1.5, 2.2)
    density = base + 0.35 * detail
    coverage = float(min(max(coverage, 0.0), 1.0))
    threshold = float(np.quantile(density[:height // 2], 1.0 - coverage)) if coverage > 0.0 else 1e9
    soft = 0.05 + 0.9 * float(min(max(softness, 0.0), 1.0))
    mask = _smoothstep(np, threshold - soft, threshold + soft, density)

    shade = 0.55 + 0.45 * _smoothstep(np, threshold, threshold + 1.5 + soft, density)
    image = mask * shade

    # up to the horizon: full strength overhead, fading out in the last 20 degrees, none below
    elevation = (0.5 - (np.arange(height, dtype=np.float32) + 0.5) / height) * 180.0
    fade = _smoothstep(np, 1.0, 20.0, elevation)[:, None]
    return np.clip(image * fade, 0.0, 1.0).astype(np.float32)


# ------------------------------------------------------------
# OpenEXR file, RGB (the grey value in the three channels), 16-bit float, one scanline per ZIP block, written with
# zlib so no imaging library is needed. Linear light: a 8-bit PNG would be read as sRGB and come out much darker.
def write_exr_grey(path, array):
    import numpy as np
    values = np.asarray(array, dtype=np.float32)
    height, width = values.shape
    half = values.astype(np.float16)

    def attribute(name, kind, data):
        return name + b"\x00" + kind + b"\x00" + struct.pack("<i", len(data)) + data

    channels = b"".join(name + b"\x00" + struct.pack("<iBxxxii", 1, 0, 1, 1) for name in (b"B", b"G", b"R")) + b"\x00"
    window = struct.pack("<iiii", 0, 0, width - 1, height - 1)
    header = (b"\x76\x2f\x31\x01" + struct.pack("<I", 2)
              + attribute(b"channels", b"chlist", channels)
              + attribute(b"compression", b"compression", b"\x02")
              + attribute(b"dataWindow", b"box2i", window)
              + attribute(b"displayWindow", b"box2i", window)
              + attribute(b"lineOrder", b"lineOrder", b"\x00")
              + attribute(b"pixelAspectRatio", b"float", struct.pack("<f", 1.0))
              + attribute(b"screenWindowCenter", b"v2f", struct.pack("<ff", 0.0, 0.0))
              + attribute(b"screenWindowWidth", b"float", struct.pack("<f", 1.0))
              + b"\x00")

    blocks = []
    for row in range(height):
        line = half[row].tobytes()
        raw = np.frombuffer(line * 3, dtype=np.uint8)            # B, G and R rows, the same grey
        shuffled = np.concatenate((raw[0::2], raw[1::2])).astype(np.int16)
        delta = shuffled.copy()
        delta[1:] = (shuffled[1:] - shuffled[:-1] + 384) & 255   # the predictor of OpenEXR's ZIP
        packed = zlib.compress(delta.astype(np.uint8).tobytes(), 6)
        if len(packed) >= len(raw):
            packed = raw.tobytes()                              # stored as it is when it does not shrink
        blocks.append(struct.pack("<ii", row, len(packed)) + packed)

    start = len(header) + 8 * height
    offsets, position = [], start
    for block in blocks:
        offsets.append(position)
        position += len(block)
    with open(path, "wb") as handle:
        handle.write(header + struct.pack("<{}Q".format(height), *offsets) + b"".join(blocks))


# ------------------------------------------------------------
def cloud_texture_path(coverage, softness, scale, seed, size=CLOUD_TEXTURE_SIZE):
    key = "{:.3f}|{:.3f}|{:.3f}|{}|{}".format(float(coverage), float(softness), float(scale), int(seed), tuple(size))
    name = "{}{}.exr".format(CLOUD_FILE_PREFIX, hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12])
    folder = _cache_folder()
    path = "{}/{}".format(folder, name)
    if not os.path.isfile(path):
        write_exr_grey(path, render_cloud_layer(coverage, softness, scale, seed, size))
        _debug("cloud texture written: {}".format(path))
        _forget_old_textures(folder, keep=path)
    return path


# ------------------------------------------------------------
def _forget_old_textures(folder, keep):
    try:
        files = [os.path.join(folder, n) for n in os.listdir(folder) if n.startswith(CLOUD_FILE_PREFIX) and n.endswith((".exr", ".png"))]
        files.sort(key=os.path.getmtime, reverse=True)
        for old in files[CLOUD_FILES_KEPT:]:
            if os.path.normcase(os.path.abspath(old)) != os.path.normcase(os.path.abspath(keep)):
                os.remove(old)
    except OSError as exc:
        _debug("old cloud textures not cleaned: {}".format(exc))
