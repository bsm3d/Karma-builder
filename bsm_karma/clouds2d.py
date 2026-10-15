# clouds2d.py - BSM Karma Builder - procedural 2D cloud layer (a lat-long texture for a dome light)
# Version : 2026.10.15.1 | Revision : 15-10-2026 | Auteur : BSM

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
# Grey image, 0 to 1: clouds in the upper half (top row = zenith), nothing below the horizon.
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

    # thicker clouds are brighter, the thin edges are faint
    shade = 0.55 + 0.45 * _smoothstep(np, threshold, threshold + 1.5 + soft, density)
    image = mask * shade

    # up to the horizon: full strength overhead, fading out in the last 20 degrees, none below
    elevation = (0.5 - (np.arange(height, dtype=np.float32) + 0.5) / height) * 180.0
    fade = _smoothstep(np, 1.0, 20.0, elevation)[:, None]
    return np.clip(image * fade, 0.0, 1.0).astype(np.float32)


# ------------------------------------------------------------
# 8-bit grey PNG, written with zlib so no imaging library is needed.
def write_png_grey(path, array):
    import numpy as np
    pixels = (np.clip(array, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    height, width = pixels.shape
    raw = b"".join(b"\x00" + pixels[row].tobytes() for row in range(height))

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(png)


# ------------------------------------------------------------
# Path of the texture for these settings. The file name is a hash of them: the same settings reuse the file.
def cloud_texture_path(coverage, softness, scale, seed, size=CLOUD_TEXTURE_SIZE):
    key = "{:.3f}|{:.3f}|{:.3f}|{}|{}".format(float(coverage), float(softness), float(scale), int(seed), tuple(size))
    name = "{}{}.png".format(CLOUD_FILE_PREFIX, hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12])
    folder = _cache_folder()
    path = "{}/{}".format(folder, name)
    if not os.path.isfile(path):
        write_png_grey(path, render_cloud_layer(coverage, softness, scale, seed, size))
        _debug("cloud texture written: {}".format(path))
        _forget_old_textures(folder, keep=path)
    return path


# ------------------------------------------------------------
def _forget_old_textures(folder, keep):
    try:
        files = [os.path.join(folder, n) for n in os.listdir(folder) if n.startswith(CLOUD_FILE_PREFIX) and n.endswith(".png")]
        files.sort(key=os.path.getmtime, reverse=True)
        for old in files[CLOUD_FILES_KEPT:]:
            if os.path.normcase(os.path.abspath(old)) != os.path.normcase(os.path.abspath(keep)):
                os.remove(old)
    except OSError as exc:
        _debug("old cloud textures not cleaned: {}".format(exc))
