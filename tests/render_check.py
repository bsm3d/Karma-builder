# Manual render check, not part of run_tests.ps1: hython tests/render_check.py [cpu|xpu] [output.png]
#
# Renders a small sky and clouds scene with the tool and prints the time and the image path.
#
# Revision : 10-10-2026 | Auteur : BSM
import os
import sys
import time
from _common import base_config, load_tool, scratch_dir

hou, k = load_tool()
engine = sys.argv[1] if len(sys.argv) > 1 else "cpu"
out = (sys.argv[2] if len(sys.argv) > 2 else os.path.join(scratch_dir("render_check"), "clouds_{}.png".format(engine))).replace("\\", "/")
if os.path.exists(out):
    os.remove(out)

stage = hou.node("/stage")
cam = stage.createNode("camera", "look_up")
cam.parm("ty").set(2.0)
cam.parm("rx").set(32.0)
sphere = stage.createNode("sphere", "ball")
sphere.parm("ty").set(1.0)
geo = stage.createNode("merge", "geo")
geo.setInput(0, sphere)

cfg = dict(
    base_config(scratch_dir("render_check")), scene_mode="Environment", env_type="Physical Sky", engine=engine,
    res_x=960, res_y=540, samples=48, camera_choice=cam.path(), geo_source=geo.path(), enable_aovs=False,
    enable_clouds=True, cloud_density=0.2, cloud_altitude=140, cloud_scale=180, cloud_precision=5, cloud_clip=0.35,
    sky_elev=40, sky_azim=30, sky_sun_int=3.0, output_format="PNG", out_path=out,
)
logs = []
k.setup_karma_environment(cfg, logs.append)
print("warnings:", [l for l in logs if "WARN" in l])

start = time.time()
try:
    stage.node("render_to_disk").render()
except hou.OperationFailed as exc:
    print("RENDER FAILED:", exc)
print("engine={} seconds={:.1f} exists={} kb={}".format(engine, time.time() - start, os.path.exists(out),
                                                        os.path.getsize(out) // 1024 if os.path.exists(out) else 0))
print("IMAGE", out)
