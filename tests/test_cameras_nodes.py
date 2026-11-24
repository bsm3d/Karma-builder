# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Checks the camera choice and network integrity: no orphan tool node, user nodes left alone, and the camera rules.

# Revision : 10-10-2026 | Auteur : BSM
from _common import Checker, base_config, load_tool, scratch_dir

hou, k = load_tool()
t = Checker("cameras and nodes")
out_dir = scratch_dir("cameras_nodes")
stage = hou.node("/stage")
logs = []

# user network, positions recorded to check nothing gets moved
sph = stage.createNode("sphere", "my_sphere")
box = stage.createNode("cube", "my_cube")
geo_cam = stage.createNode("camera", "geo_cam")
geo_cam.parm("tz").set(3)
mrg = stage.createNode("merge", "user_geo")
mrg.setInput(0, sph); mrg.setInput(1, box); mrg.setInput(2, geo_cam)
my_cam = stage.createNode("camera", "my_cam")
my_cam.parm("tz").set(9)
user_nodes = [sph, box, geo_cam, mrg, my_cam]
for i, n in enumerate(user_nodes):
    n.setPosition(hou.Vector2(i * 7.0, -30.0))
user_pos = {n.name(): tuple(n.position()) for n in user_nodes}


# ------------------------------------------------------------
def build(**over):
    logs.clear()
    k.setup_karma_environment(dict(base_config(out_dir), **over), logs.append)



# ------------------------------------------------------------
def tool_nodes():
    return [n for n in stage.children() if k._is_tool_node_candidate(n, n.name())]


# ----------------------------------------------------------------------
def upstream(node, seen=None):
    seen = set() if seen is None else seen
    for src in node.inputs():
        if src is not None and src.path() not in seen:
            seen.add(src.path())
            upstream(src, seen)
    return seen



# ------------------------------------------------------------
def no_orphans(label):
    rop = stage.node("render_to_disk")
    reachable = upstream(rop) | {rop.path()}
    orphans = [n.name() for n in tool_nodes() if n.path() not in reachable]
    t.check("no orphan tool node " + label, not orphans, orphans)


def cam_path():
    return stage.node("karma_settings").parm("camera").evalAsString()


# generated camera: focal from the UI, position kept across builds
build()
rc = stage.node("render_cam")
t.check("generated camera created", rc is not None)
t.check("focal from the UI", abs(rc.parm("focalLength").eval() - 50.0) < 1e-6)
t.check("Render Settings gets the prim path", cam_path() == "/cameras/render_cam", cam_path())
rc.parm("tz").set(12.5)
build(new_cam_focal=24.0)
t.check("manual camera position survives a rebuild", abs(stage.node("render_cam").parm("tz").eval() - 12.5) < 1e-6)
t.check("focal follows the UI", abs(stage.node("render_cam").parm("focalLength").eval() - 24.0) < 1e-6)
no_orphans("(generated camera)")

vm = hou.hmath.buildTranslate(1.0, 2.0, 3.0) * hou.hmath.buildRotate(10.0, 20.0, 0.0)
build(new_cam_from_viewport=True, viewport_matrix=tuple(vm.asTuple()))
rc = stage.node("render_cam")
t.check("camera takes the viewport translate", all(abs(a - b) < 1e-4 for a, b in zip(rc.parmTuple("t").eval(), vm.extractTranslates())))
t.check("camera takes the viewport rotate", abs(rc.parm("rx").eval() - 10.0) < 0.01 and abs(rc.parm("ry").eval() - 20.0) < 0.01)

build(camera_choice=my_cam.path())
t.check("generated camera removed", stage.node("render_cam") is None)
t.check("Render Settings uses my_cam", cam_path() == "/cameras/my_cam", cam_path())
t.check("environment chain starts at my_cam", stage.node("physical_sky").input(0) == my_cam)
t.check("the user's camera is untouched", abs(my_cam.parm("tz").eval() - 9.0) < 1e-9)
no_orphans("(existing camera)")

# USD camera prim from the geometry source
t.check("USD camera prim listed", k._stage_camera_prims(mrg.stage()) == ["/cameras/geo_cam"])
build(camera_choice=k.USD_CAMERA_PREFIX + "/cameras/geo_cam", geo_source=mrg.path())
t.check("Render Settings uses the prim", cam_path() == "/cameras/geo_cam", cam_path())
t.check("no generated camera", stage.node("render_cam") is None)
t.check("the prim reaches the render stage", stage.node("karma_settings").stage().GetPrimAtPath("/cameras/geo_cam").IsValid())
no_orphans("(USD camera)")
build(camera_choice=k.USD_CAMERA_PREFIX + "/cameras/geo_cam", geo_source="")
t.check("warns when the geometry source is missing", any("only exists in the stage" in l for l in logs), logs)

# deleted camera falls back to a new one
tmp = stage.createNode("camera", "tmp_cam")
tmp_path = tmp.path()
tmp.destroy()
build(camera_choice=tmp_path)
t.check("fallback creates a camera", stage.node("render_cam") is not None)
t.check("fallback warns", any("not found or invalid" in l for l in logs), logs)

build(camera_choice="/stage/render_cam")
t.check("render_cam kept", stage.node("render_cam") is not None and cam_path() == "/cameras/render_cam")

build(enable_aovs=False)
t.check("pass chain removed when disabled", stage.node("standard_aovs") is None)
t.check("settings fed by the material library", stage.node("karma_settings").input(0).name() == "mtlx_materials")
build(enable_aovs=True)
t.check("pass chain back", stage.node("standard_aovs") is not None)
no_orphans("(AOV toggle)")

for mode, env, fog, clouds in (("Studio", "HDRI Image", False, False), ("3 Points", "HDRI Image", False, False),
                               ("Interior", "None", False, False), ("Interior", "HDRI Image", False, False), ("Environment", "HDRI Image", True, True),
                               ("Environment", "Physical Sky", True, False), ("Studio", "HDRI Image", False, False)):
    build(scene_mode=mode, env_type=env, enable_fog=fog, enable_clouds=clouds, sky_mode=1)
    no_orphans("({} / {} fog={} clouds={})".format(mode, env, fog, clouds))
stale = {"physical_sky", "sky_sun", "sky_atmosphere", "sky_atmosphere_linker", "atmosphere_fog", "cloud_geo", "env_merge", "env_hdri", "window_portal", "key_light"}
t.check("no stale environment node", not (stale & {n.name() for n in tool_nodes()}), sorted(n.name() for n in tool_nodes()))

for n in user_nodes:
    alive = stage.node(n.name())
    t.check("user node {} alive and not moved".format(n.name()), alive is not None and tuple(alive.position()) == user_pos[n.name()])

t.check("a node without a valid stage has no camera prims, nothing raised", k.environment._stage_camera_prims(None) == [])

t.done()
