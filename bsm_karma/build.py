# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : The build: cleanup, geometry merge and setup_karma_environment
# Houdini : 21 and 22
# Version : 1.0.0

import hou
from .config import TOOL_STAGE_DELETE_ORDER
from .debuglog import _debug, _debug_exception, _debug_state
from .environment import _lamp_color, _create_area_light, _create_cloud_branch, _create_cloud_layer_2d, _create_dome_light, _create_environment_merge, _create_fog_branch, _create_physical_sky, _ensure_atmosphere_clip, _resolve_render_camera
from .linker import _material_edit_node, _material_linker_node
from .nodeutil import (_get_or_create_node, _get_or_create_stage, _is_tool_node_candidate, _layout_tool_nodes, _paused_cooking,
                       _remove_tool_node, _safe_connect)
from .rendering import _create_aov_chain, _create_material_library, _create_render_rop, _create_render_settings

#--------------------------------------------------------
def _cleanup_environment_nodes(stage, cfg, log_callback):
    all_env_nodes = {
        "physical_sky", "sky_atmosphere_linker", "env_hdri", "atmosphere_fog", "fog_xform", "assign_fog_shader",
        "cloud_geo", "cloud_xform", "quickcloudmaterial", "assign_cloud_shader", "cloud_volume", "cloud_layer_2d", "env_merge",
        "studio_hdri", "studio_key", "fill_hdri", "key_light", "fill_light", "rim_light", "window_portal",
    }

    mode = cfg.get("scene_mode", "Environment")
    env_type = cfg.get("env_type", "Physical Sky")
    keep = set()

    if mode == "Environment":
        if env_type == "Physical Sky":
            keep.add("physical_sky")
            if cfg.get("sky_mode", 0) == 1:
                keep.add("sky_atmosphere_linker")
        else:
            keep.add("env_hdri")
        keep.add("env_merge")
        if cfg.get("enable_fog"):
            keep.add("atmosphere_fog")
        if cfg.get("enable_clouds"):
            if int(cfg.get("cloud_type", 0)) == 1:
                keep.add("cloud_layer_2d")
            else:
                keep.update({"cloud_geo", "cloud_xform", "quickcloudmaterial", "assign_cloud_shader"})
    elif mode == "Studio":
        keep.update({"studio_hdri", "studio_key"})
    elif mode == "3 Points":
        keep.update({"fill_hdri", "key_light", "fill_light", "rim_light"})
    elif mode == "Interior":
        # no sky: the window light, and an HDRI for the view through it
        if env_type == "HDRI Image":
            keep.add("env_hdri")
        keep.add("window_portal")

    removed = 0
    # delete in the listed order so Houdini does not warn about stranded connections
    candidates_to_remove = []
    
    for node_name in TOOL_STAGE_DELETE_ORDER:
        if node_name in all_env_nodes and node_name not in keep:
            candidates_to_remove.append(node_name)
            
    for node_name in all_env_nodes:
        if node_name not in keep and node_name not in candidates_to_remove:
            candidates_to_remove.append(node_name)

    for node_name in candidates_to_remove:
        node = stage.node(node_name)
        if node is None or not _is_tool_node_candidate(node, node_name):
            continue
        try:
            node.destroy()
            removed += 1
        except hou.OperationFailed:
            log_callback(f"[WARN] Could not remove previous node: {node_name}")

    if removed:
        log_callback(f"[INFO] Cleanup: removed {removed} obsolete environment node(s).")


# --------------------------------------------------------------------------------
# A node the build no longer needs: removed now, or, when a list is given, at the end of the build (see below).
def _drop_node(stage, name, log_callback, reason, removals):
    if removals is None:
        _remove_tool_node(stage, name, log_callback, reason)
    else:
        removals.append((name, reason))


# --------------------------------------------------------------------------------
def _merge_geometry_source(stage, env_tip, cfg, log_callback, removals=None):
    geo_path = (cfg.get("geo_source") or "").strip()
    geo_node = hou.node(geo_path) if geo_path else None

    usable = (
        geo_node is not None
        and geo_node.type().category() == hou.lopNodeTypeCategory()
        and geo_node.parent() == stage
        and not _is_tool_node_candidate(geo_node, geo_node.name())
    )
    if not usable:
        if geo_path:
            log_callback("[WARN] Geometry source not usable: {}".format(geo_path))
        _drop_node(stage, "geo_merge", log_callback, "", removals)
        return env_tip

    merge = _get_or_create_node(stage, "merge", "geo_merge")
    try:
        for i in range(len(merge.inputs())):
            merge.setInput(i, None)
        merge.setInput(0, env_tip)
        merge.setInput(1, geo_node)
    except hou.OperationFailed as exc:
        log_callback("[WARN] Could not merge geometry source {}: {}".format(geo_path, exc))
        return env_tip
    return merge


# --------------------------------------------------------------------------------
def _build_lighting(stage, cam, cfg, log_callback, skipped):
    mode = cfg.get("scene_mode", "Environment")
    env_type = cfg.get("env_type", "Physical Sky")

    if mode == "Environment":
        if env_type == "Physical Sky":
            env_base = _create_physical_sky(stage, cam, cfg, log_callback)
        else:
            env_base = _create_dome_light(stage, cam, cfg["hdri_int"], cfg["hdri_path"], log_callback, name="env_hdri", hdri_opts=cfg)

        fog = cloud = None
        if cfg["enable_fog"]:
            try:
                fog = _create_fog_branch(stage, cam, cfg, log_callback)
            except hou.Error as exc:
                log_callback("[WARN] Fog skipped: {}".format(exc))
                skipped.append("fog")
        if cfg["enable_clouds"] and int(cfg.get("cloud_type", 0)) == 1:
            try:
                cloud = _create_cloud_layer_2d(stage, cam, cfg, log_callback)
            except (hou.Error, OSError, ImportError, ValueError) as exc:
                log_callback("[WARN] 2D clouds skipped: {}".format(exc))
                skipped.append("clouds")
        elif cfg["enable_clouds"]:
            try:
                cloud = _create_cloud_branch(stage, cam, cfg, log_callback)
            except hou.Error as exc:
                log_callback("[WARN] Clouds skipped (a node type may be missing in this Houdini): {}".format(exc))
                skipped.append("clouds")
        return _create_environment_merge(stage, env_base, fog, cloud)

    if mode == "Studio":
        dome = _create_dome_light(stage, cam, cfg["hdri_int"], cfg["hdri_path"], log_callback, name="studio_hdri", hdri_opts=cfg)
        return _create_area_light(stage, dome, cfg["area_int"], log_callback, name="studio_key", pos=(3, 4, 3), rot=(-45, 30, 0),
                                  color=_lamp_color(cfg, "key"))

    if mode == "3 Points":
        dome = _create_dome_light(stage, cam, float(cfg["hdri_int"])*0.2, cfg["hdri_path"], log_callback, name="fill_hdri", hdri_opts=cfg)
        key = _create_area_light(stage, dome, float(cfg["area_int"]), log_callback, name="key_light", pos=(3, 4, 3), rot=(-45, 30, 0),
                                 color=_lamp_color(cfg, "key"))
        fill = _create_area_light(stage, key, float(cfg["area_int"])*0.4, log_callback, name="fill_light", pos=(-4, 2, 2), rot=(-20, -45, 0),
                                  color=_lamp_color(cfg, "fill"))
        return _create_area_light(stage, fill, float(cfg["area_int"])*1.5, log_callback, name="rim_light", pos=(-2, 3, -4), rot=(-30, -150, 0),
                                  color=_lamp_color(cfg, "rim"))

    if mode == "Interior":
        env_base = cam
        if env_type == "HDRI Image":
            env_base = _create_dome_light(stage, cam, cfg["hdri_int"], cfg["hdri_path"], log_callback, name="env_hdri", hdri_opts=cfg)
        return _create_area_light(stage, env_base, float(cfg["area_int"]), log_callback, name="window_portal", pos=(5, 2, 0), rot=(0, 90, 0),
                                  color=_lamp_color(cfg, "key"))

    return cam


# --------------------------------------------------------------------------------
def _build_render_chain(stage, env_tip, cam_path, cfg, log_callback, skipped, removals):
    try:
        mat = _create_material_library(stage, env_tip, cfg, log_callback)
    except hou.Error as exc:
        log_callback("[WARN] Material library skipped: {}".format(exc))
        skipped.append("material library")
        mat = env_tip

    linker = _material_linker_node(stage)
    if linker is not None:
        _safe_connect(linker, mat)
        mat = linker
        edit = _material_edit_node(stage)
        if edit is not None:
            _safe_connect(edit, mat)
            mat = edit

    if cfg["enable_aovs"]:
        try:
            upstream = _create_aov_chain(stage, mat, cfg, log_callback)
        except hou.Error as exc:
            log_callback("[WARN] AOVs skipped: {}".format(exc))
            skipped.append("AOVs")
            upstream = mat
    else:
        _drop_node(stage, "standard_aovs", log_callback, "AOVs disabled", removals)
        upstream = mat
    ks = _create_render_settings(stage, cam_path, upstream, cfg, log_callback)
    try:
        _create_render_rop(stage, ks, cfg, log_callback)
    except hou.Error as exc:
        log_callback("[WARN] Render ROP skipped: {}".format(exc))
        skipped.append("render ROP")
    return ks


# --------------------------------------------------------------------------------
# Order matters for a running Karma viewport: the new network is built and wired first, the obsolete nodes are removed
# last, when nothing displayed depends on them any more, and cooking is paused for the whole build.
def setup_karma_environment(cfg, log_callback):
    log_callback(f"--- Building: {cfg['scene_mode']} (Houdini {hou.applicationVersionString()}) ---")
    live = bool(cfg.get("live"))
    try:
        if hou.applicationVersion()[0] < 21:
            log_callback("[WARN] Written for Houdini 21 and 22: some Karma parameters may be missing in this version.")
    except (hou.Error, TypeError, IndexError):
        pass
    skipped = []
    removals = []
    with _paused_cooking(log_callback):
        stage = _get_or_create_stage()
        child_count = len(stage.children())
        cam, cam_path = _resolve_render_camera(stage, cfg, log_callback)
        if cfg.get("scene_mode", "Environment") == "Environment" and cfg.get("env_type", "Physical Sky") == "Physical Sky" \
                and cfg.get("sky_mode", 0) == 1:
            _ensure_atmosphere_clip(cam, cam_path, log_callback)

        env_tip = _build_lighting(stage, cam, cfg, log_callback, skipped)
        env_tip = _merge_geometry_source(stage, env_tip, cfg, log_callback, removals)
        ks = _build_render_chain(stage, env_tip, cam_path, cfg, log_callback, skipped, removals)
        for name, reason in removals:
            _remove_tool_node(stage, name, log_callback, reason)
        _cleanup_environment_nodes(stage, cfg, log_callback)

        # a live update only re-places the nodes when it created or removed some, and never takes the selection
        if not live or len(stage.children()) != child_count:
            _layout_tool_nodes(stage)
        _debug_stage_dump(stage)

        if ks:
            ks.setDisplayFlag(True)
            if not live:
                ks.setSelected(True, True)

    if skipped:
        log_callback("[WARN] Built, but these steps were skipped: {}.".format(", ".join(skipped)))
    else:
        env = "" if cfg.get("scene_mode", "Environment") in ("Studio", "3 Points") else " | Env: {}".format(cfg.get("env_type", "Physical Sky"))
        log_callback(f"[OK] Karma Ready. Engine: {cfg['engine'].upper()}{env}")


# ------------------------------------------------------------
def _debug_stage_dump(stage):
    if not _debug_state["enabled"] or stage is None:
        return
    try:
        lines = []
        for node in sorted(stage.children(), key=lambda n: n.name()):
            sources = ", ".join(n.name() if n is not None else "-" for n in node.inputs()) or "-"
            tagged = "tool" if _is_tool_node_candidate(node, node.name()) else "user"
            lines.append("  {:<26} {:<34} <- {:<34} [{}]".format(
                node.name(), node.type().nameWithCategory(), sources, tagged))
        _debug("/stage after the build:\n" + "\n".join(lines))
    except Exception:   # a debug dump must never break a build
        _debug_exception("_debug_stage_dump")
