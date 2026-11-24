# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Runs the build: cleanup of the old tool nodes, geometry merge, and setup_karma_environment that assembles the Karma network.

# Houdini : 21 and 22

import hou
from .config import TOOL_STAGE_DELETE_ORDER
from .debuglog import _debug, _debug_exception, _debug_state
from .environment import _lamp_color, _create_area_light, _create_cloud_branch, _create_cloud_layer_2d, _create_dome_light, _create_moon, _create_night_sky, _night_fade, _create_environment_merge, _create_fog_branch, _create_physical_sky, _ensure_atmosphere_clip, _resolve_render_camera
from .ephemeris import apply_exact_sky
from .skycomp import prepare_config
from .moon import moon_state
from .linker import _material_edit_node, _material_linker_node
from .nodeutil import (ignored_report, ignored_reset, _get_or_create_node, _get_or_create_stage, _is_tool_node_candidate, _layout_tool_nodes, _paused_cooking,
                       _remove_tool_node, _safe_connect)
from .rendering import _create_aov_chain, _create_material_library, _create_render_rop, _create_render_settings

# ----------------------------------------------------------
def _atmosphere_sky(cfg):
    return cfg.get("env_type", "Physical Sky") == "Physical Sky" and cfg.get("sky_mode", 0) == 1

#--------------------------------------------------------
def _cleanup_environment_nodes(stage, cfg, log_callback):
    all_env_nodes = {
        "physical_sky", "sky_sun", "sky_atmosphere", "sky_atmosphere_linker", "env_hdri", "atmosphere_fog", "fog_xform", "assign_fog_shader",
        "cloud_geo", "cloud_xform", "quickcloudmaterial", "assign_cloud_shader", "cloud_volume", "cloud_layer_2d", "cloud_layer_2d_ref", "cloud_layer_2d_mat", "sky_moon", "sky_moon_disc", "sky_moon_halo", "sky_moon_ref", "sky_moon_mat", "sky_milky", "sky_stars_ref", "sky_stars_mtl", "sky_stars_mat", "env_merge",
        "studio_hdri", "studio_key", "fill_hdri", "key_light", "fill_light", "rim_light", "window_portal",
    }

    mode = cfg.get("scene_mode", "Environment")
    env_type = cfg.get("env_type", "Physical Sky")
    keep = set()

    if mode == "Environment":
        if env_type == "Physical Sky":
            keep.update({"sky_sun", "sky_atmosphere"} if cfg.get("sky_mode", 0) == 1 else {"physical_sky"})
        else:
            keep.add("env_hdri")
        keep.add("env_merge")
        if cfg.get("enable_fog"):
            keep.add("atmosphere_fog")
        if moon_state(cfg)["active"] and not cfg.get("sky_plate"):
            keep.update({"sky_moon", "sky_moon_disc", "sky_moon_halo", "sky_moon_ref", "sky_moon_mat"})
        if cfg.get("stars_enable") and _night_fade(cfg) > 0.0 and not cfg.get("sky_plate"):
            keep.update({"sky_stars_ref", "sky_stars_mtl", "sky_stars_mat"})
            if cfg.get("stars_milky", True):
                keep.add("sky_milky")
        if cfg.get("enable_clouds"):
            if int(cfg.get("cloud_type", 0)) == 1:
                if not _atmosphere_sky(cfg) and not cfg.get("sky_plate"):
                    keep.update({"cloud_layer_2d", "cloud_layer_2d_ref", "cloud_layer_2d_mat"})
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

        fog = cloud = moon = stars = None
        if cfg["enable_fog"]:
            try:
                fog = _create_fog_branch(stage, cam, cfg, log_callback)
            except hou.Error as exc:
                log_callback("[WARN] Fog skipped: {}".format(exc))
                skipped.append("fog")
        if cfg["enable_clouds"] and int(cfg.get("cloud_type", 0)) == 1 and cfg.get("sky_plate"):
            pass   # the 2D clouds are a layer of the composite, nothing is built in the scene
        elif cfg["enable_clouds"] and int(cfg.get("cloud_type", 0)) == 1 and _atmosphere_sky(cfg):
            # bug trouvé: l'atmosphère cache une image de dôme et le dôme l'éclaire (voile blanc, aucun nuage visible)
            log_callback("[WARN] 2D clouds are not drawn with the Volumetric Atmosphere (it hides a dome picture): use the 3D Volume clouds, or the Basic Projection sky.")
            skipped.append("clouds")
        elif cfg["enable_clouds"] and int(cfg.get("cloud_type", 0)) == 1:
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
        if moon_state(cfg)["active"] and not cfg.get("sky_plate"):
            try:
                moon = _create_moon(stage, cam, cfg, log_callback)
            except (hou.Error, OSError, ValueError) as exc:
                log_callback("[WARN] Moon skipped: {}".format(exc))
                skipped.append("moon")
        if cfg.get("stars_enable") and _night_fade(cfg) > 0.0 and not cfg.get("sky_plate"):
            try:
                stars = _create_night_sky(stage, cam, cfg, log_callback)
            except (hou.Error, OSError, ValueError, KeyError) as exc:
                log_callback("[WARN] Night sky skipped: {}".format(exc))
                skipped.append("stars")
        return _create_environment_merge(stage, env_base, fog, cloud, moon, stars)

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
    # the exact sky (a date, a time, a place) takes the sun's place and the sidereal time from the ephemeris
    cfg = apply_exact_sky(cfg)
    # a sky made in the composite needs the depth in the render
    cfg = prepare_config(cfg)
    log_callback(f"--- Building: {cfg['scene_mode']} (Houdini {hou.applicationVersionString()}) ---")
    live = bool(cfg.get("live"))
    ignored_reset()
    try:
        if hou.applicationVersion()[0] < 21:
            log_callback("[WARN] Written for Houdini 21 and 22: some Karma parameters may be missing in this version.")
        elif hou.applicationVersion()[0] == 21:
            log_callback("[INFO] Houdini 21 has not been tested with this version: read the [WARN] lines, a setting that is not applied is named there.")
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
            _show_render_chain(stage, ks)
            if not live:
                ks.setSelected(True, True)

    ignored_report(log_callback, live)
    if skipped:
        log_callback("[WARN] Built, but these steps were skipped: {}.".format(", ".join(skipped)))
    else:
        env = "" if cfg.get("scene_mode", "Environment") in ("Studio", "3 Points") else " | Env: {}".format(cfg.get("env_type", "Physical Sky"))
        log_callback(f"[OK] Karma Ready. Engine: {cfg['engine'].upper()}{env}")

# ------------------------------------------------------------
# bug trouvé et fixé: every build, and every move of a slider in Live Update, put the display flag back on Karma Render Settings.
# A node made after it (a sphere created in the viewport is wired to the displayed node) was no longer displayed: the geometry
# "disappeared". The flag only goes to the end of the chain when nothing at or after it is displayed already.
def _show_render_chain(stage, tip):
    def downstream(node):
        seen, todo = set(), [node]
        while todo:
            current = todo.pop()
            if current.path() in seen:
                continue
            seen.add(current.path())
            todo.extend(current.outputs())
        return seen

    after = downstream(tip)
    # the ROPs of the network have no display flag
    displayed = []
    for node in stage.children():
        try:
            if node.isDisplayFlagSet():
                displayed.append(node)
        except (AttributeError, hou.Error):
            pass
    if not any(n.path() in after for n in displayed):
        tip.setDisplayFlag(True)

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
