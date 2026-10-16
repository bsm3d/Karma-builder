# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Material library, AOVs, Karma settings and the render ROP
# Houdini : 21 and 22
# Version : 1.0.0

import hou
import re
from .nodeutil import _get_or_create_node, _mark_tool_node, _menu_has_value, _pset, _safe_connect, _set_first_existing_parm, _set_menu_token
from .util import _normalize_output_path_extension

# --------------------------------------------------------
def _create_material_library(stage, prev, cfg, log_callback):
    mat_lib = _get_or_create_node(stage, "materiallibrary", "mtlx_materials")
    _safe_connect(mat_lib, prev)

    _set_first_existing_parm(
        mat_lib,
        ("matpathprefix", "materialpathprefix", "pathprefix"),
        "/World/Materials",
        log_callback,
    )

    def _ensure_shader_material(subnet_name, shader_name, shader_types, output_kind="surface"):
        subnet = mat_lib.node(subnet_name)
        if subnet is None:
            subnet = mat_lib.createNode("subnet", subnet_name)
            _mark_tool_node(subnet)

        shader = subnet.node(shader_name)
        if shader is None:
            for shader_type in shader_types:
                try:
                    shader = subnet.createNode(shader_type, shader_name)
                    _mark_tool_node(shader)
                    break
                except hou.Error:
                    shader = None

        if shader is None:
            # Last resort keeps build from failing if a shader node is unavailable.
            try:
                shader = subnet.createNode("mtlxstandard_surface", shader_name)
                _mark_tool_node(shader)
            except hou.Error:
                shader = None

        out = subnet.node("surface_out")
        if out is None:
            for out_name in ("OUT", "output", "suboutput1"):
                out = subnet.node(out_name)
                if out is not None:
                    break

        if out is None:
            for out_type in ("suboutput", "suboutput1", "subnetconnector", "output"):
                try:
                    out = subnet.createNode(out_type, "surface_out")
                    _mark_tool_node(out)
                    break
                except hou.Error:
                    out = None

        if out is not None:
            try:
                kind_values = [output_kind]
                if output_kind == "surface":
                    kind_values.extend(["surface", "output", 0])
                elif output_kind == "volume":
                    kind_values.extend(["volume", "output", 1])

                for kind_val in kind_values:
                    if _set_first_existing_parm(
                        out,
                        ("connectorkind", "kind", "parmtype", "signature"),
                        kind_val,
                        log_callback,
                    ):
                        break
            except (hou.Error, TypeError):
                pass

            try:
                if shader is not None:
                    out.setInput(0, shader)
            except hou.Error:
                pass

        try:
            subnet.layoutChildren()
        except hou.Error:
            pass

        return shader

    is_new_pbr = mat_lib.node("pbr_standard") is None or mat_lib.node("pbr_standard").node("pbr_surface") is None
    pbr_surf = _ensure_shader_material(
        "pbr_standard",
        "pbr_surface",
        ("mtlxstandard_surface",),
        "surface",
    )
    if pbr_surf is not None and is_new_pbr:
        _pset(pbr_surf, "base", 1.0, log_callback)
        _pset(pbr_surf, "base_colorr", 0.8, log_callback)
        _pset(pbr_surf, "base_colorg", 0.8, log_callback)
        _pset(pbr_surf, "base_colorb", 0.8, log_callback)
        _pset(pbr_surf, "specular", 1.0, log_callback)
        _pset(pbr_surf, "specular_roughness", 0.4, log_callback)
        _pset(pbr_surf, "specular_IOR", 1.5, log_callback)

    try:
        mat_lib.layoutChildren()
    except hou.Error:
        pass

    return mat_lib


# ------------------------------------------------------------
def _apply_aov_precision(aovs, beauty_half, other_half, log_callback):
    pattern = re.compile(r"^(color[34])([hf])$")
    changed = 0
    for parm in aovs.parms():
        name = parm.name()
        if not name.endswith("precision"):
            continue
        match = pattern.match(parm.evalAsString())
        if not match:
            continue
        half = beauty_half if name == "beautyprecision" else other_half
        wanted = match.group(1) + ("h" if half else "f")
        if wanted != parm.evalAsString() and _menu_has_value(parm, wanted):
            if _pset(aovs, name, wanted, log_callback, quiet=True):
                changed += 1
    return changed


# ------------------------------------------------------------
# Fix erreur = aucun des anciens noms de toggles n'existait sur H22, les AOV étaient ignorés en silence
def _create_aov_chain(stage, prev, cfg, log_callback):
    aovs = _get_or_create_node(stage, "karmastandardrendervars", "standard_aovs")
    _safe_connect(aovs, prev)

    aov_flag_map = {
        "aov_ao": (("ambientocclusion",), ("format_ao", "format_ambientocclusion", "aov_ao")),
        "aov_depth": (("hitPz",), ("format_depth", "format_z", "format_pz", "aov_depth")),
        "aov_normal": (("hitN",), ("format_normal", "format_n", "aov_normal")),
        "aov_position": (("hitP",), ("format_position", "format_p", "aov_position")),
        "aov_albedo": (("albedo",), ("format_albedo", "format_basecolor", "format_base_color", "aov_albedo")),
        "aov_emission": (("combinedemission",), ("format_emission", "format_emit", "aov_emission")),
        "aov_diffuse": (("combineddiffuse",), ("format_diffuse", "format_diff", "aov_diffuse")),
        "aov_specular": (("combinedglossyreflection",), ("format_specular", "format_spec", "aov_specular")),
        "aov_motion": (("motionvectors",), ("format_motionvector", "format_motion", "format_mv", "aov_motion")),
        "aov_shadow": (("shadow",), ("format_shadow", "format_shadowmask", "aov_shadow")),
        "aov_id": (("primid", "element"), ("format_id", "format_objectid", "format_cryptomatte", "aov_id")),
    }

    for cfg_key, (names, legacy_names) in aov_flag_map.items():
        if cfg_key == "aov_ao":
            enabled = bool(cfg.get("aov_ao", cfg.get("enable_ao", False)))
        else:
            enabled = bool(cfg.get(cfg_key, False))
        value = 1 if enabled else 0
        applied = False
        for name in names:
            if aovs.parm(name) is not None:
                applied = _pset(aovs, name, value, log_callback, quiet=True) or applied
        if not applied:
            _set_first_existing_parm(aovs, legacy_names, value, log_callback)

    # Beauty follows the EXR precision of the Export tab; the other passes follow the AOV option.
    beauty_half = (cfg.get("exr_precision", "16-bit float") == "16-bit float")
    other_half = bool(cfg.get("aov_half_precision", False))
    if not _apply_aov_precision(aovs, beauty_half, other_half, log_callback):
        _set_first_existing_parm(
            aovs,
            ("halfprecision", "half", "half_float", "halfFloat"),
            1 if other_half else 0,
            log_callback,
        )

    return aovs


# ------------------------------------------------------------
def _create_render_settings(stage, cam_path, prev, cfg, log_callback):
    ks = _get_or_create_node(stage, "karmarendersettings", "karma_settings")
    engine = cfg["engine"]
    _pset(ks, "engine", engine, log_callback, quiet=True)
    _pset(ks, "camera", cam_path, log_callback)

    # CPU uses path traced samples too (see convergence_mode below)
    if ks.parm("pathtracedsamples") is not None:
        _pset(ks, "pathtracedsamples", cfg["samples"], log_callback)
        if engine == "cpu":
            _set_menu_token(ks, ("convergence_mode",), "Path Traced", log_callback, label="Convergence")
    elif engine == "xpu":
        _set_first_existing_parm(ks, ("pathtracesamples",), cfg["samples"], log_callback)
    else:
        _set_first_existing_parm(ks, ("primarysamples", "samplesperpixel"), cfg["samples"], log_callback)

    if not _set_menu_token(ks, ("res_mode",), "manual", log_callback, label="Resolution mode"):
        _pset(ks, "resolutionmode", "manual", log_callback, quiet=True)
        _pset(ks, "resMenu", "specific", log_callback, quiet=True)
    res_parm = ks.parmTuple("resolution")
    if res_parm is not None:
        for p in res_parm:
            if p.isLocked(): p.lock(False)
            p.deleteAllKeyframes()
        try: res_parm.set((cfg["res_x"], cfg["res_y"]))
        except hou.Error: pass

    denoise_tokens = {"None": "off", "Optix (GPU)": "optix", "OIDN (CPU)": "oidn"}
    denoiser = ks.parm("denoiser")
    if denoiser is not None:
        token = denoise_tokens.get(cfg["denoiser"], "off")
        if not _menu_has_value(denoiser, token):
            token = {"off": "0", "optix": "1", "oidn": "2"}[token]
        _pset(ks, "denoiser", token, log_callback, quiet=True)

    pixel_filter = str(cfg["pixel_filter"])
    pf_parm = ks.parm("pixelfilter")
    if pf_parm is not None:
        if _menu_has_value(pf_parm, pixel_filter):
            _pset(ks, "pixelfilter", pixel_filter, log_callback, quiet=True)
        else:
            try:
                has_menu = bool(pf_parm.menuItems())
            except hou.OperationFailed:
                has_menu = False
            if has_menu:
                log_callback("[WARN] Pixel filter '{}' not available in this Houdini, keeping '{}'.".format(
                    pixel_filter, pf_parm.evalAsString()))
            else:
                _pset(ks, "pixelfilter", '["{}", {{}}]'.format(pixel_filter), log_callback, quiet=True)

    _set_first_existing_parm(ks, ("diffuselimit", "diffuse_limit"), float(cfg["diffuse_limit"]), log_callback)
    _set_first_existing_parm(ks, ("reflectionlimit", "reflectlimit", "specularlimit"), float(cfg["reflection_limit"]), log_callback)
    _set_first_existing_parm(
        ks,
        ("refractionlimit", "transmissionlimit", "transmitlimit", "refractlimit"),
        float(cfg["transmission_limit"]),
        log_callback,
    )
    _set_first_existing_parm(ks, ("colorlimit", "indirectlimit"), float(cfg.get("color_limit", 10.0)), log_callback)

    noise_lvl = float(cfg.get("noise_level", 0.01))
    _set_first_existing_parm(ks, ("varianceaa_thresh", "oracle_variance", "adaptivethreshold", "noiselevel", "variancethreshold"), noise_lvl, log_callback)

    vol_limit = int(cfg.get("volume_limit", 8))
    if cfg.get("enable_clouds") and int(cfg.get("cloud_type", 0)) == 0 and cfg.get("enable_fog") and vol_limit < 8:
        vol_limit = max(vol_limit, 8)
    _set_first_existing_parm(ks, ("volumelimit", "volume_limit", "volumeraylimit"), float(vol_limit), log_callback)

    out_path = _normalize_output_path_extension(cfg["out_path"], cfg["output_format"])
    _set_first_existing_parm(ks, ("picture",), out_path, log_callback)
    if cfg.get("enable_aovs", False):
        _set_first_existing_parm(ks, ("splitrendervars",), 0 if cfg.get("aov_multilayer", True) else 1, log_callback)

    _safe_connect(ks, prev)
    return ks


# ------------------------------------------------------------------------
def _create_render_rop(stage, lop_input, cfg, log_callback):
    rp = _get_or_create_node(stage, "usdrender_rop", "render_to_disk")
    out_path = _normalize_output_path_extension(cfg["out_path"], cfg["output_format"])

    _pset(rp, "loppath", lop_input.path(), log_callback)
    _pset(rp, "outputimage", out_path, log_callback)
    _pset(rp, "trange", cfg["trange"], log_callback)
    _pset(rp, "f1", float(cfg["f_start"]), log_callback)
    _pset(rp, "f2", float(cfg["f_end"]), log_callback)

    delegate = "BRAY_HdKarmaXPU" if cfg["engine"] == "xpu" else "BRAY_HdKarma"
    renderer = rp.parm("renderer")
    if renderer is not None and _menu_has_value(renderer, delegate):
        _pset(rp, "renderer", delegate, log_callback, quiet=True)
    ks_node = stage.node("karma_settings")
    if ks_node is not None and ks_node.parm("primpath") is not None:
        _pset(rp, "rendersettings", ks_node.parm("primpath").evalAsString(), log_callback, quiet=True)

    _set_first_existing_parm(rp, ("pictureformat", "outputformat", "imageformat"), str(cfg["output_format"]).lower(), log_callback)
    if str(cfg["output_format"]).upper() == "EXR":
        exr_is_half = (cfg.get("exr_precision", "16-bit float") == "16-bit float")
        _set_first_existing_parm(rp, ("halfprecision", "half", "exrhalf"), 1 if exr_is_half else 0, log_callback)
        _set_first_existing_parm(
            rp,
            ("exrdatatype", "exr_pixeltype", "exrprecision", "datatype"),
            "half" if exr_is_half else "float",
            log_callback,
        )

    _safe_connect(rp, lop_input)
    return rp
