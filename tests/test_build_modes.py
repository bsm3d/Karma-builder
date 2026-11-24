# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Builds every scene mode and checks that the settings reached the nodes.

# On H22 many guessed parameter names did not exist, and the quiet setters hid it.
# Revision : 10-10-2026 | Auteur : BSM
import os
from _common import Checker, base_config, load_tool, scratch_dir

hou, k = load_tool()
t = Checker("build modes")
out_dir = scratch_dir("build_modes")
stage = hou.node("/stage")
logs = []


#------------------------------------------------------------
update_mode_before = hou.updateModeSetting()


def build(**over):
    logs.clear()
    k.setup_karma_environment(dict(base_config(out_dir), **over), logs.append)
    if hou.updateModeSetting() != update_mode_before:
        t.check("a build leaves Houdini's update mode as it found it", False, hou.updateModeSetting())
    # a setting the build could not apply (a parameter another Houdini version named differently) is reported, never lost in silence
    ignored = [l for l in logs if "not applied" in l]
    if ignored:
        t.check("a build applies every setting it sets {}".format(sorted(over)), False, ignored)


# --------------------------------------------------
def val(node_name, parm):
    node = stage.node(node_name)
    p = node.parm(parm) if node else None
    return p.eval() if p is not None else "<missing>"


for mode, env in (("Environment", "Physical Sky"), ("Environment", "HDRI Image"), ("Studio", "HDRI Image"),
                  ("3 Points", "HDRI Image"), ("Interior", "None"), ("Interior", "HDRI Image")):
    build(scene_mode=mode, env_type=env)
    rop = stage.node("render_to_disk")
    chain, node = [], rop
    while node is not None:
        chain.append(node.name())
        node = node.input(0)
    t.check("{} / {} builds a chain to the ROP".format(mode, env), rop is not None and len(chain) >= 5, chain)
    t.check("{} / {} logs no warning".format(mode, env), not [l for l in logs if "WARN" in l], [l for l in logs if "WARN" in l])

# values reach the nodes
build(env_type="HDRI Image", engine="xpu", samples=777, res_x=2000, res_y=900, denoiser="OIDN (CPU)",
      exr_precision="32-bit float", aov_half_precision=True, aov_ao=True, aov_id=True, aov_albedo=True,
      enable_fog=True, enable_clouds=True, hdri_path=out_dir + "/sky.exr")
t.check("engine", val("karma_settings", "engine") == "xpu")
t.check("samples reach pathtracedsamples", val("karma_settings", "pathtracedsamples") == 777, val("karma_settings", "pathtracedsamples"))
t.check("resolution mode manual", val("karma_settings", "res_mode") == "manual")
t.check("resolution", tuple(stage.node("karma_settings").parmTuple("resolution").eval()) == (2000, 900))
t.check("denoiser token", val("karma_settings", "denoiser") == "oidn", val("karma_settings", "denoiser"))
t.check("camera is a prim path", val("karma_settings", "camera") == "/cameras/render_cam", val("karma_settings", "camera"))
t.check("ROP renderer matches the engine", val("render_to_disk", "renderer") == "BRAY_HdKarmaXPU")
t.check("ROP points at the render settings prim", val("render_to_disk", "rendersettings") == val("karma_settings", "primpath"))
for toggle in ("hitPz", "hitN", "ambientocclusion", "primid", "element", "albedo"):
    t.check("AOV toggle {} on".format(toggle), val("standard_aovs", toggle) == 1, val("standard_aovs", toggle))
t.check("beauty precision follows the EXR setting (32-bit)", val("standard_aovs", "beautyprecision") == "color4f", val("standard_aovs", "beautyprecision"))
t.check("dome texture set", val("env_hdri", "xn__inputstexturefile_r3ah") == out_dir + "/sky.exr", val("env_hdri", "xn__inputstexturefile_r3ah"))
t.check("fog density", abs(val("atmosphere_fog", "density") - 0.25) < 1e-6)
t.check("cloud geometry prim path", val("cloud_geo", "primpath") == "/World/Environment/Clouds")

# clouds use SideFX's Quick Cloud Material
from pxr import UsdShade
t.check("Quick Cloud Material node created", stage.node("quickcloudmaterial") is not None)
t.check("cloud density 0.2 maps to SideFX's default density scale", abs(val("quickcloudmaterial", "densityscale") - 1.0) < 1e-6, val("quickcloudmaterial", "densityscale"))
t.check("assignment points at the material prim", val("assign_cloud_shader", "matspecpath1") == "/materials/quickcloudmaterial", val("assign_cloud_shader", "matspecpath1"))
render_stage = stage.node("karma_settings").stage()
t.check("material prim exists on the render stage", render_stage.GetPrimAtPath("/materials/quickcloudmaterial").IsValid())
cloud_prims = [p for p in render_stage.Traverse() if str(p.GetPath()).startswith("/World/Environment/Clouds") and p.GetTypeName() not in ("", "Xform", "Scope")]
bound = [UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial()[0].GetPath() for p in cloud_prims]
t.check("the cloud volume is bound to it", bool(bound) and all(str(b) == "/materials/quickcloudmaterial" for b in bound), (len(cloud_prims), [str(b) for b in bound][:3]))
t.check("fog and cloud prims are not offered as material targets", not [p for p, _, _ in k._stage_target_prims(render_stage) if p.startswith("/World/Environment")])
t.check("no KarmaCloud leftover in the material library", stage.node("mtlx_materials").node("KarmaCloud") is None)
t.check("fog takes the ambient tint (default white)", tuple(round(v, 3) for v in stage.node("atmosphere_fog").parmTuple("color").eval()) == (1.0, 1.0, 1.0))
build(env_type="HDRI Image", enable_fog=True, enable_clouds=True, cloud_density=0.4, sky_amb_r=0.5, sky_amb_g=0.6, sky_amb_b=0.7, hdri_path=out_dir + "/sky.exr")
t.check("denser clouds raise the density scale", abs(val("quickcloudmaterial", "densityscale") - 2.0) < 1e-6, val("quickcloudmaterial", "densityscale"))
t.check("fog color follows the ambient tint", tuple(round(v, 3) for v in stage.node("atmosphere_fog").parmTuple("color").eval()) == (0.5, 0.6, 0.7))
build(env_type="HDRI Image", enable_clouds=True, cloud_material_path="/materials/mine", hdri_path=out_dir + "/sky.exr")
t.check("a custom material path replaces the quick material", stage.node("quickcloudmaterial") is None and val("assign_cloud_shader", "matspecpath1") == "/materials/mine")
build(env_type="HDRI Image", enable_clouds=True, hdri_path=out_dir + "/sky.exr")
t.check("back to automatic recreates it", stage.node("quickcloudmaterial") is not None)
build(env_type="HDRI Image", enable_clouds=False, hdri_path=out_dir + "/sky.exr")
t.check("disabling clouds removes the material node", stage.node("quickcloudmaterial") is None and stage.node("assign_cloud_shader") is None)

# --- 2D clouds: a sphere around the scene painted with a generated picture (a second dome is never seen by the camera) ---
build(enable_clouds=True, cloud_type=1, cloud2d_brightness=0.8, sky_int=2.0)
layer = stage.node("cloud_layer_2d")
last = stage.node("cloud_layer_2d_mat")
t.check("2D clouds: a sphere node, its material reference and its assignment", layer is not None and layer.type().name().split("::")[0] == "sopcreate"
        and stage.node("cloud_layer_2d_ref") is not None and last is not None)
t.check("2D clouds: merged with the sky", last in stage.node("env_merge").inputs(), [n.name() for n in stage.node("env_merge").inputs()])
t.check("2D clouds: no volume nodes left", all(stage.node(n) is None for n in ("cloud_geo", "cloud_xform", "quickcloudmaterial", "assign_cloud_shader")))
t.check("2D clouds: no warning", not [l for l in logs if "WARN" in l], [l for l in logs if "WARN" in l])
cloud_stage = stage.node("karma_settings").stage()
from pxr import UsdShade
mesh = [p for p in cloud_stage.Traverse() if str(p.GetPath()).startswith("/World/Environment/CloudLayer/") and p.GetTypeName() == "Mesh"]
t.check("2D clouds: the sphere is a mesh with lat-long UVs", bool(mesh) and mesh[0].GetAttribute("primvars:uv").IsValid() or bool(mesh) and mesh[0].GetAttribute("primvars:st").IsValid(), [str(p.GetPath()) for p in mesh])
bound = UsdShade.MaterialBindingAPI(cloud_stage.GetPrimAtPath("/World/Environment/CloudLayer")).ComputeBoundMaterial()[0]
t.check("2D clouds: the material is a real material bound to the sphere", bool(bound) and bound.GetPath().pathString == "/World/Environment/CloudLayerMaterial", bound.GetPath() if bound else None)
card_file = stage.node("cloud_layer_2d_ref").parm("filepath1").evalAsString()
card_text = open(card_file, encoding="utf-8").read()
import re
texture_path = re.search(r'name="file" type="filename" value="([^"]+)"', card_text).group(1)
t.check("2D clouds: the material reads a generated picture", "bsm_clouds_" in texture_path, texture_path)
t.check("2D clouds: the picture exists", os.path.isfile(texture_path.replace("\\", "/")), texture_path)
t.check("2D clouds: emission is the brightness times the sky intensity", 'name="emission" type="float" value="1.6"' in card_text, card_text[:400])
t.check("2D clouds: the picture is an EXR", texture_path.lower().endswith(".exr"), texture_path)
sky_parm = next((n for n in ("sky_intensity", "skyintensity") if stage.node("physical_sky").parm(n) is not None), None)
t.check("2D clouds: the sky is not made brighter (that is for volumes)", sky_parm is not None and abs(val("physical_sky", sky_parm) - 2.0) < 1e-6, (sky_parm, val("physical_sky", sky_parm) if sky_parm else None))
build(enable_clouds=True, cloud_type=0, sky_int=2.0)
t.check("3D clouds: the sky is brighter to compensate the volume", sky_parm is not None and abs(val("physical_sky", sky_parm) - 8.0) < 1e-6, val("physical_sky", sky_parm) if sky_parm else None)
build(enable_clouds=True, cloud_type=1, cloud2d_brightness=0.8, sky_int=2.0)
build(enable_clouds=True, cloud_type=0)
t.check("back to 3D clouds: the 2D layer is removed, the volume is back", stage.node("cloud_layer_2d") is None and stage.node("cloud_layer_2d_mat") is None and stage.node("cloud_geo") is not None)
build(enable_clouds=True, cloud_type=1)
t.check("3D to 2D again: the volume nodes are removed", stage.node("cloud_geo") is None and stage.node("cloud_layer_2d") is not None)
build(enable_clouds=False, cloud_type=1)
t.check("clouds off: no 2D layer either", stage.node("cloud_layer_2d") is None)
build(scene_mode="Studio", env_type="HDRI Image", enable_clouds=True, cloud_type=1)
t.check("clouds only exist in Environment mode", stage.node("cloud_layer_2d") is None)

# --- lamp colors: temperature and tint of the lamps of Studio, 3 Points and Interior ---
def lamp_rgb(name):
    node = stage.node(name)
    for parm_tuple in node.parmTuples():
        if len(parm_tuple) == 3 and parm_tuple.name().lower().startswith("xn__inputscolor"):
            return tuple(parm_tuple.eval())
    return None


build(scene_mode="Studio", env_type="HDRI Image", lamp_key_temp=3000)
warm = lamp_rgb("studio_key")
build(scene_mode="Studio", env_type="HDRI Image", lamp_key_temp=10000)
cool = lamp_rgb("studio_key")
t.check("Studio: a low key temperature gives a warm lamp, a high one a cool lamp", warm and cool and warm[0] > warm[2] and cool[2] > cool[0], (warm, cool))
build(scene_mode="Studio", env_type="HDRI Image", lamp_key_tint=1.0)
t.check("Studio: a positive tint raises red and blue over green", lamp_rgb("studio_key")[1] < lamp_rgb("studio_key")[0], lamp_rgb("studio_key"))
build(scene_mode="3 Points", env_type="HDRI Image", lamp_key_temp=3000, lamp_fill_temp=10000, lamp_rim_temp=6500)
key, fill, rim = lamp_rgb("key_light"), lamp_rgb("fill_light"), lamp_rgb("rim_light")
t.check("3 Points: each lamp has its own color", key[0] > key[2] and fill[2] > fill[0] and abs(rim[0] - rim[2]) < 0.1, (key, fill, rim))
build(scene_mode="Interior", env_type="None", lamp_key_temp=3000)
window = lamp_rgb("window_portal")
t.check("Interior: the window light takes the key color", window[0] > window[2], window)
t.check("Interior: no sky and no dome without a window view", stage.node("physical_sky") is None and stage.node("env_hdri") is None and stage.node("window_portal") is not None)
build(scene_mode="Interior", env_type="HDRI Image")
t.check("Interior: an HDRI is the view through the window, still no sky", stage.node("env_hdri") is not None and stage.node("physical_sky") is None and stage.node("window_portal") is not None)
t.check("lamp colors: no warning", not [l for l in logs if "WARN" in l], [l for l in logs if "WARN" in l])

# --- cloud animation: the wind moves the 3D clouds and the drift turns the 2D ones, with the time
build(enable_clouds=True, cloud_type=0, cloud_wind_speed=10.0, cloud_wind_dir=90.0)
xform = stage.node("cloud_xform")
tx, tz = xform.parm("tx"), xform.parm("tz")
t.check("3D clouds: the wind is an expression of the time (none along Z at 90 degrees)", "$T" in tx.expression() and not tz.keyframes(), (tx.expression() if tx.keyframes() else None))
hou.setFrame(hou.timeToFrame(0.0)); start = tx.eval()
hou.setFrame(hou.timeToFrame(10.0)); later = tx.eval(); later_z = tz.eval()
t.check("3D clouds: at 10 m/s towards +X they are 100 m further after ten seconds, and not moved along Z", abs((later - start) - 100.0) < 1e-3 and abs(later_z) < 1e-3, (start, later, later_z))
t.check("3D clouds: the altitude is kept", abs(xform.parm("ty").eval() - 140.0) < 1e-6)
build(enable_clouds=True, cloud_type=0, cloud_wind_speed=0.0)
t.check("3D clouds: wind off takes the animation off again", not xform.parm("tx").keyframes() and abs(xform.parm("tx").eval()) < 1e-9)
build(enable_clouds=True, cloud_type=1, cloud2d_drift=30.0)
ry = stage.node("cloud_layer_2d").parm("ry")
hou.setFrame(hou.timeToFrame(0.0)); a = ry.eval()
hou.setFrame(hou.timeToFrame(60.0)); b = ry.eval()
t.check("2D clouds: 30 degrees per minute turn the sphere 30 degrees in a minute", abs((b - a) - 30.0) < 1e-3, (a, b))
build(enable_clouds=True, cloud_type=1, cloud2d_drift=0.0)
t.check("2D clouds: no drift, no animation", not stage.node("cloud_layer_2d").parm("ry").keyframes())
hou.setFrame(1)
build(enable_clouds=False)

# --- the moon: placed from the sun and the phase, a lit ball with a halo, only built while it is above the horizon ---
import numpy as np
from bsm_karma.moon import moon_state
MOON_NODES = ("sky_moon", "sky_moon_disc", "sky_moon_halo", "sky_moon_ref", "sky_moon_mat")
build(enable_clouds=False)
t.check("moon: not built unless asked", all(stage.node(n) is None for n in MOON_NODES))
full = moon_state(dict(sky_elev=-12.0, sky_azim=0.0, moon_enable=True, moon_phase=0.5))
t.check("moon: a full moon is exactly opposite the sun (whatever the sun's place)", float(np.dot(full["moon"], full["sun"])) < -0.999999 and abs(full["altitude"] - 12.0) < 1e-6 and abs(full["azimuth"] - 180.0) < 1e-6, (full["altitude"], full["azimuth"]))
new = moon_state(dict(sky_elev=20.0, sky_azim=70.0, moon_enable=True, moon_phase=0.0))
t.check("moon: a new moon is where the sun is, and dark", float(np.dot(new["moon"], new["sun"])) > 0.999999 and new["lit"] < 1e-6)
quarter = moon_state(dict(sky_elev=10.0, sky_azim=40.0, moon_enable=True, moon_phase=0.25))
t.check("moon: a first quarter is 90 degrees from the sun and half lit", abs(float(np.dot(quarter["moon"], quarter["sun"]))) < 1e-6 and abs(quarter["lit"] - 0.5) < 1e-6)
before = [moon_state(dict(sky_elev=e, sky_azim=60.0, moon_enable=True, moon_phase=0.25))["altitude"] for e in (-10.0, 0.0, 10.0, 20.0)]
t.check("moon: it follows the sun along an inclined path (its altitude is not a straight line of the sun's)", len(set(round(a, 3) for a in before)) == 4 and abs((before[1] - before[0]) - (before[3] - before[2])) > 1e-3, before)
build(enable_clouds=False, moon_enable=True, sky_elev=-12.0, sky_azim=0.0, moon_phase=0.5, moon_size=4.0)
t.check("moon: nodes built and merged with the sky", all(stage.node(n) is not None for n in MOON_NODES) and stage.node("sky_moon_mat") in stage.node("env_merge").inputs())
t.check("moon: no warning", not [l for l in logs if "WARN" in l], [l for l in logs if "WARN" in l])
moon_stage = stage.node("karma_settings").stage()
from pxr import UsdGeom, Gf
disc = moon_stage.GetPrimAtPath("/World/Environment/Moon_sky_moon_disc")
center = UsdGeom.Xformable(disc).ComputeLocalToWorldTransform(0).ExtractTranslation() if disc else Gf.Vec3d(0)
far = k.config.MOON_DISTANCE
t.check("moon: the disc is far away (84 km) towards the moon (altitude 12, azimuth 180)", abs(center[1] - far * 0.20791) < 0.002 * far and abs(center[2] - far * 0.97815) < 0.002 * far and abs(center[0]) < 0.002 * far, tuple(center))
halo = moon_stage.GetPrimAtPath("/World/Environment/Moon_sky_moon_halo")
bound_disc = UsdShade.MaterialBindingAPI(disc).ComputeBoundMaterial()[0] if disc else None
bound_halo = UsdShade.MaterialBindingAPI(halo).ComputeBoundMaterial()[0] if halo else None
t.check("moon: the disc and the halo have their own material", bool(bound_disc) and bool(bound_halo) and bound_disc.GetPath().pathString.endswith("/Moon") and bound_halo.GetPath().pathString.endswith("/MoonHalo"),
        (bound_disc.GetPath() if bound_disc else None, bound_halo.GetPath() if bound_halo else None))
moon_text = open(stage.node("sky_moon_ref").parm("filepath1").evalAsString(), encoding="utf-8").read()
t.check("moon: the material is lit by the sun's direction and has a halo", 'name="sun_facing"' in moon_text and 'name="SR_MoonHalo"' in moon_text and ("moon.jpg" in moon_text) == bool(k._sky_data_file("moon.jpg")))
def moon_light(): return stage.node("sky_moon").stage().GetPrimAtPath("/lights/sky_moon").GetAttribute("inputs:intensity").Get()
t.check("moon: the light glows at full moon", moon_light() > 0.2, moon_light())
build(enable_clouds=False, moon_enable=True, sky_elev=30.0, sky_azim=0.0, moon_phase=0.5)
t.check("moon: a full moon is under the horizon with the sun high: no node at all", all(stage.node(n) is None for n in MOON_NODES))
build(enable_clouds=False, moon_enable=True, sky_elev=30.0, sky_azim=0.0, moon_phase=0.25)
day_quarter = moon_state(dict(sky_elev=30.0, sky_azim=0.0, moon_phase=0.25, moon_enable=True))
t.check("moon: built when it is above the horizon even in the day, and only then", all(stage.node(n) is not None for n in MOON_NODES) == day_quarter["active"], day_quarter["altitude"])
build(enable_clouds=False, moon_enable=False, sky_elev=-12.0)
t.check("moon: switched off removes its nodes", all(stage.node(n) is None for n in MOON_NODES))
build(scene_mode="Studio", env_type="HDRI Image", moon_enable=True, sky_elev=-12.0)
t.check("moon: only in Environment mode", all(stage.node(n) is None for n in MOON_NODES))
build()

# --- the night sky: stars as points, the Milky Way as a picture; only built once the sun is down ---
STAR_NODES = ("sky_stars_ref", "sky_stars_mtl", "sky_stars_mat")
build(enable_clouds=False)
t.check("stars: not built unless asked", all(stage.node(n) is None for n in STAR_NODES) and stage.node("sky_milky") is None)
build(enable_clouds=False, stars_enable=True, sky_elev=30.0)
t.check("stars: nothing is built in the day", all(stage.node(n) is None for n in STAR_NODES) and stage.node("sky_milky") is None)
if k.nightsky.night_sources()[1]:
    build(enable_clouds=False, stars_enable=True, sky_elev=-20.0, stars_latitude=45.0, stars_time=0.0, stars_milky=True)
    t.check("stars: nodes built and merged with the sky", all(stage.node(n) is not None for n in STAR_NODES) and stage.node("sky_milky") is not None and stage.node("sky_stars_mat") in stage.node("env_merge").inputs())
    t.check("stars: no warning", not [l for l in logs if "WARN" in l], [l for l in logs if "WARN" in l])
    star_stage = stage.node("karma_settings").stage()
    stars_prim = star_stage.GetPrimAtPath("/World/Environment/NightStars/Stars")
    positions = stars_prim.GetAttribute("points").Get() if stars_prim else []
    t.check("stars: thousands of real points, sharp at any resolution", len(positions) > 4000 and stars_prim.GetTypeName() == "Points", len(positions))
    t.check("stars: each has a width, a colour and a phase of its own", len(stars_prim.GetAttribute("widths").Get()) == len(positions) and len(stars_prim.GetAttribute("primvars:displayColor").Get()) == len(positions)
            and len(stars_prim.GetAttribute("primvars:phase").Get()) == len(positions))
    # stars under the horizon are left out: Polaris is found as the point nearest the celestial pole
    pole = np.array([0.0, np.sin(np.radians(45.0)), -np.cos(np.radians(45.0))])
    pts = np.array(positions, dtype=float)
    around = np.degrees(np.arccos(np.clip((pts / np.linalg.norm(pts, axis=1)[:, None]) @ pole, -1, 1)))
    polaris = int(np.argmin(around))
    where = pts[polaris]
    t.check("stars: Polaris stands at the celestial pole, at the latitude above the north horizon", around[polaris] < 1.5, float(around[polaris]))
    t.check("stars: a halo set for the bright ones", star_stage.GetPrimAtPath("/World/Environment/NightStars/StarGlow").IsValid() and 50 < len(star_stage.GetPrimAtPath("/World/Environment/NightStars/StarGlow").GetAttribute("points").Get()) < 1000)
    t.check("stars: the materials twinkle with the clock and glow with the facing ratio", all(w in open(stage.node("sky_stars_mtl").parm("filepath1").evalAsString(), encoding="utf-8").read() for w in ('<time name="clock"', 'name="facing"')))
    bound = UsdShade.MaterialBindingAPI(stars_prim).ComputeBoundMaterial()[0]
    t.check("stars: the stars have their material", bool(bound) and bound.GetPath().pathString.endswith("/StarMat"), bound.GetPath() if bound else None)
    t.check("stars: opaque in the deep night", 'name="opacity" type="color3" value="1.000, 1.000, 1.000"' in open(stage.node("sky_stars_mtl").parm("filepath1").evalAsString(), encoding="utf-8").read())
    build(enable_clouds=False, stars_enable=True, sky_elev=-20.0, stars_latitude=45.0, stars_time=6.0)
    later = np.array(stage.node("karma_settings").stage().GetPrimAtPath("/World/Environment/NightStars/Stars").GetAttribute("points").Get(), dtype=float)
    still = np.min(np.linalg.norm(later - where, axis=1))
    t.check("stars: the hours turn the sky and leave the pole where it is", still < 0.03 * k.nightsky.STARS_RADIUS, float(still))
    build(enable_clouds=False, stars_enable=True, sky_elev=-20.0, stars_milky=False)
    t.check("stars: without the Milky Way there is no sphere", stage.node("sky_milky") is None and all(stage.node(n) is not None for n in STAR_NODES))
    build(enable_clouds=False, stars_enable=True, sky_elev=-5.0)
    t.check("stars: in the twilight they are half shown (a cross fade with the sky)", 'value="0.' in open(stage.node("sky_stars_mtl").parm("filepath1").evalAsString(), encoding="utf-8").read().split('name="SR_Star"')[1].split("</standard_surface>")[0])
else:
    t.check("stars: no star picture here, a warning and no node", all(stage.node(n) is None for n in STAR_NODES) and any("Night sky skipped" in l for l in logs))
build(enable_clouds=False, stars_enable=False, sky_elev=-20.0)
t.check("stars: switched off removes the nodes", all(stage.node(n) is None for n in STAR_NODES) and stage.node("sky_milky") is None)
build(scene_mode="Studio", env_type="HDRI Image", stars_enable=True, sky_elev=-20.0)
t.check("stars: only in Environment mode", all(stage.node(n) is None for n in STAR_NODES))
build()

# --- AOVs: one beauty only (two planes named C stop husk: a render to disk with AOVs was a plain RGBA) ---
build(enable_aovs=True)
vars_names = []
for var in stage.node("karma_settings").stage().GetPrimAtPath("/Render/karma_settings/Products/renderproduct").GetRelationship("orderedVars").GetTargets():
    prim = stage.node("karma_settings").stage().GetPrimAtPath(var)
    vars_names.append(str(prim.GetAttribute("sourceName").Get()))
t.check("AOVs on: each render var of the product is there once (no two planes named C)", len(vars_names) == len(set(vars_names)) and vars_names.count("C.*[LO]") == 1, vars_names)
build(enable_aovs=False)
t.check("AOVs off: the settings node makes the beauty", stage.node("karma_settings").parm("beauty").eval() == 1)
build()

# --- a node made after the render chain keeps the display flag: a build does not take it back ---
build()
after = stage.createNode("sphere", "made_after")
after.setInput(0, stage.node("karma_settings"))
after.setDisplayFlag(True)
build(live=True)
t.check("display: a live build leaves the display flag on a node made after Karma Render Settings", after.isDisplayFlagSet() and not stage.node("karma_settings").isDisplayFlagSet())
build()
t.check("display: so does a Build", after.isDisplayFlagSet())
after.setDisplayFlag(False)
stage.node("env_merge").setDisplayFlag(True)
build()
t.check("display: when nothing at or after the chain is displayed, the chain is shown again", stage.node("karma_settings").isDisplayFlagSet())
after.destroy()
build()

# --- the small cache files must not push a picture that a node reads out of the cache ---
import time
build(enable_clouds=True, cloud_type=1)
cloud_picture = re.search(r'name="file" type="filename" value="([^"]+)"', open(stage.node("cloud_layer_2d_ref").parm("filepath1").evalAsString(), encoding="utf-8").read()).group(1)
for brightness in range(1, 12):
    build(enable_clouds=True, cloud_type=1, moon_enable=True, moon_phase=0.5, sky_elev=-5.0 - brightness, cloud2d_brightness=0.3 + 0.1 * brightness, moon_intensity=0.5 + 0.1 * brightness, stars_enable=True)
t.check("cache: a dozen slider values later the cloud picture is still there", os.path.isfile(cloud_picture), cloud_picture)
build()

# --- the Volumetric Atmosphere needs a camera that sees as far as the atmosphere
def far_clip(node_name):
    node = stage.node(node_name)
    for parm_tuple in node.parmTuples():
        if len(parm_tuple) == 2 and "clip" in parm_tuple.name().lower():
            return tuple(parm_tuple.eval())
    return None


build(sky_mode=0)
normal = far_clip("render_cam")
build(sky_mode=1)
t.check("Volumetric Atmosphere: the camera of the tool sees as far as the atmosphere", normal is not None and far_clip("render_cam")[1] >= 2000000.0 and far_clip("render_cam")[0] == normal[0],
        (normal, far_clip("render_cam")))
t.check("Volumetric Atmosphere: the Log says what was done", any("far clipping range of render_cam is now" in l for l in logs), [l for l in logs if "Atmosphere" in l])
mine = stage.createNode("camera", "my_atmo_cam")
build(sky_mode=1, camera_choice=mine.path())
t.check("a camera of the user is not changed, the Log warns", far_clip("my_atmo_cam")[1] < 2000000.0 and any("does not change a camera it did not make" in l for l in logs), (far_clip("my_atmo_cam"), [l for l in logs if "Atmosphere" in l]))
mine.destroy()
build(sky_mode=0)

build(engine="cpu", sky_mode=1, sky_atm_rayleigh=2.0, sky_atm_mie=3.0)
t.check("CPU uses path traced convergence", val("karma_settings", "convergence_mode") == "Path Traced")
t.check("rayleigh scale", abs(val("sky_atmosphere", "rayleighscale") - 6e-05) < 1e-12, val("sky_atmosphere", "rayleighscale"))
t.check("mie scale", abs(val("sky_atmosphere", "miescatterscale") - 1.5e-05) < 1e-12, val("sky_atmosphere", "miescatterscale"))
t.check("no light link: the sun lights the geometry as well as the atmosphere", stage.node("sky_atmosphere_linker") is None)
# the volumetric sky is a Karma Sky Atmosphere and a distant light, not the Karma Physical Sky node
sun = stage.node("sky_sun")
t.check("volumetric: a Karma Sky Atmosphere and a distant sun, no Physical Sky node", stage.node("sky_atmosphere") is not None and sun is not None and stage.node("physical_sky") is None
        and stage.node("sky_atmosphere").type().name().startswith("karmaskyatmosphere"))
sun_prim = sun.stage().GetPrimAtPath("/lights/sky_sun")
t.check("volumetric: the sun is a normalized distant light (not normalized it renders black)", sun_prim.GetTypeName() == "DistantLight" and sun_prim.GetAttribute("inputs:normalize").Get() is True, sun_prim.GetTypeName())
build(engine="cpu", sky_mode=1, sky_elev=40, sky_azim=30, sky_sun_int=3.0)
from pxr import UsdGeom
t.check("volumetric: the sun slider is divided by 3 (Midday 3.0 is Karma's own sun of 1.0, 3 burns the sky white)",
        abs(stage.node("sky_sun").stage().GetPrimAtPath("/lights/sky_sun").GetAttribute("inputs:intensity").Get() - 1.0) < 1e-6)
axis = UsdGeom.Xformable(stage.node("sky_sun").stage().GetPrimAtPath("/lights/sky_sun")).ComputeLocalToWorldTransform(0).GetRow3(2)
t.check("volumetric: the +Z of the sun points at it (altitude 40, azimuth 30 from -Z towards +X)",
        abs(axis[0] - 0.383) < 0.01 and abs(axis[1] - 0.643) < 0.01 and abs(axis[2] + 0.663) < 0.01, tuple(axis))
build(sky_mode=1, enable_clouds=True, cloud_type=1)
t.check("2D clouds are not built with the Volumetric Atmosphere (it hides them and the dome whitens it), the Log says so",
        stage.node("cloud_layer_2d") is None and any("2D clouds are not drawn" in l for l in logs))
build(sky_mode=1, enable_clouds=True, cloud_type=0)
t.check("3D clouds are built with the Volumetric Atmosphere", stage.node("cloud_geo") is not None and stage.node("sky_sun") is not None)
build(sky_mode=0)
t.check("back to the basic projection: the Physical Sky node returns, the atmosphere and the sun go", stage.node("physical_sky") is not None and stage.node("sky_sun") is None and stage.node("sky_atmosphere") is None)
build(sky_mode=1)
t.check("and again: no Physical Sky node left", stage.node("physical_sky") is None and stage.node("sky_sun") is not None)
t.check("daytime volumetric atmosphere gives no night warning", not [l for l in logs if "below the horizon" in l], logs)
build(engine="cpu", sky_mode=1, sky_elev=-10)
t.check("volumetric atmosphere with the sun below the horizon says it is dark", any("below the horizon" in l for l in logs), logs)
build(engine="cpu", sky_mode=0, sky_elev=-10)
t.check("no such warning for the basic projection sky", not [l for l in logs if "below the horizon" in l], logs)

# every optional layer on at once: moon, stars, fog, 3D clouds, composite: each setter must find its parameter on this version
build(enable_fog=True, enable_clouds=True, cloud_type=0, moon_enable=True, stars_enable=True, sky_plate=False, sky_elev=-20)
t.check("moon, stars, fog and clouds together report no ignored setting", not [l for l in logs if "not applied" in l], logs)

# the report itself: a parameter that does not exist is named in one [WARN] line
from bsm_karma.nodeutil import _pset, _set_first_existing_parm, ignored_report, ignored_reset
ignored_reset()
probe = stage.node("karma_settings")
_pset(probe, "no_such_parm_x", 1, logs.append, quiet=True)
_set_first_existing_parm(probe, ("no_such_a", "no_such_b"), 1, logs.append)
_set_first_existing_parm(probe, ("no_such_c",), 1, logs.append, note=False)
logs.clear()
ignored_report(logs.append)
t.check("ignored settings are named in one WARN line", len(logs) == 1 and "no_such_parm_x" in logs[0] and "no_such_a|no_such_b" in logs[0] and "no_such_c" not in logs[0], logs)
ignored_reset()
logs.clear()
ignored_report(logs.append)
t.check("nothing ignored, nothing said", not logs, logs)

t.done()
