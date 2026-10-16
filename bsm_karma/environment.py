# environment.py - BSM Karma Builder - camera, lights, sky, fog and clouds
# Version : 1.0.0 | Revision : 15-10-2026 | Auteur : BSM

import hou
import math
import os
from .clouds2d import CLOUD_TEXTURE_SIZE, cloud_texture_path
from .config import ATMOSPHERE_FAR_CLIP, CAMERA_CREATE_LABEL, CLOUD2D_BRIGHTNESS, CLOUD_LAYER_NAME, DEFAULT_CLOUD_MATERIAL_PATH, GENERATED_CAMERA_NAME, QUICK_CLOUD_NAME, USD_CAMERA_PREFIX
from .nodeutil import _get_or_create_node, _is_tool_node_candidate, _mark_tool_node, _pset, _remove_tool_node, _safe_connect, _set_first_existing_parm, _set_first_existing_parm_tuple, _set_light_color, _set_usd_input
from .util import _apply_saturation, _apply_tint, _kelvin_to_rgb

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


def _create_physical_sky(stage, prev, cfg, log_callback):
    try:
        sky = _get_or_create_node(stage, "karmaphysicalsky", "physical_sky")
        
        if "sky_mode" in cfg:
            _pset(sky, "skymode", int(cfg["sky_mode"]), log_callback, quiet=True)
            
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

        # H22 has scale parms, the sliders multiply their defaults
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

        if cfg.get("sky_mode", 0) == 1:
            # the atmosphere is lit by the sun alone: below the horizon there is no daylight to scatter
            if float(cfg["sky_elev"]) < 0.0:
                log_callback("[WARN] Volumetric Atmosphere with the sun at {:.1f} deg (below the horizon) is dark, that is night. "
                             "Raise Solar Altitude above 0, or pick a daytime preset. It only renders in Karma.".format(
                                 float(cfg["sky_elev"])))
            log_callback("[INFO] Volumetric Atmosphere renders in Karma CPU and XPU. If it stays black: the sun above the horizon, the far "
                         "clipping range of the camera (raised for the camera the tool makes), then a render in CPU to tell the engines apart.")
            linker = _get_or_create_node(stage, "lightlinker", "sky_atmosphere_linker")
            _pset(linker, "num_links", 1, log_callback, quiet=True)

            # Fix erreur = lightlinker recevait des chemins de node, il veut des chemins de prim USD: <primpath du sky>/<nom du sun>
            sky_root = sky.parm("primpath").evalAsString().rstrip("/") if sky.parm("primpath") else "/lights/physical_sky"
            sun_name = sky.parm("sunprim").evalAsString() if sky.parm("sunprim") else "sun"
            atmo_name = sky.parm("atmoprim").evalAsString() if sky.parm("atmoprim") else "atmosphere"

            _pset(linker, "link_type_1", "light", log_callback, quiet=True)
            _pset(linker, "link_prim_1", "{}/{}".format(sky_root, sun_name), log_callback, quiet=True)
            _pset(linker, "link_includes_1", "{}/{}".format(sky_root, atmo_name), log_callback, quiet=True)
            _safe_connect(linker, sky)
            return linker
            
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
    _pset(fog_geo, "noisescale", float(cfg.get("fog_noise_scale", 0.1)), log_callback, quiet=True)

    _safe_connect(fog_geo, prev)
    return fog_geo


# ------------------------------------------------------------
# SideFX's Quick Cloud Material (an Edit Material Properties LOP). Returns the node, or None.
def _create_quick_cloud_material(stage, prev, cfg, log_callback):
    try:
        from husd import quickmaterials
    except ImportError:
        log_callback("[WARN] husd.quickmaterials is not available in this Houdini: no Quick Cloud Material.")
        return None

    node = stage.node(QUICK_CLOUD_NAME)
    if node is not None and not _is_tool_node_candidate(node):
        log_callback("[WARN] {} was not created by BSM Karma Builder: left untouched, no Quick Cloud Material.".format(node.path()))
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
# 2D clouds: a procedural cloud picture on a second dome light, added to the sky. No geometry, no volume: it renders
# like any dome. A live update uses a smaller picture, the next Build writes the full one. The brightness slider is
# relative to the sky (1 = as bright as the sky), so the clouds stay visible whatever the sky intensity is.
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
    dome = _create_dome_light(stage, prev, intensity, path, log_callback, name=CLOUD_LAYER_NAME)
    # the picture turns around the sky: the rotation of the dome follows the time
    drift = float(cfg.get("cloud2d_drift", 0.0))
    if dome.parm("ry") is not None:
        _animate_parm(dome.parm("ry"), drift / 60.0, log_callback)
    elif drift > 0.0:
        log_callback("[WARN] 2D clouds: the dome light has no rotation parameter, the drift was not set.")
    log_callback("[INFO] 2D clouds: dome light {} at intensity {:.2f} ({} x the {} {:.2f}), picture {}".format(
        dome.name(), intensity, "{:.2f}".format(float(cfg.get("cloud2d_brightness", CLOUD2D_BRIGHTNESS))),
        "sky intensity" if cfg.get("env_type", "Physical Sky") == "Physical Sky" else "HDRI intensity", reference, os.path.basename(path)))
    return dome


# ------------------------------------------------------------
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
            cloud_mat_path = quick.parm("primpath").evalAsString()
    else:
        _remove_tool_node(stage, QUICK_CLOUD_NAME, log_callback, "a custom cloud material is used")
    if not cloud_mat_path or cloud_mat_path == DEFAULT_CLOUD_MATERIAL_PATH:
        log_callback("[WARN] No cloud material available: clouds will render with the default volume.")

    _pset(assign, "matspecpath1", cloud_mat_path, log_callback, quiet=True)
    _safe_connect(assign, upstream)
    return assign


# ------------------------------------------------------------
def _create_environment_merge(stage, env_base, fog=None, cloud=None):
    merge = _get_or_create_node(stage, "merge", "env_merge")
    inputs = [env_base]
    if fog: inputs.append(fog)
    if cloud: inputs.append(cloud)
    for i in range(len(merge.inputs())): merge.setInput(i, None)
    for i, node in enumerate(inputs): merge.setInput(i, node)
    return merge
