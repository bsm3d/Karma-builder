# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Composes the sky plate under the picture after the render, in a Copernicus network (Houdini 22 only).

# Houdini : 22

import os
import hou
from .clouds2d import write_exr_grey
from .config import TOOL_NODE_TAG_KEY, TOOL_NODE_TAG_VALUE
from .debuglog import _debug
from .skyplate import camera_of_stage, compose, render_sky_plate

COMP_NET_NAME = "karma_sky_comp"

# ------------------------------------------------------------
# Does this build ask for a sky made in the composite (stars, planets, Milky Way, moon), and is there anything of it to show?
def wants_plate(cfg):
    from .ephemeris import apply_exact_sky
    from .environment import _night_fade
    from .moon import moon_state
    if not cfg.get("sky_plate") or cfg.get("scene_mode", "Environment") != "Environment":
        return False
    cfg = apply_exact_sky(cfg)
    clouds = bool(cfg.get("enable_clouds")) and int(cfg.get("cloud_type", 0)) == 1
    return bool((cfg.get("stars_enable") and _night_fade(cfg) > 0.0) or moon_state(cfg)["active"] or clouds)

# ------------------------------------------------------------
# What the render has to carry for the composite: the beauty and the depth (the sky is where the depth is 0) in an EXR with AOVs.
def prepare_config(cfg):
    if not wants_plate(cfg):
        return cfg
    out = dict(cfg)
    out.update(enable_aovs=True, aov_depth=True, aov_multilayer=True, output_format="EXR")
    return out

# ------------------------------------------------------------
def _read_layers(path):
    import numpy as np
    import OpenImageIO as oiio
    reader = oiio.ImageInput.open(path)
    if reader is None:
        raise OSError("cannot read {}".format(path))
    layers, index = {}, 0
    while reader.seek_subimage(index, 0):
        spec = reader.spec()
        layers[spec.get_string_attribute("oiio:subimagename", "?")] = np.array(reader.read_image("float")).reshape(spec.height, spec.width, spec.nchannels)
        index += 1
    reader.close()
    return layers

# ------------------------------------------------------------
def _frame_path(path, frame):
    return hou.text.expandStringAtFrame(path, frame).replace("\\", "/")

# ------------------------------------------------------------
# bug trouvé et fixé: the range of the output node is $FSTART and $FEND by default and set() leaves such an expression where it is: a frame
# range of the render came out as the range of the timeline. The expression goes first.
def _set_range(out, first, last):
    out.parm("trange").set(1 if last > first else 0)
    for name, value in (("f1", first), ("f2", last)):
        out.parm(name).deleteAllKeyframes()
        out.parm(name).set(value)

# ------------------------------------------------------------
# The blend mode by its name; the position in the menu is only the way out when this version names it differently
def _set_blend_mode(node, token, index):
    parm = node.parm("mode")
    items = parm.menuItems()
    if token in items:
        parm.set(token)
    else:
        parm.set(index)

# ------------------------------------------------------------
# The nodes the tool puts in its network. A network that still has all of them is kept and only its files are updated.
COMP_NODES = ("render", "moon", "stars", "clouds", "moon_over", "stars_add", "clouds_over", "final")

# ------------------------------------------------------------
# The Copernicus network: the render (beauty), the moon over it, the stars and the Milky Way added, written to the final picture. The
# plates are masked to the sky already; open the network to grade, glow or blur them like any layer.
def build_comp_network(beauty, moon, stars, clouds, final, first, last, log=None):
    obj = hou.node("/obj")
    # bug trouvé et fixé: a copnet of the user with this name was destroyed at every render. Only the networks the tool made (tagged) are
    # replaced; next to a foreign one the new network takes the next free name (karma_sky_comp1).
    mine = [old for old in obj.children() if old.name().startswith(COMP_NET_NAME) and old.userData(TOOL_NODE_TAG_KEY) == TOOL_NODE_TAG_VALUE]
    # bug trouvé et fixé: the network was rebuilt at every render, so what the user added in it (a glow, a grade) was lost without a word.
    # A network that still has the tool's nodes is kept: only the file paths and the frame range change.
    net = next((old for old in mine if all(old.node(name) is not None for name in COMP_NODES)), None)
    if net is not None:
        for old in mine:
            if old is not net:
                old.destroy()
        for name, path in (("render", beauty), ("moon", moon), ("stars", stars), ("clouds", clouds)):
            net.node(name).parm("filename").set(path)
        out = net.node("final")
        out.parm("copoutput").set(final)
        _set_range(out, first, last)
        if log:
            log("Sky composite: the network {} is kept (your changes stay), its files are updated.".format(net.path()))
        return net, out
    for old in mine:
        old.destroy()
    net = obj.createNode("copnet", COMP_NET_NAME)
    net.setUserData(TOOL_NODE_TAG_KEY, TOOL_NODE_TAG_VALUE)

    def file_node(name, path, aovs):
        node = net.createNode("file", name)
        node.parm("filename").set(path)
        node.parm("aovs").set(len(aovs))
        for i, (aov, kind) in enumerate(aovs, 1):
            node.parm("aov{}".format(i)).set(aov)
            node.parm("type{}".format(i)).set(kind)
        return node

    render = file_node("render", beauty, [("C", 3)])
    moon_node = file_node("moon", moon, [("C", 3)])
    stars_node = file_node("stars", stars, [("C", 3)])
    clouds_node = file_node("clouds", clouds, [("C", 3)])
    over = net.createNode("blend", "moon_over")
    _set_blend_mode(over, "over", 1)
    over.setInput(0, render)
    over.setInput(1, moon_node)
    add = net.createNode("blend", "stars_add")
    _set_blend_mode(add, "add", 3)
    add.setInput(0, over)
    add.setInput(1, stars_node)
    cover = net.createNode("blend", "clouds_over")
    _set_blend_mode(cover, "over", 1)
    cover.setInput(0, add)
    cover.setInput(1, clouds_node)
    out = net.createNode("rop_image", "final")
    out.setInput(0, cover)
    out.parm("copoutput").set(final)
    _set_range(out, first, last)
    net.layoutChildren()
    return net, out

# ------------------------------------------------------------
# After a render to disk: for each frame the plate is drawn for the render camera and masked by the depth of the picture, written
# beside it, and the Copernicus network writes the final picture (beauty path with _sky before the extension).
def compose_sky_after_render(cfg, beauty_path, first, last, log):
    import numpy as np
    stage_node = hou.node("/stage/karma_settings")
    if stage_node is None:
        raise ValueError("no Karma Render Settings node: build first")
    base, extension = os.path.splitext(beauty_path)
    moon_path, stars_path, clouds_path = base + "_skymoon" + extension, base + "_skystars" + extension, base + "_skyclouds" + extension
    final_path = base + "_sky" + extension
    cam_path = stage_node.parm("camera").evalAsString()
    for frame in range(int(first), int(last) + 1):
        hou.setFrame(frame)
        source = _frame_path(beauty_path, frame)
        layers = _read_layers(source)
        beauty, depth = layers["C"], layers["depth"][..., 0]
        height, width = depth.shape
        plate = render_sky_plate(cfg, camera_of_stage(stage_node.stage(), cam_path), width, height, (frame - 1) / hou.fps())
        sky = (depth <= 0.0).astype(np.float32)
        write_exr_grey(_frame_path(stars_path, frame), plate["add"] * sky[..., None])
        write_exr_grey(_frame_path(moon_path, frame), np.dstack([plate["moon"] * (plate["moon_alpha"] * sky)[..., None], plate["moon_alpha"] * sky]))
        write_exr_grey(_frame_path(clouds_path, frame), np.dstack([plate["clouds"] * (plate["clouds_alpha"] * sky)[..., None], plate["clouds_alpha"] * sky]))
    net, out = build_comp_network(beauty_path, moon_path, stars_path, clouds_path, final_path, first, last, log)
    out.parm("execute").pressButton()
    log("[OK] Sky composed: {} (network {})".format(_frame_path(final_path, int(first)), net.path()))
    return final_path
