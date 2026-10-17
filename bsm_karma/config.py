# Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Constants shared by the whole tool
# Houdini : 21 and 22 (plain Python, also runs without Houdini)
# Version : 1.0.0

import re

SCRIPT_VERSION = "1.0.0"


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
    "cloud_layer_2d": {"domelight"},
    "quickcloudmaterial": {"editmaterialproperties"},
    "env_merge": {"merge"},
    "mtlx_materials": {"materiallibrary"},
    "material_edit": {"editmaterial"},
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
    "material_edit",
    "material_linker",
    "mtlx_materials",
    "geo_merge",
    "env_merge",
    "atmosphere_fog",
    "cloud_geo",
    "cloud_layer_2d",
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


# pixels between a label and its field in the tab forms
FORM_LABEL_GAP = 14


# least room between two widgets of a row, and between two rows stacked in a column (the Houdini style can use less)
ROW_GAP = 8
COLUMN_GAP = 4


# Settings that add, remove or rewire nodes, or switch the render engine. A running Karma viewport restarts on
# these and can freeze Houdini for minutes, so Live Update leaves them to the Build button.
LIVE_STRUCTURE_KEYS = ("scene_mode", "env_type", "sky_mode", "enable_fog", "enable_clouds", "cloud_type", "enable_aovs",
                       "engine", "camera_choice", "geo_source", "cloud_material_path")


# cloud types of the Atmosphere tab: a volume (slow, lit, parallax) or a 2D layer on a second dome light (fast)
CLOUD_TYPES = ["3D Volume (slow, realistic)", "2D Layer (fast, backdrop)"]
CLOUD2D_BRIGHTNESS = 1.5


# The Volumetric Atmosphere is a shell about a hundred kilometres thick: a camera that does not see that far shows black.
# At the horizon the ray to the top of the atmosphere is about 1,130 km long (scene units are metres).
ATMOSPHERE_FAR_CLIP = 2000000.0
CLOUD_LAYER_NAME = "cloud_layer_2d"


# Edit Material LOP: edits an existing USD material as a VOP network. Read on H22.0.466: a multiparm 'materials'
# whose first entry is enable1, matpath1 (the material), load1 (button) and matnode1. The tool always uses entry 1.
MATERIAL_EDIT_NODE = "material_edit"
MATERIAL_EDIT_TYPE = "editmaterial"
MATERIAL_EDIT_COUNT_PARM = "materials"
MATERIAL_EDIT_ENABLE_PARM = "enable1"
MATERIAL_EDIT_PATH_PARM = "matpath1"
MATERIAL_EDIT_LOAD_PARM = "load1"


# list and category views of the catalog: rows read from the gallery model, never more than this
MATERIAL_VIEW_LIMIT = 20000
MATERIAL_VIEW_DEPTH = 8


# viewport picking: Houdini pixel coordinates start at the lower left, Qt at the upper left
VIEWPORT_PICK_FLIP_Y = True


_PRIM_PATH_RE = re.compile(r"^/[A-Za-z0-9_/]*$")
