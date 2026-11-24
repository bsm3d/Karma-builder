# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Procedural 2D cloud layer rendered as a lat-long texture for a dome light, with its cache and the cloud card file.

# Houdini : 21 and 22

import hashlib
import hou
import html
import os
import struct
import zlib
from .debuglog import _debug
from .util import _has_expression, _private_temp_dir

CLOUD_TEXTURE_SIZE = (2048, 1024)
CLOUD_FILE_PREFIX = "bsm_clouds_"
CLOUD_FILES_KEPT = 6
# bug trouvé et fixé: the small files of the cloud card and of the moon had the same name prefix as the pictures, a slider
# dragged a few times pushed the picture a node still reads out of the "newest six" and it was deleted. One prefix each.
CLOUD_CARD_PREFIX = "bsm_cloudcard_"
SMALL_FILES_KEPT = 40
CLOUD_CARD_NAME = "CloudLayer"
CLOUD_UV_VEX = """vector uvof(vector P) { vector p = normalize(P); return set(atan2(p.x, p.z) / (2 * PI) + 0.5, asin(clamp(p.y, -1, 1)) / PI + 0.5, 0); }
int vts[] = primvertices(0, vertexprim(0, @vtxnum));
float umin = 1, umax = 0;
foreach (int vt; vts) { vector q = uvof(point(0, "P", vertexpoint(0, vt))); umin = min(umin, q.x); umax = max(umax, q.x); }
vector uv = uvof(@P);
if (umax - umin > 0.5 && uv.x < 0.5) uv.x += 1;
v@uv = uv;"""
CLOUD_CARD_MTLX = """<?xml version="1.0"?>
<materialx version="1.38">
  <image name="picture" type="color3">
    <input name="file" type="filename" value="{file}" colorspace="Raw" />
  </image>
  <extract name="mask" type="float">
    <input name="in" type="color3" nodename="picture" />
    <input name="index" type="integer" value="0" />
  </extract>
  <convert name="mask_color" type="color3">
    <input name="in" type="float" nodename="mask" />
  </convert>
  <standard_surface name="SR_CloudLayer" type="surfaceshader">
    <input name="base" type="float" value="0" />
    <input name="specular" type="float" value="0" />
    <input name="emission" type="float" value="{emission}" />
    <input name="emission_color" type="color3" nodename="picture" />
    <input name="opacity" type="color3" nodename="mask_color" />
  </standard_surface>
  <surfacematerial name="CloudLayer" type="material">
    <input name="surfaceshader" type="surfaceshader" nodename="SR_CloudLayer" />
  </surfacematerial>
</materialx>
"""

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
    height, width = values.shape[:2]
    half = values.astype(np.float16)
    colour = values.ndim == 3
    # RGB (3 channels) or RGBA (4): the channels of an EXR go in alphabetical order, A B G R
    names = (b"A", b"B", b"G", b"R") if colour and values.shape[2] == 4 else (b"B", b"G", b"R")
    order = (3, 2, 1, 0) if len(names) == 4 else (2, 1, 0)

    def attribute(name, kind, data):
        return name + b"\x00" + kind + b"\x00" + struct.pack("<i", len(data)) + data

    channels = b"".join(name + b"\x00" + struct.pack("<iBxxxii", 1, 0, 1, 1) for name in names) + b"\x00"
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
        if colour:
            raw = np.frombuffer(b"".join(np.ascontiguousarray(half[row, :, c]).tobytes() for c in order), dtype=np.uint8)
        else:
            raw = np.frombuffer(half[row].tobytes() * 3, dtype=np.uint8)   # B, G and R rows, the same grey
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
# bug trouvé et fixé: a second dome light is never seen by the camera (Karma draws one environment background), so
# the clouds were lit but invisible. They are painted on a sphere instead: emissive, opaque where there is a cloud
# and clear elsewhere, so the sky shows through. The cloud picture is the mask and the colour.
def cloud_card_file(texture_path, emission):
    if _has_expression(texture_path):
        raise ValueError("refusing a cloud texture path that contains an expression")
    key = "{}|{:.4f}|{}".format(texture_path, float(emission), CLOUD_CARD_MTLX)
    name = "{}{}.mtlx".format(CLOUD_CARD_PREFIX, hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12])
    path = "{}/{}".format(os.path.dirname(texture_path), name)
    if not os.path.isfile(path):
        text = CLOUD_CARD_MTLX.format(file=html.escape(texture_path, quote=True), emission="{:.6g}".format(float(emission)))
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        _forget_old_textures(os.path.dirname(texture_path), keep=path, prefix=CLOUD_CARD_PREFIX, count=SMALL_FILES_KEPT)
    return path

# ------------------------------------------------------------
def _forget_old_textures(folder, keep, prefix=CLOUD_FILE_PREFIX, count=CLOUD_FILES_KEPT):
    try:
        files = [os.path.join(folder, n) for n in os.listdir(folder) if n.startswith(prefix) and n.endswith((".exr", ".png", ".mtlx", ".usdc"))]
        files.sort(key=os.path.getmtime, reverse=True)
        for old in files[count:]:
            if os.path.normcase(os.path.abspath(old)) != os.path.normcase(os.path.abspath(keep)):
                os.remove(old)
    except OSError as exc:
        _debug("old cloud textures not cleaned: {}".format(exc))
