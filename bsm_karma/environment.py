# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Creates the camera, lights, sky, fog, clouds and moon in the Solaris stage for the Karma build.

# Houdini : 21 and 22

import hou
import math
import os
from .clouds2d import CLOUD_CARD_NAME, CLOUD_TEXTURE_SIZE, CLOUD_UV_VEX, cloud_card_file, cloud_texture_path
from .config import ATMOSPHERE_FAR_CLIP, CAMERA_CREATE_LABEL, CLOUD2D_BRIGHTNESS, CLOUD2D_RADIUS, CLOUD_LAYER_MATERIAL, CLOUD_LAYER_NAME, CLOUD_LAYER_PRIM, MOON_DISTANCE, MOON_MATERIALS, MOON_PRIM, DEFAULT_CLOUD_MATERIAL_PATH, GENERATED_CAMERA_NAME, QUICK_CLOUD_NAME, USD_CAMERA_PREFIX
from .moon import HALO_SCALE, HALO_VEX, MOON_COLOR, MOON_LIGHT_BASE, MOON_VEX, moon_file, moon_state
from .nightsky import NIGHT_MATS, NIGHT_PRIM, NIGHT_RADIUS, NIGHT_STARS_PRIM, NIGHT_UV_VEX, milky_way_texture_path, night_card_file, night_rotation, star_points_file
from .nodeutil import _get_or_create_node, _is_tool_node_candidate, _mark_tool_node, _pset, _remove_tool_node, _safe_connect, _set_first_existing_parm, _set_first_existing_parm_tuple, _set_light_color, _set_usd_input
from .util import _sky_data_file, _apply_saturation, _apply_tint, _kelvin_to_rgb

# ------------------------------------------------------------
def _is_lop_camera(node):
    if node is None:
        return False
    try:
        return "camera" in node.type().name().lower()
    except hou.Error:
        return False

# ------------------------------------------------------------
# Fix erreur = Render Settings veut le chemin de prim USD, pas le chemin du node
# (la caméra était ignorée avant)
def _camera_prim_path(cam):
    for parm_name in ("primpath", "primpattern"):
        parm = cam.parm(parm_name)
        if parm is not None:
            value = parm.evalAsString().strip()
            if value.startswith("/"):
                return value
    return "/cameras/{}".format(cam.name())

# ------------------------------------------------------------
def _lop_camera_nodes(stage):
    if stage is None:
        return []
    return [
        node for node in stage.children()
        if _is_lop_camera(node) and node.name() != GENERATED_CAMERA_NAME
    ]

# ------------------------------------------------------------
def _stage_camera_prims(usd_stage):
    from pxr import UsdGeom
    # bug trouvé et fixé: node.stage() renvoie None quand le nœud n'a pas (encore) de stage valide
    if usd_stage is None:
        return []
    return [str(prim.GetPath()) for prim in usd_stage.Traverse() if prim.IsA(UsdGeom.Camera)]

# ------------------------------------------------------------
def _apply_matrix_to_camera(cam, matrix_values, log_callback):
    try:
        matrix = hou.Matrix4(tuple(matrix_values))
        translate = matrix.extractTranslates()
        rotate = matrix.extractRotates()
    except (hou.Error, TypeError, ValueError) as exc:
        log_callback("[WARN] Could not read the viewport transform: {}".format(exc))
        return False
    for name, value in zip(("tx", "ty", "tz"), translate):
        _pset(cam, name, value, log_callback, quiet=True)
    for name, value in zip(("rx", "ry", "rz"), rotate):
        _pset(cam, name, value, log_callback, quiet=True)
    return True

# --------------------------------------------------
# bug trouvé et fixé: la position était remise à zéro à chaque build, une caméra bougée à la main
# revenait à sa place. Maintenant seulement à la création ou pour un match du viewport :)
def _create_camera(stage, focal, res_x, res_y, pos, log_callback, view_matrix=None):
    is_new = stage.node(GENERATED_CAMERA_NAME) is None
    cam = _get_or_create_node(stage, "camera", GENERATED_CAMERA_NAME)
    _pset(cam, "focalLength", float(focal), log_callback, quiet=True)
    if res_x / res_y > 2.0: _pset(cam, "aperture", 41.42, log_callback)
    if view_matrix:
        _apply_matrix_to_camera(cam, view_matrix, log_callback)
    elif is_new:
        _pset(cam, "tx", pos[0], log_callback); _pset(cam, "ty", pos[1], log_callback); _pset(cam, "tz", pos[2], log_callback)
    return cam

# --------------------------------------------------
def _clip_range_parms(cam):
    for name in ("clippingRange", "clippingrange"):
        parm_tuple = cam.parmTuple(name)
        if parm_tuple is not None and len(parm_tuple) == 2:
            return parm_tuple
    for parm_tuple in cam.parmTuples():
        if len(parm_tuple) == 2 and "clip" in parm_tuple.name().lower():
            return parm_tuple
    return None

# ------------------------------------------------------------
# The Karma Sky Atmosphere is a shell about a hundred kilometres thick: a camera whose far clipping range stops short of it
# renders black (SideFX documents it). The camera the tool made is given the range; a camera of yours is only checked.
def _ensure_atmosphere_clip(cam, cam_path, log_callback, wanted=ATMOSPHERE_FAR_CLIP):
    if cam is None:
        log_callback("[INFO] Volumetric Atmosphere: the camera {} is a USD camera, its far clipping range cannot be checked here: "
                     "it must reach about {:,.0f} units, or the sky renders black.".format(cam_path, wanted))
        return
    parm_tuple = _clip_range_parms(cam)
    if parm_tuple is None:
        log_callback("[WARN] Volumetric Atmosphere: no clipping range found on {}: its far clipping range must reach about {:,.0f} "
                     "units, or the sky renders black.".format(cam.path(), wanted))
        return
    near, far = parm_tuple.eval()
    if far >= wanted:
        return
    if cam.name() == GENERATED_CAMERA_NAME and _is_tool_node_candidate(cam):
        try:
            parm_tuple.set((near, wanted))
        except hou.Error as exc:
            log_callback("[WARN] Volumetric Atmosphere: the far clipping range of {} could not be raised: {}".format(cam.path(), exc))
            return
        log_callback("[INFO] Volumetric Atmosphere: the far clipping range of {} is now {:,.0f} (it was {:,.0f}), the atmosphere is "
                     "clipped otherwise.".format(cam.name(), wanted, far))
    else:
        log_callback("[WARN] Volumetric Atmosphere: the far clipping range of {} is {:,.0f}. It must reach about {:,.0f} units or the "
                     "sky renders black; the tool does not change a camera it did not make.".format(cam.path(), far, wanted))

# --------------------------------------------------
# (camera node or None, USD prim path). camera_choice is the create label, a camera LOP path, or
# 'usd:<prim path>' for a camera that lives in the geometry source (no node then).
def _resolve_render_camera(stage, cfg, log_callback):
    choice = str(cfg.get("camera_choice", CAMERA_CREATE_LABEL)).strip()

    if choice.startswith(USD_CAMERA_PREFIX):
        prim_path = choice[len(USD_CAMERA_PREFIX):]
        if not (cfg.get("geo_source") or "").strip():
            log_callback("[WARN] Camera prim {} only exists in the stage when its LOP is chosen as Geometry Source.".format(prim_path))
        _remove_tool_node(stage, GENERATED_CAMERA_NAME, log_callback, "a USD camera is used instead")
        return None, prim_path

    if choice and choice != CAMERA_CREATE_LABEL:
        cam = hou.node(choice)
        if _is_lop_camera(cam) and cam.name() != GENERATED_CAMERA_NAME:
            _remove_tool_node(stage, GENERATED_CAMERA_NAME, log_callback, "{} is used instead".format(cam.name()))
            return cam, _camera_prim_path(cam)
        log_callback("[WARN] Selected camera not found or invalid: {} | fallback to a new camera.".format(choice))

    cam = _create_camera(
        stage,
        float(cfg.get("new_cam_focal", 35.0)),
        cfg["res_x"],
        cfg["res_y"],
        (0.0, 2.0, 8.0),
        log_callback,
        view_matrix=cfg.get("viewport_matrix") if cfg.get("new_cam_from_viewport") else None,
    )
    return cam, _camera_prim_path(cam)

# ------------------------------------------------------------
def _create_dome_light(stage, prev, intensity, texture_path, log_callback, name="dome_light", hdri_opts=None):
    dome = _get_or_create_node(stage, "domelight", name)
    ev = 0.0 if hdri_opts is None else float(hdri_opts.get("hdri_ev", 0.0))
    final_intensity = max(0.0, float(intensity) * (2.0 ** ev))

    if not _set_usd_input(dome, "intensity", final_intensity, log_callback):
        _set_first_existing_parm(dome, ("intensity",), final_intensity, log_callback)
    if not (_set_usd_input(dome, "texturefile", texture_path, log_callback)
            or _set_usd_input(dome, "texture_file", texture_path, log_callback)):
        log_callback("[WARN] Dome light: texture parameter not found on {}.".format(dome.type().name()))

    if hdri_opts is not None:
        _pset(dome, "ry", float(hdri_opts.get("hdri_rot", 0.0)), log_callback, quiet=True)
        # no blur here: Karma's light schema has no attribute for it on H22

        temp_rgb = _kelvin_to_rgb(float(hdri_opts.get("hdri_temp", 6500.0)))
        tint_rgb = _apply_tint(temp_rgb, float(hdri_opts.get("hdri_tint", 0.0)))
        final_rgb = _apply_saturation(tint_rgb, float(hdri_opts.get("hdri_sat", 1.0)))
        _set_light_color(dome, final_rgb)

    _safe_connect(dome, prev)
    return dome

# ------------------------------------------------------------
# Color of a lamp from its temperature and tint sliders (lamp = "key", "fill" or "rim"; the window light of the Interior
# mode is the key). 6500 K and no tint is the neutral white the lamps had before.
def _lamp_color(cfg, lamp):
    rgb = _kelvin_to_rgb(float(cfg.get("lamp_{}_temp".format(lamp), 6500.0)))
    return _apply_tint(rgb, float(cfg.get("lamp_{}_tint".format(lamp), 0.0)))

# ------------------------------------------------------------
def _create_area_light(stage, prev, intensity, log_callback, name="area_light", pos=(3.0, 4.0, 3.0), rot=(-45.0, 30.0, 0.0), color=None):
    is_new = stage.node(name) is None
    area = _get_or_create_node(stage, "light", name)
    _set_usd_input(area, "intensity", float(intensity), log_callback)
    if color is not None and not _set_light_color(area, color):
        log_callback("[WARN] {}: no color parameter found, the lamp color was not set.".format(name))
    # size and placement only at creation: a light moved by hand must stay where it was put
    if is_new:
        _set_usd_input(area, "width", 1.5, log_callback)
        _set_usd_input(area, "height", 1.5, log_callback)
        _pset(area, "tx", pos[0], log_callback); _pset(area, "ty", pos[1], log_callback); _pset(area, "tz", pos[2], log_callback)
        _pset(area, "rx", rot[0], log_callback); _pset(area, "ry", rot[1], log_callback); _pset(area, "rz", rot[2], log_callback)
    _safe_connect(area, prev)
    return area

# ------------------------------------------------------------
# A light looks down -Z: its +Z axis points at the sky position (azimuth 0 is -Z, 90 is +X, as for the wind of the clouds).
# Returns the unit vector towards that position.
def _aim_light(light, elevation_deg, azimuth_deg, log_callback):
    elevation = math.radians(elevation_deg)
    azimuth = math.radians(azimuth_deg)
    toward = hou.Vector3(math.sin(azimuth) * math.cos(elevation), math.sin(elevation), -math.cos(azimuth) * math.cos(elevation))
    side = hou.Vector3(0.0, 1.0, 0.0).cross(toward)
    if side.length() < 1e-6:
        side = hou.Vector3(1.0, 0.0, 0.0)
    side = side.normalized()
    up = toward.cross(side)
    rotation = hou.Matrix4(hou.Matrix3((side[0], side[1], side[2], up[0], up[1], up[2], toward[0], toward[1], toward[2])))
    for name, value in zip(("rx", "ry", "rz"), rotation.extractRotates()):
        _pset(light, name, value, log_callback, quiet=True)
    return toward

# ------------------------------------------------------------
# Volumetric Atmosphere: a Karma Sky Atmosphere and a distant light as the sun, instead of the Karma Physical Sky node.
# The sun is normalized (an irradiance whatever its angular size), without it a sun of intensity 1 is about 200 times too
# weak and everything renders black: found by comparing with the sun that Karma Physical Sky makes (same picture then).
ATMOSPHERE_SUN_DIVIDER = 3.0

def _create_atmosphere_sky(stage, prev, cfg, log_callback):
    try:
        atmosphere = _get_or_create_node(stage, "karmaskyatmosphere", "sky_atmosphere")
        rayleigh = float(cfg.get("sky_atm_rayleigh", 1.0))
        mie = float(cfg.get("sky_atm_mie", 1.0))
        _pset(atmosphere, "rayleighscale", 3e-05 * rayleigh, log_callback, quiet=True)
        _pset(atmosphere, "miescatterscale", 5e-06 * mie, log_callback, quiet=True)
        _safe_connect(atmosphere, prev)

        sun = _get_or_create_node(stage, "light", "sky_sun")
        _pset(sun, "lighttype", "UsdLuxDistantLight", log_callback, quiet=True)
        # the slider is the one of the basic sky (the Midday preset is 3). A physical sun of 3 burns the atmosphere to
        # white in a render, Karma's own default sun is 1: the slider is divided by 3 so that Midday looks like it
        _set_usd_input(sun, "intensity", float(cfg["sky_sun_int"]) / ATMOSPHERE_SUN_DIVIDER, log_callback)
        _set_usd_input(sun, "angle", float(cfg["sky_sun_size"]), log_callback)
        _set_usd_input(sun, "normalize", 1, log_callback)
        _set_light_color(sun, _kelvin_to_rgb(float(cfg.get("sky_sun_temp", 5500.0))))
        toward = _aim_light(sun, float(cfg["sky_elev"]), float(cfg["sky_azim"]), log_callback)
        _safe_connect(sun, atmosphere)

        # the atmosphere is lit by the sun alone: below the horizon there is no daylight to scatter
        if float(cfg["sky_elev"]) < 0.0:
            log_callback("[WARN] Volumetric Atmosphere with the sun at {:.1f} deg (below the horizon) is dark, that is night. "
                         "Raise Solar Altitude above 0, or pick a daytime preset. It only renders in Karma.".format(float(cfg["sky_elev"])))
        log_callback("[INFO] Volumetric Atmosphere renders in Karma CPU and XPU. If it stays black: the sun above the horizon, the far "
                     "clipping range of the camera (raised for the camera the tool makes), then a render in CPU to tell the engines apart.")
        return sun
    except hou.OperationFailed as exc:
        _remove_tool_node(stage, "sky_sun", log_callback)
        _remove_tool_node(stage, "sky_atmosphere", log_callback)
        log_callback("[WARN] Volumetric atmosphere could not be built: {}".format(exc))
        return prev

def _create_physical_sky(stage, prev, cfg, log_callback):
    # one sky or the other: the nodes of the mode that is not wanted go
    if cfg.get("sky_mode", 0) == 1:
        _remove_tool_node(stage, "physical_sky", log_callback)
        return _create_atmosphere_sky(stage, prev, cfg, log_callback)
    _remove_tool_node(stage, "sky_sun", log_callback)
    _remove_tool_node(stage, "sky_atmosphere", log_callback)
    try:
        sky = _get_or_create_node(stage, "karmaphysicalsky", "physical_sky")
        
        _pset(sky, "skymode", 0, log_callback, quiet=True)

        # one name per Houdini generation: a parm that none of them matches is reported, not skipped silently
        missing = []
        for label, names, value in (
            ("sun altitude", ("solar_altitude", "sunelevation"), float(cfg["sky_elev"])),
            ("sun azimuth", ("solar_azimuth", "sunazimuth"), float(cfg["sky_azim"])),
            ("sun intensity", ("sun_intensity", "sunintensity"), float(cfg["sky_sun_int"])),
            ("sun size", ("angle", "sunsize"), float(cfg["sky_sun_size"])),
        ):
            if not _set_first_existing_parm(sky, names, value, log_callback):
                missing.append(label)
        if missing:
            log_callback("[WARN] Physical Sky: no matching parameter for {} on {} (this Houdini version?).".format(
                ", ".join(missing), sky.type().nameWithCategory()))
        
        sun_temp = float(cfg.get("sky_sun_temp", 5500.0))
        sun_color = _kelvin_to_rgb(sun_temp)
        _set_first_existing_parm_tuple(sky, ("sun_color", "suncolor"), sun_color, log_callback)

        _pset(sky, "turbidity",    float(cfg["sky_turbidity"]), log_callback, quiet=True)
        
        # volumes absorb sky light, boost it when fog or clouds are on
        sky_int = float(cfg["sky_int"])
        # fog and 3D clouds are volumes that dim the sky behind them; the 2D layer is a picture, it does not
        if cfg.get("enable_fog") or (cfg.get("enable_clouds") and int(cfg.get("cloud_type", 0)) == 0):
            sky_int *= 4.0

        if not _set_first_existing_parm(sky, ("sky_intensity", "skyintensity"), sky_int, log_callback):
            log_callback("[WARN] Physical Sky: no matching parameter for sky intensity on {}.".format(
                sky.type().nameWithCategory()))
        
        _set_first_existing_parm(sky, ("horizon_blur", "horizonblurfalloff"), float(cfg["sky_hz_blur"]), log_callback)

        if "sky_atm_rayleigh" in cfg:
            rayleigh = float(cfg["sky_atm_rayleigh"])
            mie = float(cfg["sky_atm_mie"])
            if sky.parm("rayleighscale") is not None:
                _pset(sky, "rayleighscale", 3e-05 * rayleigh, log_callback, quiet=True)
                _pset(sky, "miescatterscale", 5e-06 * mie, log_callback, quiet=True)
            else:
                _set_first_existing_parm(sky, ("atmosphere_rayleigh", "rayleigh"), rayleigh, log_callback)
                _set_first_existing_parm(sky, ("atmosphere_mie", "mie", "haze"), mie, log_callback)
        _pset(sky, "enablesun", 1, log_callback, quiet=True)

        _safe_connect(sky, prev)

        return sky
    except hou.OperationFailed as exc:
        _remove_tool_node(stage, "sky_atmosphere_linker", log_callback)
        _remove_tool_node(stage, "physical_sky", log_callback)
        log_callback("[WARN] Physical sky could not be built: {}".format(exc))
        return prev

# ------------------------------------------------------------
def _create_fog_branch(stage, prev, cfg, log_callback):
    fog_geo = _get_or_create_node(stage, "karmafogbox", "atmosphere_fog")
    
    fog_radius = max(5.0, float(cfg.get("fog_radius", 120.0))) * 20.0
    fog_height = float(cfg.get("fog_height", 30.0))
    fog_density = float(cfg.get("fog_density", 0.05))
    fog_phase = float(cfg.get("fog_phase", 0.4))
    
    _pset(fog_geo, "primpath", "/World/Environment/Fog", log_callback, quiet=True)
    _pset(fog_geo, "shape", 0, log_callback, quiet=True) # 0 = Box
    
    _pset(fog_geo, "density", fog_density, log_callback, quiet=True)
    _pset(fog_geo, "shadow", fog_density * 0.8, log_callback, quiet=True)
    _pset(fog_geo, "phase", fog_phase, log_callback, quiet=True)
    
    amb_color = (
        float(cfg.get("sky_amb_r", 1.0)),
        float(cfg.get("sky_amb_g", 1.0)),
        float(cfg.get("sky_amb_b", 1.0))
    )
    _set_first_existing_parm_tuple(fog_geo, ("color",), amb_color, log_callback)

    _pset(fog_geo, "sx", fog_radius, log_callback, quiet=True)
    _pset(fog_geo, "sy", fog_height * 2.0, log_callback, quiet=True)
    _pset(fog_geo, "sz", fog_radius, log_callback, quiet=True)
    
    _pset(fog_geo, "ty", fog_height, log_callback, quiet=True)
    
    _pset(fog_geo, "addnoise", 1, log_callback, quiet=True)
    _pset(fog_geo, "amplitude", float(cfg.get("fog_noise_amp", 0.5)), log_callback, quiet=True)
    # bug trouvé et fixé: Karma steps the fog with the size of the noise features: 0.1 m noise in a 2.4 km box took 105 s (80 x 50, 2 samples).
    # Slider read as hundreds of metres per unit, floor 10 m: same picture, 12 times faster than 1 m and 60 times than 0.1 m.
    _pset(fog_geo, "noisescale", max(10.0, 100.0 * float(cfg.get("fog_noise_scale", 0.1))), log_callback, quiet=True)

    _safe_connect(fog_geo, prev)
    return fog_geo

# ------------------------------------------------------------
def _create_quick_cloud_material(stage, prev, cfg, log_callback):
    try:
        from husd import quickmaterials
    except ImportError:
        log_callback("[WARN] husd.quickmaterials is not available in this Houdini: no Quick Cloud Material.")
        return None

    node = stage.node(QUICK_CLOUD_NAME)
    if node is not None and not _is_tool_node_candidate(node):
        log_callback("[WARN] {} was not created by Karma Builder: left untouched, no Quick Cloud Material.".format(node.path()))
        return None
    if node is None:
        node = stage.createNode("editmaterialproperties", QUICK_CLOUD_NAME)
        try:
            quickmaterials.createQuickCloudMaterial(quick_material_node=node)
        except (hou.Error, AttributeError, KeyError, TypeError) as exc:
            node.destroy()
            log_callback("[WARN] Could not set up the Quick Cloud Material: {}".format(exc))
            return None
    _mark_tool_node(node)

    # 0.2 on the slider is SideFX's default density scale (1)
    _pset(node, "densityscale", max(0.0, float(cfg.get("cloud_density", 0.20)) * 5.0), log_callback, quiet=True)
    _safe_connect(node, prev)
    return node

# ------------------------------------------------------------
# An animation the tool made on a parameter: an expression of the time in seconds ($T) with plain numbers in it, so it
# plays at any frame rate. The parameter is cleared first at every build: a value set over an animation would not stay.
def _animate_parm(parm, per_second, log_callback):
    try:
        parm.deleteAllKeyframes()
        if abs(per_second) > 1e-9:
            parm.setExpression("$T*{:.8g}".format(per_second), hou.exprLanguage.Hscript)
    except (hou.Error, AttributeError) as exc:
        log_callback("[WARN] Clouds: the animation of {} was not set: {}".format(parm.name(), exc))

# ------------------------------------------------------------
# 2D clouds: a procedural picture on a big sphere around the scene (emissive, opaque only where there is a cloud). No volume.
# A live update uses a smaller picture, the next Build writes the full one.
# The brightness slider is relative to the sky (1 = as bright as the sky).
def _create_cloud_layer_2d(stage, prev, cfg, log_callback):
    size = (CLOUD_TEXTURE_SIZE[0] // 2, CLOUD_TEXTURE_SIZE[1] // 2) if cfg.get("live") else CLOUD_TEXTURE_SIZE
    path = cloud_texture_path(
        cfg.get("cloud2d_coverage", 0.45), cfg.get("cloud2d_softness", 0.4), cfg.get("cloud2d_scale", 3.0),
        cfg.get("cloud2d_seed", 7), size)
    if cfg.get("env_type", "Physical Sky") == "Physical Sky":
        reference = float(cfg.get("sky_int", 1.0))
    else:
        reference = float(cfg.get("hdri_int", 1.0)) * (2.0 ** float(cfg.get("hdri_ev", 0.0)))
    intensity = float(cfg.get("cloud2d_brightness", CLOUD2D_BRIGHTNESS)) * reference
    card_file = cloud_card_file(path, intensity)

    card = _get_or_create_node(stage, "sopcreate", CLOUD_LAYER_NAME)
    if card.isLockedHDA():
        card.allowEditingOfContents()
    _set_first_existing_parm(card, ("primpath", "destpath"), CLOUD_LAYER_PRIM, log_callback)
    _pset(card, "pathprefix", CLOUD_LAYER_PRIM, log_callback, quiet=True)
    sopnet = card.node("sopnet")
    if sopnet is not None and sopnet.node("cloud_sphere") is None:
        for n in sopnet.children():
            if n.name() not in ("OUT", "output"):
                n.destroy()
        sphere = sopnet.createNode("sphere", "cloud_sphere")
        _mark_tool_node(sphere)
        _pset(sphere, "type", 2, log_callback, quiet=True)        # polygon mesh
        _pset(sphere, "orient", 1, log_callback, quiet=True)      # Y axis
        _pset(sphere, "rows", 60, log_callback, quiet=True)
        _pset(sphere, "cols", 120, log_callback, quiet=True)
        for axis in ("radx", "rady", "radz"):
            _pset(sphere, axis, CLOUD2D_RADIUS, log_callback, quiet=True)
        # the sphere SOP has no lat-long UVs (the polar ones are a top view): written per vertex, the seam fixed per face
        uv = sopnet.createNode("attribwrangle", "cloud_uv")
        _mark_tool_node(uv)
        uv.setInput(0, sphere)
        _pset(uv, "class", "vertex", log_callback, quiet=True)
        _pset(uv, "snippet", CLOUD_UV_VEX, log_callback, quiet=True)
        out = sopnet.node("OUT") or sopnet.node("output")
        if out is None:
            out = sopnet.createNode("output", "OUT")
        out.setInput(0, uv)
        out.setDisplayFlag(True)
        out.setRenderFlag(True)
    _safe_connect(card, prev)

    ref = _get_or_create_node(stage, "reference", CLOUD_LAYER_NAME + "_ref")
    _pset(ref, "filepath1", card_file, log_callback, quiet=True)
    _pset(ref, "primpath1", CLOUD_LAYER_MATERIAL, log_callback, quiet=True)
    _pset(ref, "filerefprim1", "", log_callback, quiet=True)    # "" is the prim path typed below
    _pset(ref, "filerefprimpath1", "/MaterialX/Materials/{}".format(CLOUD_CARD_NAME), log_callback, quiet=True)
    _safe_connect(ref, card)

    assign = _get_or_create_node(stage, "assignmaterial", CLOUD_LAYER_NAME + "_mat")
    _pset(assign, "nummaterials", 1, log_callback, quiet=True)
    _pset(assign, "primpattern1", CLOUD_LAYER_PRIM, log_callback, quiet=True)
    _pset(assign, "matspecpath1", CLOUD_LAYER_MATERIAL, log_callback, quiet=True)
    _safe_connect(assign, ref)

    drift = float(cfg.get("cloud2d_drift", 0.0))
    if card.parm("ry") is not None:
        _animate_parm(card.parm("ry"), drift / 60.0, log_callback)
    elif drift > 0.0:
        log_callback("[WARN] 2D clouds: the cloud sphere has no rotation parameter, the drift was not set.")
    log_callback("[INFO] 2D clouds: sphere {} at emission {:.2f} ({} x the {} {:.2f}), picture {}".format(
        card.name(), intensity, "{:.2f}".format(float(cfg.get("cloud2d_brightness", CLOUD2D_BRIGHTNESS))),
        "sky intensity" if cfg.get("env_type", "Physical Sky") == "Physical Sky" else "HDRI intensity", reference, os.path.basename(path)))
    return assign

def _create_cloud_branch(stage, prev, cfg, log_callback):
    cloud_geo = _get_or_create_node(stage, "sopcreate", "cloud_geo")
    if cloud_geo.isLockedHDA():
        cloud_geo.allowEditingOfContents()
    _set_first_existing_parm(cloud_geo, ("primpath", "destpath"), "/World/Environment/Clouds", log_callback)
    _pset(cloud_geo, "pathprefix", "/World/Environment/Clouds", log_callback, quiet=True)

    sopnet = cloud_geo.node("sopnet")
    if sopnet:
        skybox = sopnet.node("cloud_base")
        if not skybox:
            try:
                for n in sopnet.children():
                    if n.name() not in ["OUT", "output"]:
                        n.destroy()
            except hou.Error as e:
                log_callback(f"[WARN] Failed to destroy nodes in cloud sopnet: {e}")
            
            skybox = sopnet.createNode("skybox", "cloud_base")
            _mark_tool_node(skybox)
            _pset(skybox, "sizex", 1000, log_callback, quiet=True)
            _pset(skybox, "sizey", 200, log_callback, quiet=True)
            _pset(skybox, "sizez", 1000, log_callback, quiet=True)
            _pset(skybox, "divsize", float(cfg.get("cloud_precision", 5.0)), log_callback, quiet=True)

            billowy = sopnet.createNode("cloudbillowynoise", "add_detail")
            _mark_tool_node(billowy)
            billowy.setInput(0, skybox)
            _set_first_existing_parm(billowy, ("niters", "iterations"), 4, log_callback)
            _set_first_existing_parm(billowy, ("doworleydetails", "useworley"), 1, log_callback)
            _pset(billowy, "offset", float(cfg.get("cloud_clip", 0.35)), log_callback, quiet=True)

            adjust = sopnet.createNode("cloudadjustdensityprofile", "adjust_density")
            _mark_tool_node(adjust)
            adjust.setInput(0, billowy)

            out_node = sopnet.node("OUT")
            if out_node is None:
                out_node = sopnet.createNode("output", "OUT_CLOUD")
                _mark_tool_node(out_node)
            out_node.setInput(0, adjust)
            out_node.setDisplayFlag(True)
            out_node.setRenderFlag(True)

            sopnet.layoutChildren()

    _safe_connect(cloud_geo, prev)

    cloud_xform = _get_or_create_node(stage, "xform", "cloud_xform")
    _set_first_existing_parm(
        cloud_xform,
        ("primpattern", "primpath", "prims", "primpattern1"),
        "/World/Environment/Clouds*",
        log_callback,
    )
    # the translate is set below: an animation of the wind from an earlier build is taken off first
    moving = next((cloud_xform.parmTuple(n) for n in ("t", "translate", "trans") if cloud_xform.parmTuple(n) is not None), None)
    if moving is not None and len(moving) == 3:
        for component in (moving[0], moving[2]):
            try:
                component.deleteAllKeyframes()
            except hou.Error:
                pass
    cloud_altitude = float(cfg.get("cloud_altitude", 140.0))
    cloud_scale = max(5.0, float(cfg.get("cloud_scale", 180.0)))
    _set_first_existing_parm_tuple(
        cloud_xform,
        ("t", "translate", "trans"),
        (0.0, cloud_altitude, 0.0),
        log_callback,
    )
    # wind: the clouds slide along the ground plane with the time (direction 0 is -Z, 90 is +X)
    speed = float(cfg.get("cloud_wind_speed", 0.0))
    angle = math.radians(float(cfg.get("cloud_wind_dir", 90.0)))
    translate = next((cloud_xform.parmTuple(n) for n in ("t", "translate", "trans") if cloud_xform.parmTuple(n) is not None), None)
    if translate is not None and len(translate) == 3:
        _animate_parm(translate[0], speed * math.sin(angle), log_callback)
        _animate_parm(translate[2], -speed * math.cos(angle), log_callback)
    elif speed > 0.0:
        log_callback("[WARN] Clouds: the transform has no translate parameter, the wind was not set.")
    scale_c = cloud_scale / 100.0
    _set_first_existing_parm_tuple(
        cloud_xform,
        ("s", "scale", "scales"),
        (scale_c, scale_c * 0.5, scale_c),
        log_callback,
    )
    _safe_connect(cloud_xform, cloud_geo)

    assign = _get_or_create_node(stage, "assignmaterial", "assign_cloud_shader")
    _pset(assign, "primpattern1", "/World/Environment/Clouds*", log_callback, quiet=True)

    cloud_mat_path = (cfg.get("cloud_material_path") or "").strip()
    upstream = cloud_xform
    if not cloud_mat_path or cloud_mat_path == DEFAULT_CLOUD_MATERIAL_PATH:
        quick = _create_quick_cloud_material(stage, cloud_xform, cfg, log_callback)
        if quick is not None:
            upstream = quick
            primpath = quick.parm("primpath")
            cloud_mat_path = primpath.evalAsString() if primpath is not None else ""
    else:
        _remove_tool_node(stage, QUICK_CLOUD_NAME, log_callback, "a custom cloud material is used")
    if not cloud_mat_path or cloud_mat_path == DEFAULT_CLOUD_MATERIAL_PATH:
        log_callback("[WARN] No cloud material available: clouds will render with the default volume.")

    _pset(assign, "matspecpath1", cloud_mat_path, log_callback, quiet=True)
    _safe_connect(assign, upstream)
    return assign

# ------------------------------------------------------------
# The moon: placed from the sun and the phase slider, a lit sphere (phase from the sun's direction, a map if datas/Sky has one) and a halo, with a distant light.
# Built only while above the horizon: nothing is added to the scene or the render the rest of the time.
def _create_moon(stage, prev, cfg, log_callback):
    state = moon_state(cfg)
    fade, altitude, azimuth = state["fade"], state["altitude"], state["azimuth"]
    strength = float(cfg.get("moon_intensity", 1.0))
    size = max(0.1, float(cfg.get("moon_size", 2.0)))
    halo = float(cfg.get("moon_halo", 1.0))
    # by day the moon is a pale disc and its light is nothing
    emission = 0.9 * strength * (1.0 - 0.55 * state["daylight"])

    light = _get_or_create_node(stage, "light", "sky_moon")
    _pset(light, "lighttype", "UsdLuxDistantLight", log_callback, quiet=True)
    _set_usd_input(light, "intensity", MOON_LIGHT_BASE * strength * state["lit"] * fade * (1.0 - state["daylight"]), log_callback)
    _set_usd_input(light, "angle", size, log_callback)
    _set_usd_input(light, "normalize", 1, log_callback)
    _set_light_color(light, MOON_COLOR)
    toward = _aim_light(light, altitude, azimuth, log_callback)
    _safe_connect(light, prev)

    radius = MOON_DISTANCE * math.tan(math.radians(size) / 2.0)

    def sphere_node(name, wrangle, sphere_radius, distance, log=log_callback):
        node = _get_or_create_node(stage, "sopcreate", name)
        if node.isLockedHDA():
            node.allowEditingOfContents()
        _set_first_existing_parm(node, ("primpath", "destpath"), MOON_PRIM + "_" + name, log)
        _pset(node, "pathprefix", MOON_PRIM + "_" + name, log, quiet=True)
        sopnet = node.node("sopnet")
        if sopnet is not None and sopnet.node("moon_sphere") is None:
            for n in sopnet.children():
                if n.name() not in ("OUT", "output"):
                    n.destroy()
            sphere = sopnet.createNode("sphere", "moon_sphere")
            _mark_tool_node(sphere)
            _pset(sphere, "type", 2, log, quiet=True)
            _pset(sphere, "orient", 1, log, quiet=True)
            _pset(sphere, "rows", 48, log, quiet=True)
            _pset(sphere, "cols", 96, log, quiet=True)
            wr = sopnet.createNode("attribwrangle", "moon_attribs")
            _mark_tool_node(wr)
            wr.setInput(0, sphere)
            _pset(wr, "class", "vertex", log, quiet=True)
            _pset(wr, "snippet", wrangle, log, quiet=True)
            out = sopnet.node("OUT") or sopnet.node("output")
            if out is None:
                out = sopnet.createNode("output", "OUT")
            out.setInput(0, wr)
            out.setDisplayFlag(True)
            out.setRenderFlag(True)
        sphere = sopnet.node("moon_sphere") if sopnet is not None else None
        if sphere is not None:
            for axis in ("radx", "rady", "radz"):
                _pset(sphere, axis, sphere_radius, log, quiet=True)
        for pname, value in zip(("tx", "ty", "tz"), toward * distance):
            _pset(node, pname, value, log, quiet=True)
        # the near side of the map (longitude 0, in the middle of it) faces the observer, north up
        _aim_light(node, -altitude, (azimuth + 180.0) % 360.0, log)
        return node

    disc = sphere_node("sky_moon_disc", MOON_VEX, radius, MOON_DISTANCE)
    _safe_connect(disc, light)
    # the halo sphere sits behind the disc (its near pole at the moon's distance): in front it would veil the moon
    halo_node = sphere_node("sky_moon_halo", HALO_VEX, radius * HALO_SCALE, MOON_DISTANCE + radius * HALO_SCALE)
    _safe_connect(halo_node, disc)

    ref = _get_or_create_node(stage, "reference", "sky_moon_ref")
    sun_dir = [float(c) for c in state["sun"]]
    _pset(ref, "filepath1", moon_file(emission, fade, _sky_data_file("moon.jpg"), sun_dir, halo), log_callback, quiet=True)
    _pset(ref, "primpath1", MOON_MATERIALS, log_callback, quiet=True)
    _pset(ref, "filerefprim1", "", log_callback, quiet=True)
    _pset(ref, "filerefprimpath1", "/MaterialX/Materials", log_callback, quiet=True)
    _safe_connect(ref, halo_node)

    assign = _get_or_create_node(stage, "assignmaterial", "sky_moon_mat")
    _pset(assign, "nummaterials", 2, log_callback, quiet=True)
    _pset(assign, "primpattern1", MOON_PRIM + "_sky_moon_disc", log_callback, quiet=True)
    _pset(assign, "matspecpath1", MOON_MATERIALS + "/Moon", log_callback, quiet=True)
    _pset(assign, "primpattern2", MOON_PRIM + "_sky_moon_halo", log_callback, quiet=True)
    _pset(assign, "matspecpath2", MOON_MATERIALS + "/MoonHalo", log_callback, quiet=True)
    _safe_connect(assign, ref)
    log_callback("[INFO] Moon: altitude {:.1f}, azimuth {:.0f}, {:.0f}% lit, {:.0f}% shown.".format(altitude, azimuth, state["lit"] * 100.0, fade * 100.0))
    return assign

# ------------------------------------------------------------
# Stars: the catalogue as points (nightsky.py), coloured, sized by magnitude, halo for the bright ones, own twinkle; the Milky Way, a soft picture, on a sphere behind.
# Turned for latitude and hour. Shown from sun below -3 degrees, all there at -12; the nodes are built only from then on.
def _night_fade(cfg):
    from .ephemeris import apply_exact_sky
    cfg = apply_exact_sky(cfg)
    t = min(max((-3.0 - float(cfg.get("sky_elev", 30.0))) / 9.0, 0.0), 1.0)
    return round(t * t * (3.0 - 2.0 * t) * 20.0) / 20.0

# ------------------------------------------------------------
def _create_night_sky(stage, prev, cfg, log_callback):
    from .ephemeris import apply_exact_sky
    cfg = apply_exact_sky(cfg)
    snapshot = cfg.get("_snapshot")
    fade = _night_fade(cfg)
    strength = float(cfg.get("stars_intensity", 1.0))
    latitude, hours = float(cfg.get("stars_latitude", 45.0)), float(cfg.get("stars_time", 0.0))
    milky_texture = milky_way_texture_path() if cfg.get("stars_milky", True) else ""
    points_file = star_points_file(latitude, hours, float(cfg.get("stars_size", 1.0)), 3.0, snapshot)
    chain = prev

    if milky_texture:
        milky = _get_or_create_node(stage, "sopcreate", "sky_milky")
        if milky.isLockedHDA():
            milky.allowEditingOfContents()
        _set_first_existing_parm(milky, ("primpath", "destpath"), NIGHT_PRIM, log_callback)
        _pset(milky, "pathprefix", NIGHT_PRIM, log_callback, quiet=True)
        sopnet = milky.node("sopnet")
        if sopnet is not None and sopnet.node("night_sphere") is None:
            for n in sopnet.children():
                if n.name() not in ("OUT", "output"):
                    n.destroy()
            sphere = sopnet.createNode("sphere", "night_sphere")
            _mark_tool_node(sphere)
            _pset(sphere, "type", 2, log_callback, quiet=True)
            _pset(sphere, "orient", 1, log_callback, quiet=True)
            _pset(sphere, "rows", 60, log_callback, quiet=True)
            _pset(sphere, "cols", 120, log_callback, quiet=True)
            for axis in ("radx", "rady", "radz"):
                _pset(sphere, axis, NIGHT_RADIUS, log_callback, quiet=True)
            uv = sopnet.createNode("attribwrangle", "night_uv")
            _mark_tool_node(uv)
            uv.setInput(0, sphere)
            _pset(uv, "class", "vertex", log_callback, quiet=True)
            _pset(uv, "snippet", NIGHT_UV_VEX, log_callback, quiet=True)
            out = sopnet.node("OUT") or sopnet.node("output")
            if out is None:
                out = sopnet.createNode("output", "OUT")
            out.setInput(0, uv)
            out.setDisplayFlag(True)
            out.setRenderFlag(True)
        for name, value in zip(("rx", "ry", "rz"), night_rotation(latitude, hours)):
            _pset(milky, name, value, log_callback, quiet=True)
        _safe_connect(milky, chain)
        chain = milky

    points = _get_or_create_node(stage, "reference", "sky_stars_ref")
    _pset(points, "filepath1", points_file, log_callback, quiet=True)
    _pset(points, "primpath1", NIGHT_STARS_PRIM, log_callback, quiet=True)
    _pset(points, "filerefprim1", "defaultPrim", log_callback, quiet=True)
    _safe_connect(points, chain)

    mats = _get_or_create_node(stage, "reference", "sky_stars_mtl")
    _pset(mats, "filepath1", night_card_file(milky_texture, fade, strength, float(cfg.get("stars_twinkle", 1.0)), float(cfg.get("stars_glow", 1.0))),
          log_callback, quiet=True)
    _pset(mats, "primpath1", NIGHT_MATS, log_callback, quiet=True)
    _pset(mats, "filerefprim1", "", log_callback, quiet=True)
    _pset(mats, "filerefprimpath1", "/MaterialX/Materials", log_callback, quiet=True)
    _safe_connect(mats, points)

    rows = [(NIGHT_STARS_PRIM + "/Stars", "StarMat"), (NIGHT_STARS_PRIM + "/StarGlow", "GlowMat")]
    if milky_texture:
        rows.append((NIGHT_PRIM, "MilkyMat"))
    assign = _get_or_create_node(stage, "assignmaterial", "sky_stars_mat")
    _pset(assign, "nummaterials", len(rows), log_callback, quiet=True)
    for index, (pattern, material) in enumerate(rows, 1):
        _pset(assign, "primpattern{}".format(index), pattern, log_callback, quiet=True)
        _pset(assign, "matspecpath{}".format(index), "{}/{}".format(NIGHT_MATS, material), log_callback, quiet=True)
    _safe_connect(assign, mats)
    log_callback("[INFO] Night sky: {:.0f}% shown (latitude {:.0f}, {:.1f} h){}.".format(
        fade * 100.0, latitude, hours, ", Milky Way" if milky_texture else ""))
    return assign

# ------------------------------------------------------------
def _create_environment_merge(stage, env_base, fog=None, cloud=None, moon=None, stars=None):
    merge = _get_or_create_node(stage, "merge", "env_merge")
    inputs = [env_base]
    if fog: inputs.append(fog)
    if cloud: inputs.append(cloud)
    if moon: inputs.append(moon)
    if stars: inputs.append(stars)
    for i in range(len(merge.inputs())): merge.setInput(i, None)
    for i, node in enumerate(inputs): merge.setInput(i, node)
    return merge
