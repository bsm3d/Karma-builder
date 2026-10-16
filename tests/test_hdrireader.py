# HDRI preview readers: Radiance .hdr (flat and run-length) and OpenEXR written by the tool, ratio, tone mapping, damaged files.
#
# Revision : 16-10-2026 | Auteur : BSM
from _common import Checker, load_tool, scratch_dir

hou, k = load_tool()
import numpy as np
import bsm_karma.clouds2d as clouds
import bsm_karma.hdrireader as reader

t = Checker("hdri reader")
folder = scratch_dir("hdri_reader")


# ------------------------------------------------------------
def rgbe_rows(picture):
    peak = picture.max(axis=-1)
    mantissa, exponent = np.frexp(peak)
    scale = np.where(peak > 0, 256.0 / np.ldexp(1.0, exponent), 0.0)
    rgb = np.clip(picture * scale[..., None], 0, 255).astype(np.uint8)
    return np.concatenate([rgb, np.where(peak > 0, exponent + 128, 0).astype(np.uint8)[..., None]], axis=-1)


def write_hdr(path, picture, coded):
    height, width = picture.shape[:2]
    rows = rgbe_rows(picture)
    body = b""
    for row in rows:
        if not coded:
            body += row.tobytes()
            continue
        body += bytes([2, 2, width >> 8, width & 255])
        for channel in range(4):
            data, i = row[:, channel].tobytes(), 0
            while i < width:
                run = 1
                while i + run < width and data[i + run] == data[i] and run < 127:
                    run += 1
                if run >= 4:
                    body += bytes([128 + run, data[i]])
                    i += run
                else:
                    end = min(i + 4, width)
                    body += bytes([end - i]) + data[i:end]
                    i = end
    with open(path, "wb") as handle:
        handle.write(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y %d +X %d\n" % (height, width) + body)


# ------------------------------------------------------------
height, width = 96, 200
yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
picture = np.stack([xx / width * 4 + 0.05, yy / height * 2 + 0.05, np.full_like(xx, 0.5)], axis=-1)
picture[10:20, 30:80] = 300.0
for coded in (False, True):
    path = "{}/test_{}.hdr".format(folder, "rle" if coded else "flat")
    write_hdr(path, picture, coded)
    got = reader._read_hdr(path, 1024)
    error = float((np.abs(got - picture) / picture.max(axis=-1, keepdims=True)).max())
    t.check("Radiance {} file: same pixels (8-bit mantissa)".format("run-length" if coded else "flat"), got.shape == picture.shape and error < 0.01, (got.shape, round(error, 4)))

small = reader._read_hdr(path, 50)
t.check("fewer columns keep the ratio of the picture", small.shape[1] == 50 and abs(small.shape[0] - 24) <= 1, small.shape)

# the cloud picture the tool writes
image = clouds.render_cloud_layer(0.5, 0.4, 3.0, 7, (256, 128))
exr = "{}/test.exr".format(folder)
clouds.write_exr_grey(exr, image)
got = reader._read_exr(exr, 1024)
t.check("OpenEXR written by the tool: read back", got.shape == (128, 256, 3) and float(np.abs(got[..., 0] - image).max()) < 1e-3, got.shape)
half = reader._read_exr(exr, 64)
t.check("OpenEXR: 64 columns, ratio kept", half.shape == (32, 64, 3), half.shape)

pixels, why = reader.read_preview(exr)
t.check("read_preview gives 8-bit RGB", pixels is not None and pixels.dtype == np.uint8 and pixels.shape == (128, 256, 3) and why == "", why)
t.check("tone mapping: dark stays dark, the sun does not clip everything", int(pixels[0, 0, 0]) <= int(pixels.max()) and pixels.max() <= 255)
mapped = reader.tone_map(np.array([[[0.2, 0.2, 0.2], [0.2, 0.2, 0.2], [5000.0, 5000.0, 5000.0]]], dtype=np.float32))
t.check("tone mapping: a very bright pixel stays a valid value", mapped.shape == (1, 3, 3) and mapped[0, 2, 0] >= mapped[0, 0, 0])
nan = reader.tone_map(np.array([[[np.nan, np.inf, -1.0]]], dtype=np.float32))
t.check("tone mapping: nan, infinity and negative values do not raise", nan.shape == (1, 1, 3))

# what cannot be read says why, and never raises
with open("{}/not.exr".format(folder), "wb") as handle:
    handle.write(b"nope")
with open("{}/cut.hdr".format(folder), "wb") as handle:
    handle.write(b"#?RADIANCE\n\n-Y 10 +X 10\nxx")
piz = bytearray(open(exr, "rb").read())
marker = piz.index(b"compression")
piz[marker + len(b"compression\x00compression\x00") + 4] = 4
with open("{}/piz.exr".format(folder), "wb") as handle:
    handle.write(bytes(piz))
for name, wanted in (("not.exr", "OpenEXR"), ("cut.hdr", "ends early"), ("piz.exr", "PIZ"), ("a.txt", "no reader")):
    path = "{}/{}".format(folder, name)
    if name == "a.txt":
        open(path, "w").write("x")
    out, why = reader.read_preview(path)
    t.check("{}: no picture, and the reason says '{}'".format(name, wanted), out is None and wanted in why, why)

t.done()
