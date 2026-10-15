# 2D cloud picture: shape, coverage, seamless, deterministic, cached, a valid PNG.
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
t.check("PNG signature", data[:8] == b"\x89PNG\r\n\x1a\n")
width, height, depth, color = struct.unpack(">IIBB", data[16:26])
t.check("header: 2048 x 1024, 8-bit grey", (width, height, depth, color) == (2048, 1024, 8, 0), (width, height, depth, color))
pos, idat = 8, b""
while pos < len(data):
    length, kind = struct.unpack(">I4s", data[pos:pos + 8])
    body = data[pos + 8:pos + 8 + length]
    crc = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
    t.check("chunk {} crc".format(kind.decode()), zlib.crc32(kind + body) & 0xFFFFFFFF == crc)
    if kind == b"IDAT":
        idat += body
    pos += 12 + length
raw = zlib.decompress(idat)
rows = np.frombuffer(raw, dtype=np.uint8).reshape(height, width + 1)
t.check("filter byte 0 on every row", int(rows[:, 0].max()) == 0)
t.check("pixels match the picture", int(np.abs(rows[:, 1:].astype(int) - (image * 255 + 0.5).astype(int)).max()) <= 1)

for seed in range(100, 110):
    clouds.cloud_texture_path(0.5, 0.4, 3.0, seed)
count = len([n for n in os.listdir(folder) if n.startswith(clouds.CLOUD_FILE_PREFIX)])
t.check("old pictures are cleaned up", count == clouds.CLOUD_FILES_KEPT, count)

t.done()
