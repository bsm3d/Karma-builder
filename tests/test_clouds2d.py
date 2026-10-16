# 2D cloud picture: shape, coverage, seamless, deterministic, cached, a valid OpenEXR.
#
# Revision : 15-10-2026 | Auteur : BSM
import os
import struct
import zlib
from _common import Checker, load_tool, scratch_dir

hou, k = load_tool()
import bsm_karma.clouds2d as clouds
import numpy as np

t = Checker("clouds 2d")
folder = scratch_dir("clouds_2d") + "/cache"
os.makedirs(folder, exist_ok=True)
clouds._cache_folder = lambda: folder

image = clouds.render_cloud_layer(0.5, 0.4, 3.0, 7)
t.check("shape is 1024 x 2048", image.shape == (1024, 2048), image.shape)
t.check("values between 0 and 1", image.min() >= 0.0 and image.max() <= 1.0 + 1e-6)
t.check("nothing below the horizon", image[512:].max() == 0.0)
coverage = float((image[:512] > 0.05).mean())
low = float((clouds.render_cloud_layer(0.15, 0.4, 3.0, 7)[:512] > 0.05).mean())
high = float((clouds.render_cloud_layer(0.85, 0.4, 3.0, 7)[:512] > 0.05).mean())
t.check("coverage grows with the slider", low < coverage < high, (round(low, 3), round(coverage, 3), round(high, 3)))
t.check("zero coverage is a clear sky", clouds.render_cloud_layer(0.0, 0.4, 3.0, 7).max() == 0.0)
t.check("same seed, same picture", np.array_equal(image, clouds.render_cloud_layer(0.5, 0.4, 3.0, 7)))
t.check("another seed, another picture", not np.array_equal(image, clouds.render_cloud_layer(0.5, 0.4, 3.0, 8)))
seam = float(np.abs(image[:, 0] - image[:, -1]).mean())
inner = float(np.abs(image[:, 100] - image[:, 101]).mean())
t.check("seamless around the horizon", seam < inner * 3 + 0.01, (round(seam, 4), round(inner, 4)))

path = clouds.cloud_texture_path(0.5, 0.4, 3.0, 7)
t.check("file written in the cache folder", os.path.isfile(path) and path.startswith(folder), path)
stamp = os.path.getmtime(path)
t.check("same settings reuse the file", clouds.cloud_texture_path(0.5, 0.4, 3.0, 7) == path and os.path.getmtime(path) == stamp)
small = clouds.cloud_texture_path(0.5, 0.4, 3.0, 7, (1024, 512))
t.check("a smaller picture has its own file", small != path and os.path.isfile(small))

data = open(path, "rb").read()
t.check("OpenEXR signature and version 2", data[:4] == b"\x76\x2f\x31\x01" and struct.unpack("<I", data[4:8])[0] == 2)
pos, attributes = 8, {}
while data[pos] != 0:
    end = data.index(b"\x00", pos)
    name = data[pos:end].decode()
    kind_end = data.index(b"\x00", end + 1)
    size = struct.unpack("<i", data[kind_end + 1:kind_end + 5])[0]
    attributes[name] = data[kind_end + 5:kind_end + 5 + size]
    pos = kind_end + 5 + size
pos += 1
t.check("header: 2048 x 1024 window, ZIPS compression", attributes["dataWindow"] == struct.pack("<iiii", 0, 0, 2047, 1023) and attributes["compression"] == b"\x02")
t.check("header: three 16-bit float channels B, G, R", attributes["channels"].count(struct.pack("<i", 1)) >= 3 and attributes["channels"].startswith(b"B\x00") and b"G\x00" in attributes["channels"] and b"R\x00" in attributes["channels"])
offsets = struct.unpack("<1024Q", data[pos:pos + 8 * 1024])
t.check("the offset table points at the scanlines in order", all(struct.unpack("<i", data[offset:offset + 4])[0] == row for row, offset in enumerate(offsets)))
worst = 0.0
for row in (0, 100, 511, 1023):
    size = struct.unpack("<i", data[offsets[row] + 4:offsets[row] + 8])[0]
    packed = data[offsets[row] + 8:offsets[row] + 8 + size]
    raw_size = 2048 * 2 * 3
    if size < raw_size:
        delta = np.frombuffer(zlib.decompress(packed), dtype=np.uint8).astype(np.int16)
        delta[1:] -= 128
        half = (np.cumsum(delta) & 255).astype(np.uint8)
        restored = np.empty(raw_size, dtype=np.uint8)
        restored[0::2] = half[:raw_size // 2]
        restored[1::2] = half[raw_size // 2:]
    else:
        restored = np.frombuffer(packed, dtype=np.uint8)
    red = np.frombuffer(restored[2 * 2048 * 2:].tobytes(), dtype=np.float16).astype(np.float32)
    blue = np.frombuffer(restored[:2 * 2048].tobytes(), dtype=np.float16).astype(np.float32)
    worst = max(worst, float(np.abs(red - image[row]).max()), float(np.abs(blue - image[row]).max()))
t.check("scanlines decode to the picture (16-bit float precision)", worst < 1e-3, worst)

for seed in range(100, 110):
    clouds.cloud_texture_path(0.5, 0.4, 3.0, seed)
count = len([n for n in os.listdir(folder) if n.startswith(clouds.CLOUD_FILE_PREFIX)])
t.check("old pictures are cleaned up", count == clouds.CLOUD_FILES_KEPT, count)

t.done()
