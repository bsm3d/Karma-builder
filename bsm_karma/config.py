# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Constants shared by the whole Karma Builder tool: script version, HDRI and sky data names, and the node type maps.

# Houdini : 21 and 22 (plain Python, also runs without Houdini)

import re

SCRIPT_VERSION = "1.6.0"

# the HDRI pictures that travel with the tool (datas/ next to the package, a section of each in the HDA)
DATAS_HDRIS = ("DaySkyHDRI071B_4K_HDR.exr",)
DATAS_SECTION_PREFIX = "datas_"
# datas/Sky: the moon map (and later the star pictures); only the small ones travel in the HDA, as Sky_<name>
SKY_DATAS_PREFIX = "Sky_"
SKY_DATAS_EMBEDDED = ("moon.jpg", "stars.npz", "milky_way_1k.exr")

TOOL_NODE_TAG_KEY = "bsm_karma_managed"

TOOL_NODE_TAG_VALUE = "1"

TOOL_STAGE_NODE_TYPES = {
    "render_cam": {"camera"},
    "physical_sky": {"karmaphysicalsky"},
    "sky_atmosphere": {"karmaskyatmosphere"},
    "sky_sun": {"light"},
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
    "cloud_layer_2d": {"sopcreate"},
    "cloud_layer_2d_ref": {"reference"},
    "cloud_layer_2d_mat": {"assignmaterial"},
    "sky_milky": {"sopcreate"},
    "sky_stars_ref": {"reference"},
    "sky_stars_mtl": {"reference"},
    "sky_stars_mat": {"assignmaterial"},
    "sky_moon": {"light"},
    "sky_moon_disc": {"sopcreate"},
    "sky_moon_halo": {"sopcreate"},
    "sky_moon_ref": {"reference"},
    "sky_moon_mat": {"assignmaterial"},
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
    "sky_stars_mat",
    "sky_stars_mtl",
    "sky_stars_ref",
    "sky_milky",
    "sky_moon_mat",
    "sky_moon_ref",
    "sky_moon_halo",
    "sky_moon_disc",
    "sky_moon",
    "cloud_layer_2d_mat",
    "cloud_layer_2d_ref",
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
    "sky_atmosphere",
    "sky_sun",
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
LABEL_COLUMN_MAX = 140

# least room between two widgets of a row, and between two rows stacked in a column (the Houdini style can use less)
ROW_GAP = 8
COLUMN_GAP = 4

# Settings that add, remove or rewire nodes, or switch the render engine. A running Karma viewport restarts on
# these and can freeze Houdini for minutes, so Live Update leaves them to the Build button.
LIVE_STRUCTURE_KEYS = ("scene_mode", "env_type", "sky_mode", "enable_fog", "enable_clouds", "cloud_type", "enable_aovs",
                       "engine", "camera_choice", "geo_source", "cloud_material_path", "moon_active", "stars_active", "stars_milky", "sky_plate")

# Among those, what Live Update builds by itself: the moon and the stars come and go with the sun (a sky preset, Solar Altitude, the
# date), a few light nodes, so waiting for the Build button for them made a night preset look broken.
LIVE_AUTO_KEYS = ("moon_active", "stars_active", "stars_milky")

# cloud types of the Atmosphere tab: a volume (slow, lit, parallax) or a 2D layer on a second dome light (fast)
CLOUD_TYPES = ["3D Volume (slow, realistic)", "2D Layer (fast, backdrop)"]
CLOUD2D_BRIGHTNESS = 1.5

# The Volumetric Atmosphere is a shell about a hundred kilometres thick: a camera that does not see that far shows black.
# At the horizon the ray to the top of the atmosphere is about 1,130 km long (scene units are metres).
ATMOSPHERE_FAR_CLIP = 2000000.0
CLOUD_LAYER_NAME = "cloud_layer_2d"
CLOUD_LAYER_PRIM = "/World/Environment/CloudLayer"
CLOUD_LAYER_MATERIAL = "/World/Environment/CloudLayerMaterial"
# the sky spheres (clouds, moon, stars, Milky Way) are far, as the sky is: 70 to 150 km, beyond any scene and any view of the viewport,
# inside the default far clipping range of a camera (1,000 km). A near sphere hid the geometry seen from outside.
CLOUD2D_RADIUS = 70000.0
# the moon: a lit sphere and a halo behind the clouds (a distant light has no visible disc), and a distant light for its glow
MOON_PRIM = "/World/Environment/Moon"
MOON_MATERIALS = "/World/Environment/MoonMaterials"
# the halo of the moon is a sphere a little wider than the disc: it must sit between the clouds (70 km) and the stars (140 km), whole
MOON_DISTANCE = 84000.0

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
