# Builds every scene mode and checks the settings reached the nodes.
#
# On H22 many parameter names the tool guessed did not exist, and the quiet setters hid it.
#
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


# --------------------------------------------------
def val(node_name, parm):
    node = stage.node(node_name)
    p = node.parm(parm) if node else None
    return p.eval() if p is not None else "<missing>"


for mode, env in (("Environment", "Physical Sky"), ("Environment", "HDRI Image"), ("Studio", "HDRI Image"),
                  ("3 Points", "HDRI Image"), ("Interior", "Physical Sky")):
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

# --- 2D clouds: a second dome light with a generated picture ---
build(enable_clouds=True, cloud_type=1, cloud2d_brightness=0.8, sky_int=2.0)
layer = stage.node("cloud_layer_2d")
t.check("2D clouds: a dome light node", layer is not None and layer.type().name() == "domelight")
t.check("2D clouds: merged with the sky", layer in stage.node("env_merge").inputs(), [n.name() for n in stage.node("env_merge").inputs()])
t.check("2D clouds: no volume nodes left", all(stage.node(n) is None for n in ("cloud_geo", "cloud_xform", "quickcloudmaterial", "assign_cloud_shader")))
t.check("2D clouds: no warning", not [l for l in logs if "WARN" in l], [l for l in logs if "WARN" in l])
cloud_stage = stage.node("karma_settings").stage()
cloud_prims = [p for p in cloud_stage.Traverse() if p.GetName() == "cloud_layer_2d"]
texture = cloud_prims[0].GetAttribute("inputs:texture:file").Get() if cloud_prims else None
texture_path = str(texture.path) if texture is not None and hasattr(texture, "path") else str(texture)
t.check("2D clouds: the light reads a generated picture", bool(cloud_prims) and "bsm_clouds_" in texture_path, texture_path)
t.check("2D clouds: the picture exists", os.path.isfile(texture_path.replace("\\", "/")), texture_path)
t.check("2D clouds: intensity is the brightness times the sky intensity", abs(float(cloud_prims[0].GetAttribute("inputs:intensity").Get()) - 1.6) < 1e-6 if cloud_prims else False)
t.check("2D clouds: the picture is an EXR", texture_path.lower().endswith(".exr"), texture_path)
sky_parm = next((n for n in ("sky_intensity", "skyintensity") if stage.node("physical_sky").parm(n) is not None), None)
t.check("2D clouds: the sky is not made brighter (that is for volumes)", sky_parm is not None and abs(val("physical_sky", sky_parm) - 2.0) < 1e-6, (sky_parm, val("physical_sky", sky_parm) if sky_parm else None))
build(enable_clouds=True, cloud_type=0, sky_int=2.0)
t.check("3D clouds: the sky is brighter to compensate the volume", sky_parm is not None and abs(val("physical_sky", sky_parm) - 8.0) < 1e-6, val("physical_sky", sky_parm) if sky_parm else None)
build(enable_clouds=True, cloud_type=1, cloud2d_brightness=0.8, sky_int=2.0)
build(enable_clouds=True, cloud_type=0)
t.check("back to 3D clouds: the 2D layer is removed, the volume is back", stage.node("cloud_layer_2d") is None and stage.node("cloud_geo") is not None)
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
build(scene_mode="Interior", env_type="Physical Sky", lamp_key_temp=3000)
window = lamp_rgb("window_portal")
t.check("Interior: the window light takes the key color", window[0] > window[2], window)
t.check("lamp colors: no warning", not [l for l in logs if "WARN" in l], [l for l in logs if "WARN" in l])

# --- cloud animation: the wind moves the 3D clouds and the drift turns the 2D ones, with the time
build(enable_clouds=True, cloud_type=0, cloud_wind_speed=10.0, cloud_wind_dir=90.0)
xform = stage.node("cloud_xform")
tx, tz = xform.parm("tx"), xform.parm("tz")
t.check("3D clouds: the wind is an expression of the time", "$T" in tx.expression() and "$T" in tz.expression(), (tx.expression() if tx.keyframes() else None))
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
t.check("2D clouds: 30 degrees per minute turn the dome 30 degrees in a minute", abs((b - a) - 30.0) < 1e-3, (a, b))
build(enable_clouds=True, cloud_type=1, cloud2d_drift=0.0)
t.check("2D clouds: no drift, no animation", not stage.node("cloud_layer_2d").parm("ry").keyframes())
hou.setFrame(1)
build(enable_clouds=False)

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
t.check("rayleigh scale", abs(val("physical_sky", "rayleighscale") - 6e-05) < 1e-12, val("physical_sky", "rayleighscale"))
t.check("mie scale", abs(val("physical_sky", "miescatterscale") - 1.5e-05) < 1e-12, val("physical_sky", "miescatterscale"))
t.check("sun link uses USD prim paths",
        val("sky_atmosphere_linker", "link_prim_1") == "/lights/physical_sky/sun"
        and val("sky_atmosphere_linker", "link_includes_1") == "/lights/physical_sky/atmosphere",
        (val("sky_atmosphere_linker", "link_prim_1"), val("sky_atmosphere_linker", "link_includes_1")))
t.check("link type", val("sky_atmosphere_linker", "link_type_1") == "light")
t.check("daytime volumetric atmosphere gives no night warning", not [l for l in logs if "below the horizon" in l], logs)
build(engine="cpu", sky_mode=1, sky_elev=-10)
t.check("volumetric atmosphere with the sun below the horizon says it is dark", any("below the horizon" in l for l in logs), logs)
build(engine="cpu", sky_mode=0, sky_elev=-10)
t.check("no such warning for the basic projection sky", not [l for l in logs if "below the horizon" in l], logs)

t.done()
