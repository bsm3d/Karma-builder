# Shared setup for the headless tests, run with hython (tests/run_tests.ps1).
#
# hython has no hou.qt, which the tool reads: a stub stands in, so only the network and linker logic runs here.
# The dialog itself is covered by tests/gui.
#
# Revision : 10-10-2026 | Auteur : BSM
import os
import sys
import types
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


# ------------------------------------------------------------
def load_tool():
    sys.path.insert(0, ROOT)
    import hou
    if not hasattr(hou, "qt"):
        hou.qt = types.SimpleNamespace(mainWindow=lambda: None)
    import bsm_karma
    return hou, bsm_karma


# --------------------------------------------------------
# Collects PASS/FAIL lines and turns them into the process exit code.
class Checker:
    def __init__(self, name):
        self.name = name
        self.failures = []
        print("== {} ==".format(name))

    # ------------------------------------------------------------------------------------------
    def check(self, label, ok, detail=""):
        print(("PASS " if ok else "FAIL ") + label + ((" | " + str(detail)) if detail != "" else ""))
        if not ok:
            self.failures.append(label)

    def done(self):
        print("RESULT {}: {}".format(self.name, "ok" if not self.failures else "{} failure(s)".format(len(self.failures))))
        sys.exit(1 if self.failures else 0)


# ------------------------------------------------------------
def scratch_dir(name):
    path = os.path.join(tempfile.gettempdir(), "bsm_karma_tests", name)
    os.makedirs(path, exist_ok=True)
    return path.replace("\\", "/")


def base_config(out_dir):
    return dict(
        scene_mode="Environment", env_type="Physical Sky", engine="cpu", res_x=1280, res_y=720, samples=32,
        camera_choice="Create New Camera", new_cam_focal=50.0, new_cam_from_viewport=False, viewport_matrix=None,
        area_int=10.0, hdri_int=1.0, hdri_path="$HIP/x.exr", hdri_ev=0, hdri_rot=0, hdri_sat=1, hdri_temp=6500,
        hdri_tint=0,
        lamp_key_temp=6500, lamp_key_tint=0, lamp_fill_temp=6500, lamp_fill_tint=0, lamp_rim_temp=6500, lamp_rim_tint=0,
        enable_fog=False, fog_density=.25, fog_height=30, fog_radius=120, fog_phase=.4, fog_noise_scale=.1,
        fog_noise_amp=.5,
        enable_clouds=False, cloud_density=.2, cloud_altitude=140, cloud_scale=180, cloud_precision=5, cloud_clip=.35,
        cloud_material_path="", cloud_type=0, cloud2d_coverage=.45, cloud2d_softness=.4, cloud2d_scale=3.0,
        cloud2d_brightness=.6, cloud2d_seed=7,
        sky_mode=0, sky_elev=30, sky_azim=0, sky_sun_int=1, sky_sun_size=.53, sky_sun_temp=5500,
        sky_amb_r=1, sky_amb_g=1, sky_amb_b=1, sky_turbidity=3, sky_int=1, sky_hz_blur=5,
        sky_atm_rayleigh=1, sky_atm_mie=1,
        denoiser="None", pixel_filter="gauss", enable_ao=False, aov_ao=False, aov_depth=True, aov_normal=True,
        aov_position=False, aov_albedo=False, aov_emission=False, aov_diffuse=False, aov_specular=False,
        aov_motion=False, aov_shadow=False, aov_id=False,
        aov_multilayer=True, aov_half_precision=False, aov_use_custom_output=False, aov_output_path="",
        diffuse_limit=3, reflection_limit=3, transmission_limit=4, volume_limit=8, color_limit=10, noise_level=.01,
        enable_aovs=True, output_format="EXR", exr_precision="16-bit float", trange=0, f_start=1, f_end=1,
        out_path=out_dir + "/beauty.exr", geo_source="",
    )
