# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Sky plate drawing stars, planets, the Milky Way, the moon and its halo for a camera, to be composed under the render.

# Houdini : 21 and 22

import math
import os
from hutil.Qt import QtGui
from .debuglog import _debug
from .moon import HALO_SCALE, MOON_COLOR, EARTHSHINE, moon_state
from .nightsky import celestial_rotation, star_catalog, star_direction
from .util import _sky_data_file

# The sky as a picture, not as geometry: nothing stands in the scene, a star is as sharp as the picture is. Every layer is for one
# camera and one resolution; the render and its depth say where the sky is (depth 0), the plate is added there.
STAR_GAIN = 6.0
STAR_SIGMA = 0.6                # pixels: the optical spread of a faint star
GLOW_SIGMA = 7.0                # pixels: the halo of a bright one
GLOW_FROM_FLUX = 1.5
MILKY_GAIN = 0.30

# ------------------------------------------------------------
# The camera of a USD stage: its orientation (the camera looks down -Z), its focal length and its horizontal aperture, in millimetres.
def camera_of_stage(stage, prim_path):
    import numpy as np
    from pxr import UsdGeom
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsA(UsdGeom.Camera):
        raise ValueError("{} is not a camera of the stage".format(prim_path))
    camera = UsdGeom.Camera(prim)
    matrix = camera.ComputeLocalToWorldTransform(0.0)
    rotation = np.array([[matrix[j][i] for j in range(3)] for i in range(3)], dtype=np.float64)   # columns: the camera axes in the world
    for i in range(3):
        rotation[:, i] /= np.linalg.norm(rotation[:, i])
    focal = camera.GetFocalLengthAttr().Get(0.0) or 50.0
    aperture = camera.GetHorizontalApertureAttr().Get(0.0) or 20.955
    return {"rotation": rotation, "focal": float(focal), "aperture": float(aperture)}

# ------------------------------------------------------------
# Where a direction of the world lands in the picture (columns, rows), and whether it is in front of the camera.
def project(np, camera, width, height, directions):
    local = directions @ camera["rotation"]
    front = local[:, 2] < -1e-6
    z = np.where(front, -local[:, 2], 1.0)
    scale = camera["focal"] / camera["aperture"] * width
    return width / 2.0 + local[:, 0] / z * scale, height / 2.0 - local[:, 1] / z * scale, front

# ------------------------------------------------------------
# The direction of the world of every pixel.
def pixel_directions(np, camera, width, height):
    scale = camera["focal"] / camera["aperture"] * width
    xs = (np.arange(width, dtype=np.float64) + 0.5 - width / 2.0) / scale
    ys = -(np.arange(height, dtype=np.float64) + 0.5 - height / 2.0) / scale
    local = np.stack(np.broadcast_arrays(xs[None, :], ys[:, None], -np.ones((1, 1))), axis=-1)
    local = local / np.linalg.norm(local, axis=-1, keepdims=True)
    return local @ camera["rotation"].T

# ------------------------------------------------------------
# A gaussian dot for each point: the colour is its peak, sigma its spread in pixels. The reach is three sigmas.
def _splat(np, plane, columns, rows, colours, sigmas):
    height, width = plane.shape[:2]
    for column, row, colour, sigma in zip(columns, rows, colours, sigmas):
        reach = int(math.ceil(3.0 * sigma))
        ix, iy = int(round(column)), int(round(row))
        if ix < -reach or iy < -reach or ix >= width + reach or iy >= height + reach:
            continue
        xs, ys = np.arange(ix - reach, ix + reach + 1), np.arange(iy - reach, iy + reach + 1)
        keep_x, keep_y = (xs >= 0) & (xs < width), (ys >= 0) & (ys < height)
        if not keep_x.any() or not keep_y.any():
            continue
        weight = np.exp(-(((xs[keep_x] - column) ** 2)[None, :] + ((ys[keep_y] - row) ** 2)[:, None]) / (2.0 * sigma * sigma))
        plane[np.ix_(ys[keep_y], xs[keep_x])] += weight[:, :, None] * colour[None, None, :]

# ------------------------------------------------------------
def _milky_way(np, directions, rotation, strength):
    source = _sky_data_file("milky_way_1k.exr")
    if not source:
        return None
    try:
        import OpenImageIO as oiio
        reader = oiio.ImageInput.open(source)
        spec = reader.spec()
        image = np.array(reader.read_image("float")).reshape(spec.height, spec.width, spec.nchannels)[:, :, :3]
        reader.close()
    except (ImportError, OSError, AttributeError, ValueError) as exc:
        _debug("milky way not read: {}".format(exc))
        return None
    celestial = directions @ rotation          # the inverse of the turn of the sky (a rotation matrix: transpose)
    ra = np.arctan2(-celestial[..., 2], celestial[..., 0])
    dec = np.arcsin(np.clip(celestial[..., 1], -1.0, 1.0))
    u = (0.5 - ra / (2.0 * math.pi)) % 1.0 * spec.width - 0.5
    v = (0.5 - dec / math.pi) * spec.height - 0.5
    x0, y0 = np.floor(u).astype(int), np.floor(v).astype(int)
    fx, fy = (u - x0)[..., None], (v - y0)[..., None]
    x0w, x1w = x0 % spec.width, (x0 + 1) % spec.width
    y0c, y1c = np.clip(y0, 0, spec.height - 1), np.clip(y0 + 1, 0, spec.height - 1)
    sample = (image[y0c, x0w] * (1 - fx) * (1 - fy) + image[y0c, x1w] * fx * (1 - fy) + image[y1c, x0w] * (1 - fx) * fy + image[y1c, x1w] * fx * fy)
    return sample * strength

# ------------------------------------------------------------
def _moon_map():
    import numpy as np
    source = _sky_data_file("moon.jpg")
    if not source:
        return None
    image = QtGui.QImage(source)
    if image.isNull():
        return None
    image = image.convertToFormat(QtGui.QImage.Format_Grayscale8)
    data = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width()].astype(np.float32) / 255.0
    return data ** 2.2

# ------------------------------------------------------------
# The sun to the moon for the shading, the moon itself with its phase and a halo around it: returns (colour, alpha, glow) arrays.
def _moon_layers(np, directions, state, size, halo, strength):
    height, width = directions.shape[:2]
    moon, sun = np.array(state["moon"], dtype=np.float64), np.array(state["sun"], dtype=np.float64)
    radius = math.radians(float(size) / 2.0)
    cosine = directions @ moon
    angle = np.arccos(np.clip(cosine, -1.0, 1.0))
    colour = np.zeros((height, width, 3), dtype=np.float32)
    alpha = np.zeros((height, width), dtype=np.float32)
    glow = np.zeros((height, width, 3), dtype=np.float32)
    daylight = state["daylight"]
    emission = 0.9 * strength * (1.0 - 0.55 * daylight) * state["fade"]
    up = np.array([0.0, 1.0, 0.0])
    right = np.cross(moon, up)
    right = right / (np.linalg.norm(right) or 1.0)
    up_axis = np.cross(right, moon)
    inside = angle < radius
    if inside.any():
        x = (directions[inside] @ right) / math.sin(radius)
        y = (directions[inside] @ up_axis) / math.sin(radius)
        z = np.sqrt(np.clip(1.0 - x * x - y * y, 0.0, 1.0))
        normal = x[:, None] * right + y[:, None] * up_axis - z[:, None] * moon
        facing = normal @ sun
        t = np.clip((facing + 0.03) / 0.18, 0.0, 1.0)
        lit = np.maximum(t * t * (3.0 - 2.0 * t), EARTHSHINE)
        texture = _moon_map()
        if texture is not None:
            u = (np.arctan2(x, z) / (2.0 * math.pi) + 0.5) * (texture.shape[1] - 1)
            v = (1.0 - (np.arcsin(np.clip(y, -1.0, 1.0)) / math.pi + 0.5)) * (texture.shape[0] - 1)
            base = texture[np.clip(v.astype(int), 0, texture.shape[0] - 1), np.clip(u.astype(int), 0, texture.shape[1] - 1)]
        else:
            base = np.ones_like(lit)
        colour[inside] = (base * lit * emission)[:, None] * np.array(MOON_COLOR, dtype=np.float32)[None, :]
        # a soft edge of one pixel worth of angle
        edge = np.clip((radius - angle[inside]) / (radius * 0.02 + 1e-9), 0.0, 1.0)
        alpha[inside] = edge * state["fade"]
    halo_radius = radius * HALO_SCALE
    outside = angle < halo_radius
    if outside.any() and halo > 0.0:
        r = np.clip(angle[outside] / halo_radius, 0.0, 1.0)
        falloff = (1.0 - r) ** 2.6
        glow[outside] = (falloff * 0.30 * halo * state["fade"] * emission)[:, None] * np.array((0.75, 0.82, 1.0), dtype=np.float32)[None, :]
    return colour, alpha, glow

# ------------------------------------------------------------
# The 2D clouds: the picture of the cloud layer (clouds2d) looked up by the direction of every pixel, turned by the drift of the time.
# Returns a premultiplied colour and an alpha; nothing under the horizon (the picture has none).
def _cloud_layer(np, directions, cfg, seconds):
    import OpenImageIO as oiio
    from .clouds2d import CLOUD_TEXTURE_SIZE, cloud_texture_path
    size = (CLOUD_TEXTURE_SIZE[0] * 2, CLOUD_TEXTURE_SIZE[1] * 2)
    path = cloud_texture_path(cfg.get("cloud2d_coverage", 0.45), cfg.get("cloud2d_softness", 0.4), cfg.get("cloud2d_scale", 3.0), cfg.get("cloud2d_seed", 7), size)
    reader = oiio.ImageInput.open(path)
    spec = reader.spec()
    image = np.array(reader.read_image("float")).reshape(spec.height, spec.width, spec.nchannels)[:, :, 0]
    reader.close()
    drift = math.radians(float(cfg.get("cloud2d_drift", 0.0)) / 60.0 * seconds)
    x = directions[..., 0] * math.cos(drift) - directions[..., 2] * math.sin(drift)
    z = directions[..., 0] * math.sin(drift) + directions[..., 2] * math.cos(drift)
    u = (np.arctan2(x, z) / (2.0 * math.pi) + 0.5) % 1.0 * spec.width - 0.5
    v = (1.0 - (np.arcsin(np.clip(directions[..., 1], -1.0, 1.0)) / math.pi + 0.5)) * spec.height - 0.5
    x0, y0 = np.floor(u).astype(int), np.floor(v).astype(int)
    fx, fy = u - x0, v - y0
    x0w, x1w = x0 % spec.width, (x0 + 1) % spec.width
    y0c, y1c = np.clip(y0, 0, spec.height - 1), np.clip(y0 + 1, 0, spec.height - 1)
    mask = image[y0c, x0w] * (1 - fx) * (1 - fy) + image[y0c, x1w] * fx * (1 - fy) + image[y1c, x0w] * (1 - fx) * fy + image[y1c, x1w] * fx * fy
    if cfg.get("env_type", "Physical Sky") == "Physical Sky":
        reference = float(cfg.get("sky_int", 1.0))
    else:
        reference = float(cfg.get("hdri_int", 1.0)) * (2.0 ** float(cfg.get("hdri_ev", 0.0)))
    emission = float(cfg.get("cloud2d_brightness", 1.5)) * reference
    mask = np.clip(mask, 0.0, 1.0).astype(np.float32)
    return (mask * emission)[..., None] * np.ones(3, dtype=np.float32), mask

# ------------------------------------------------------------
# Everything of the sky for one camera at one resolution. cfg is the (exact) settings of the build, camera a camera_of_stage dict.
# Returns {"add": float RGB (stars, planets, Milky Way, halo), "moon": float RGB, "moon_alpha": float, "clouds": float RGB, "clouds_alpha"}.
def render_sky_plate(cfg, camera, width, height, seconds=0.0):
    import numpy as np
    from .ephemeris import apply_exact_sky
    from .environment import _night_fade
    cfg = apply_exact_sky(cfg)
    fade = _night_fade(cfg)
    plate = np.zeros((height, width, 3), dtype=np.float32)
    moon_colour = np.zeros((height, width, 3), dtype=np.float32)
    moon_alpha = np.zeros((height, width), dtype=np.float32)
    strength = float(cfg.get("stars_intensity", 1.0))
    latitude, hours = float(cfg.get("stars_latitude", 45.0)), float(cfg.get("stars_time", 0.0))
    directions = pixel_directions(np, camera, width, height)
    if cfg.get("stars_enable") and fade > 0.0:
        rotation = celestial_rotation(np, latitude, hours)
        catalog = star_catalog(latitude, hours, cfg.get("_snapshot"))
        columns, rows, front = project(np, camera, width, height, catalog["world"])
        margin = 40
        keep = front & (columns > -margin) & (columns < width + margin) & (rows > -margin) & (rows < height + margin)
        flux = catalog["flux"][keep]
        size = float(cfg.get("stars_size", 1.0))
        colours = catalog["colour"][keep] * (STAR_GAIN * strength * fade)
        # a bright star spreads a little more (the optics), a faint one is a point of the picture
        sigma = STAR_SIGMA * (1.0 + 0.35 * np.log2(1.0 + flux)) * size
        _splat(np, plate, columns[keep], rows[keep], colours * flux[:, None], sigma)
        # and a halo round the bright ones
        bright = flux > GLOW_FROM_FLUX
        if bright.any():
            glow_sigma = GLOW_SIGMA * max(0.05, float(cfg.get("stars_glow", 1.0)))
            _splat(np, plate, columns[keep][bright], rows[keep][bright], colours[bright] * (flux[bright] * 0.08)[:, None], np.full(int(bright.sum()), glow_sigma))
        if cfg.get("stars_milky", True):
            milky = _milky_way(np, directions, rotation, MILKY_GAIN * strength * fade)
            if milky is not None:
                horizon = np.clip((directions[..., 1] + 0.03) / 0.08, 0.0, 1.0)
                plate += (milky * horizon[..., None]).astype(np.float32)
    clouds, clouds_alpha = np.zeros((height, width, 3), dtype=np.float32), np.zeros((height, width), dtype=np.float32)
    if cfg.get("enable_clouds") and int(cfg.get("cloud_type", 0)) == 1:
        clouds, clouds_alpha = _cloud_layer(np, directions, cfg, seconds)
    state = moon_state(cfg)
    if cfg.get("moon_enable") and state["fade"] > 0.0:
        colour, alpha, glow = _moon_layers(np, directions, state, float(cfg.get("moon_size", 2.0)), float(cfg.get("moon_halo", 1.0)), float(cfg.get("moon_intensity", 1.0)))
        moon_colour, moon_alpha = colour, alpha
        plate += glow
    return {"add": plate, "moon": moon_colour, "moon_alpha": moon_alpha, "clouds": clouds, "clouds_alpha": clouds_alpha}

# ------------------------------------------------------------
# The picture the render and the plate make together: the sky is where the depth is 0, the plate is added there, the moon covers it.
def compose(np, beauty, depth, layers):
    sky = (depth <= 0.0)[..., None].astype(np.float32)
    alpha = layers["moon_alpha"][..., None] * sky
    picture = beauty[..., :3] * (1.0 - alpha) + layers["moon"] * alpha + layers["add"] * sky
    cloud_alpha = layers["clouds_alpha"][..., None] * sky
    return picture * (1.0 - cloud_alpha) + layers["clouds"] * cloud_alpha
