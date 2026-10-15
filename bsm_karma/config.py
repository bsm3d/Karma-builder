# config.py - BSM Karma Builder - constants shared by the whole tool
# Version : 2026.10.15.1 | Revision : 15-10-2026 | Auteur : BSM

import re

SCRIPT_VERSION = "2026.10.15.1"


TOOL_NODE_TAG_KEY = "bsm_karma_managed"


TOOL_NODE_TAG_VALUE = "1"


TOOL_STAGE_NODE_TYPES = {
    "render_cam": {"camera"},
    "physical_sky": {"karmaphysicalsky"},
    "sky_atmosphere_linker": {"lightlinker"},
    "env_hdri": {"domelight"},
    "studio_hdri": {"domelight"},
    "fill_hdri": {"domelight"},
    "dome_light": {"domelight"},
    "studio_key": {"light"},
    "key_light": {"light"},
    "fill_light": {"light"},
    "rim_light": {"light"},
    "window_portal": {"light"},
    "atmosphere_fog": {"karmafogbox"},
    "cloud_geo": {"sopcreate"},
    "quickcloudmaterial": {"editmaterialproperties"},
    "env_merge": {"merge"},
    "mtlx_materials": {"materiallibrary"},
    "material_linker": {"materiallinker"},
    "geo_merge": {"merge"},
    "standard_aovs": {"karmastandardrendervars"},
    "karma_settings": {"karmarendersettings"},
    "render_to_disk": {"usdrender_rop"},
}


TOOL_STAGE_DELETE_ORDER = [
    "render_to_disk",
    "karma_settings",
    "standard_aovs",
    "material_linker",
    "mtlx_materials",
    "geo_merge",
    "env_merge",
    "atmosphere_fog",
    "cloud_geo",
    "window_portal",
    "rim_light",
    "fill_light",
    "key_light",
    "studio_key",
    "dome_light",
    "fill_hdri",
    "studio_hdri",
    "env_hdri",
    "sky_atmosphere_linker",
    "physical_sky",
    "render_cam",
]


CAMERA_CREATE_LABEL = "Create New Camera"


USD_CAMERA_PREFIX = "usd:"


GENERATED_CAMERA_NAME = "render_cam"


DEFAULT_CLOUD_MATERIAL_PATH = "/World/Materials/KarmaCloud"


QUICK_CLOUD_NAME = "quickcloudmaterial"


# Data lives in two multiparms: files (enabled_#, createprims_#, primpath_#, filepath_#, filerefprimpath_#)
# and links (link_enabled_#, link_id_#, link_prim_# = the material, link_includes_# = its prims, one per line).
# Written directly, so SideFX's UI module stays out of it.

MATERIAL_LINK_TYPE = "materialdirect"


MATERIAL_DEFAULT_ROOT = "/materials"


AMD_LIBRARY_URL = "https://api.matlib.gpuopen.com/api"


CATALOG_SOURCE_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".usd", ".usda", ".usdc", ".usdz")


AMD_SOURCE_ID = "AMD MaterialX Library"


STAGE_TARGET_LIMIT = 5000


_PRIM_PATH_RE = re.compile(r"^/[A-Za-z0-9_/]*$")
