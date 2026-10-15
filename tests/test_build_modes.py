# Builds every scene mode and checks the settings reached the nodes.
#
# On H22 many parameter names the tool guessed did not exist, and the quiet setters hid it.
#
# Revision : 10-10-2026 | Auteur : BSM
from _common import Checker, base_config, load_tool, scratch_dir

hou, k = load_tool()
t = Checker("build modes")
out_dir = scratch_dir("build_modes")
stage = hou.node("/stage")
logs = []


#------------------------------------------------------------
def build(**over):
    logs.clear()
    k.setup_karma_environment(dict(base_config(out_dir), **over), logs.append)


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
