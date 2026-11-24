# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Checks the sky composite: plate of stars, planets, Milky Way, moon and 2D clouds, and the render with its depth.

# Needs a real Karma render (CPU, a few seconds).
# Revision : 21-10-2026 | Auteur : BSM
import math
import os
import numpy as np
from _common import Checker, base_config, load_tool, scratch_dir

hou, k = load_tool()
from bsm_karma import skycomp, skyplate
import bsm_karma.ephemeris as e

t = Checker("sky composite")
stage = hou.node("/stage")
out_dir = scratch_dir("skycomp")
W, H = 480, 300

cam = stage.createNode("camera", "cam")
cam.parm("ty").set(1.5)
cam.parm("tz").set(8.0)
cam.parm("rx").set(14.0)
cam.parm("ry").set(-72.0)
ball = stage.createNode("sphere", "ball")
ball.parm("tx").set(6.2)   # in the left of the picture, 7 m in front of the camera, not on the moon
ball.parm("ty").set(2.96)
ball.parm("tz").set(5.11)
ball.parm("radius").set(0.6)
geo = stage.createNode("merge", "geo")
geo.setInput(0, ball)
exact = dict(sky_exact=True, sky_year=2024, sky_month=1, sky_day=25, sky_hour=17.9, stars_latitude=48.85, stars_longitude=2.35)
beauty_path = (out_dir + "/beauty.exr").replace("\\", "/")
cfg = dict(base_config(out_dir), scene_mode="Environment", env_type="Physical Sky", engine="cpu", res_x=W, res_y=H, samples=8, camera_choice=cam.path(),
           geo_source=geo.path(), enable_aovs=False, out_path=beauty_path, enable_clouds=True, cloud_type=1, cloud2d_coverage=0.5,
           moon_enable=True, moon_size=3.0, stars_enable=True, stars_milky=True, sky_plate=True, **exact)

t.check("a composite is asked for when the sky has something to show", skycomp.wants_plate(cfg))
t.check("not without the option, not in the day", not skycomp.wants_plate(dict(cfg, sky_plate=False)) and not skycomp.wants_plate(dict(cfg, sky_hour=12.0, enable_clouds=False, moon_enable=False)))
prepared = skycomp.prepare_config(cfg)
t.check("the render carries the beauty and the depth in an EXR", prepared["enable_aovs"] and prepared["aov_depth"] and prepared["output_format"] == "EXR")

logs = []
k.setup_karma_environment(cfg, logs.append)
t.check("no geometry for the sky in the scene (no moon, no stars, no cloud sphere)", all(stage.node(n) is None for n in
        ("sky_moon", "sky_moon_disc", "sky_moon_halo", "sky_stars_ref", "sky_milky", "cloud_layer_2d", "cloud_layer_2d_mat")), [n.name() for n in stage.children()])
t.check("the AOVs (depth) are on, no warning", stage.node("standard_aovs") is not None and not [l for l in logs if "WARN" in l], [l for l in logs if "WARN" in l])
try:
    stage.node("render_to_disk").render()
except hou.OperationFailed as exc:
    t.check("the render works with the AOVs", False, str(exc)[:120])
layers = skycomp._read_layers(beauty_path)
t.check("the render has its beauty and a depth that is 0 on the sky and a distance on the ball", "C" in layers and "depth" in layers
        and float(layers["depth"][5, 5, 0]) == 0.0 and float(layers["depth"].max()) > 1.0, sorted(layers))

# the plate: the moon where the ephemeris puts it, the stars where the catalogue puts them
camera = skyplate.camera_of_stage(stage.node("karma_settings").stage(), "/cameras/cam")
plate = skyplate.render_sky_plate(dict(cfg), camera, W, H)
snap = e.apply_exact_sky(dict(cfg))["_snapshot"]
moon_world = np.array([e.world_vector(snap["moon"]["altitude"], snap["moon"]["azimuth"])])
column, row, front = skyplate.project(np, camera, W, H, moon_world)
t.check("the moon is in front of the camera and in the picture, at the centre (the camera looks at it)", bool(front[0]) and abs(column[0] - W / 2) < 30 and abs(row[0] - H / 2) < 30, (column, row))
alpha = plate["moon_alpha"]
cy, cx = int(row[0]), int(column[0])
t.check("the plate has the moon disc there, nothing far from it", alpha[cy, cx] > 0.9 and alpha[5, 5] == 0.0 and alpha.sum() > 200, float(alpha.sum()))
t.check("with its halo", plate["add"][cy, cx + 45].max() > plate["add"][5, 5].max() + 0.01)

# stars: a point where Jupiter is
planets = {p[0]: p for p in snap["planets"]}
alt, az = e.horizontal(planets["Jupiter"][1], planets["Jupiter"][2], snap["lst"], 48.85)
jup_world = np.array([e.world_vector(alt, az)])
jc, jr, jf = skyplate.project(np, camera, W, H, jup_world)
t.check("Jupiter is high in the south, not in this view (the camera looks east): the projection says it is out of the picture or behind", (not jf[0]) or not (0 <= jc[0] < W and 0 <= jr[0] < H), (jc, jr, jf))
def look_at(direction):
    forward = np.array(direction, dtype=float)
    right = np.cross(forward, [0.0, 1.0, 0.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    return dict(camera, rotation=np.stack([right, up, -forward], axis=1))


south_cam = look_at(jup_world[0])
sc, sr, sf = skyplate.project(np, south_cam, W, H, jup_world)
south_plate = skyplate.render_sky_plate(dict(cfg, moon_enable=False, enable_clouds=False, stars_milky=False), south_cam, W, H)
patch_around = south_plate["add"][int(sr[0]) - 6:int(sr[0]) + 7, int(sc[0]) - 6:int(sc[0]) + 7]
t.check("looking at Jupiter: it is at the centre of the picture and the brightest spot of it", bool(sf[0]) and abs(sc[0] - W / 2) < 1 and abs(sr[0] - H / 2) < 1
        and patch_around.max() >= 0.99 * south_plate["add"].max(), (sc, sr, float(patch_around.max()), float(south_plate["add"].max())))

# the composite: Copernicus gives what the arithmetic gives, the ball is left alone
final_path = skycomp.compose_sky_after_render(cfg, beauty_path, 1, 1, logs.append)
net = hou.node("/obj/" + skycomp.COMP_NET_NAME)
t.check("the Copernicus network is there, with the render, the layers, the blends and the output", net is not None and all(net.node(n) is not None for n in
        ("render", "moon", "stars", "clouds", "moon_over", "stars_add", "clouds_over", "final")), [c.name() for c in net.children()] if net else None)
import OpenImageIO as oiio
reader = oiio.ImageInput.open(final_path)
spec = reader.spec()
final = np.array(reader.read_image("float")).reshape(spec.height, spec.width, spec.nchannels)[..., :3]
reader.close()
numpy_final = skyplate.compose(np, layers["C"], layers["depth"][..., 0], plate)
t.check("the picture of the network is the arithmetic of the plate over the render (half float precision)", float(np.abs(final - numpy_final).max()) < 2e-3, float(np.abs(final - numpy_final).max()))
ball_pixels = layers["depth"][..., 0] > 0.0
t.check("the geometry is untouched: the stars and the moon are only where the depth is 0", float(np.abs(final[ball_pixels] - layers["C"][..., :3][ball_pixels]).max()) < 2e-3)
t.check("and the sky has changed (the moon over the sky)", float(np.abs(final[cy, cx] - layers["C"][cy, cx, :3]).max()) > 0.1)

# a network of the user with the same name is not the tool's to destroy; its own networks are replaced, not piled up
net.destroy()
mine = hou.node("/obj").createNode("copnet", skycomp.COMP_NET_NAME)
mine.createNode("null", "my_grade")
paths = [(out_dir + "/" + n).replace("\\", "/") for n in ("b.exr", "m.exr", "s.exr", "c.exr", "f.exr")]
first_net, _ = skycomp.build_comp_network(*paths, 1, 1)
first_path = first_net.path()
second_net, _ = skycomp.build_comp_network(*paths, 1, 1)
tool_nets = [n for n in hou.node("/obj").children() if n.name().startswith(skycomp.COMP_NET_NAME) and n.userData("bsm_karma_managed") == "1"]
t.check("the user's own network with that name is left alone, with its nodes", mine.path() == "/obj/" + skycomp.COMP_NET_NAME and mine.node("my_grade") is not None and first_path != mine.path(), first_path)
t.check("a second render replaces the network of the tool", len(tool_nets) == 1 and tool_nets[0].path() == second_net.path(), [n.path() for n in tool_nets])
# what the user added in the network of the tool stays at the next render; only the files move
second_net.createNode("null", "my_glow")
paths2 = [(out_dir + "/" + n).replace("\\", "/") for n in ("b2.exr", "m2.exr", "s2.exr", "c2.exr", "f2.exr")]
third_net, third_out = skycomp.build_comp_network(*paths2, 1, 3)
t.check("a node of the user in the tool's network survives the next render", third_net.path() == second_net.path() and third_net.node("my_glow") is not None, third_net.path())
t.check("and the files and the range are the new ones", third_net.node("render").parm("filename").eval() == paths2[0] and third_out.parm("copoutput").eval() == paths2[4]
        and third_out.parm("f2").eval() == 3 and third_out.parm("trange").eval() == 1, (third_net.node("render").parm("filename").eval(), third_out.parm("copoutput").eval(), third_out.parm("f2").eval(), third_out.parm("trange").eval()))
t.check("the blends use their names: over, add, over", [third_net.node(n).parm("mode").evalAsString() for n in ("moon_over", "stars_add", "clouds_over")] == ["over", "add", "over"])
# a network that lost one of the tool's nodes is rebuilt whole
third_net.node("stars_add").destroy()
fourth_net, _ = skycomp.build_comp_network(*paths2, 1, 1)
t.check("a network missing a node of the tool is rebuilt whole", all(fourth_net.node(n) is not None for n in skycomp.COMP_NODES) and fourth_net.node("my_glow") is None
        and len([n for n in hou.node("/obj").children() if n.userData("bsm_karma_managed") == "1"]) == 1)
t.done()
