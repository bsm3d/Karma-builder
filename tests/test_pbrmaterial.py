# The PBR material: the spec and its file, the graph written for each map, the texture set found by names, and the checks
# on what comes from outside. MaterialX validates every document when this Python has the module.
#
# Revision : 16-10-2026 | Auteur : BSM
import os
import shutil
import tempfile
from xml.etree import ElementTree
from _common import Checker, load_tool

hou, k = load_tool()
import bsm_karma.pbrmaterial as pbr

t = Checker("pbr material")
work = tempfile.mkdtemp(prefix="bsm_pbr_")

TEXTURES = work + "/tex"
os.makedirs(TEXTURES)
for name in ("Wood_Color.png", "Wood_Roughness.png", "Wood_NormalGL.png", "Wood_AmbientOcclusion.png", "Wood_Displacement.png", "Wood_Metalness.png", "notes.txt", "Wood_Color.png.bak"):
    open(TEXTURES + "/" + name, "wb").write(b"x")
ALL = {slot: "{}/{}".format(TEXTURES, name) for slot, name in (("base_color", "Wood_Color.png"), ("roughness", "Wood_Roughness.png"), ("metalness", "Wood_Metalness.png"),
                                                                ("normal", "Wood_NormalGL.png"), ("ao", "Wood_AmbientOcclusion.png"), ("height", "Wood_Displacement.png"),
                                                                ("emission", "e.png"), ("opacity", "o.png"))}


def nodes_of(text):
    root = ElementTree.fromstring(text)
    return root, {e.get("name"): e for e in root if e.get("name")}


# --- the default material
default = pbr.default_spec("PBR")
text = pbr.build_pbr_mtlx(default)
root, named = nodes_of(text)
surface = [e for e in root if e.tag == "standard_surface"][0]
t.check("the default material is a standard surface and its material", surface.get("name") == "SR_PBR" and "PBR" in named and not [e for e in root if e.tag == "tiledimage"])
t.check("the spec is kept in a comment and read back as it was", pbr.read_pbr_spec(text) == pbr.normalize_spec(default))
t.check("another file is not a PBR file", pbr.read_pbr_spec('<?xml version="1.0"?><materialx version="1.38"/>') is None and pbr.read_pbr_spec("<!-- bsm_karma_pbr !!!! -->") is None)

# --- one tiledimage per map, with the right color spaces and connections
spec = pbr.normalize_spec({"name": "Wood", "maps": ALL, "options": {"normal_format": "DirectX", "gloss": True, "ao_strength": 0.5, "tiling": 2.0, "rotation": 30.0,
                                                                     "offset": (0.1, 0.2), "tint": (0.5, 1.0, 1.0), "rough_scale": 0.5, "normal_strength": 2.0, "disp_scale": 0.05}})
text = pbr.build_pbr_mtlx(spec)
root, named = nodes_of(text)
images = {e.get("name"): e for e in root if e.tag == "tiledimage"}
t.check("a tiledimage for each of the eight maps", sorted(images) == sorted("T_" + s for s in pbr.SLOT_NAMES), sorted(images))
colorspaces = {n: [i.get("colorspace") for i in e if i.get("name") == "file"][0] for n, e in images.items()}
t.check("only the color maps are sRGB", {n for n, c in colorspaces.items() if c == "srgb_texture"} == {"T_base_color", "T_emission"}, colorspaces)
t.check("tiling, offset and rotation reach every image", all({i.get("name") for i in e} >= {"uvtiling", "uvoffset", "texcoord"} for e in images.values()))
t.check("DirectX: the green channel is flipped before the normal map", all(n in named for n in ("N_split", "N_green", "N_flipped", "N_map")) and named["N_map"].tag == "normalmap")
t.check("glossiness is inverted, then scaled", "R_invert" in named and "R_scale" in named)
t.check("displacement goes through the mid value and the scale", "D_mid" in named and "D_shader" in named)
spec_back = pbr.read_pbr_spec(text)
t.check("the comment holds the spec as given, not the tinted constants", spec_back["options"]["tint"] == (0.5, 1.0, 1.0) and spec_back["options"]["rough_scale"] == 0.5)
text_gl = pbr.build_pbr_mtlx(pbr.normalize_spec({"maps": {"normal": ALL["normal"]}}))
t.check("OpenGL normals have no flip", "N_split" not in text_gl and "N_map" in text_gl)
bare = pbr.build_pbr_mtlx(pbr.normalize_spec({"name": "Bare", "values": {"base_color": (0.5, 0.5, 0.5), "specular_roughness": 0.6}, "options": {"tint": (0.5, 0.5, 0.5), "rough_scale": 0.5}}))
_root, _named = nodes_of(bare)
_surface = [e for e in _root if e.tag == "standard_surface"][0]
_values = {i.get("name"): i.get("value") for i in _surface}
t.check("with no map, tint and scales change the constants", _values["base_color"].startswith("0.25") and _values["specular_roughness"].startswith("0.3"), _values)

# --- the files
folder = work + "/files"
os.makedirs(folder)
base = pbr.write_pbr_file(spec, folder, base=True)
variant = pbr.write_pbr_file(spec, folder)
t.check("the base file has the name of the material, an edit a hashed name", os.path.basename(base) == "Wood.mtlx" and os.path.basename(variant).startswith("Wood.bsm_") and variant != base)
stamp = os.path.getmtime(variant)
t.check("the same spec gives the same file", pbr.write_pbr_file(spec, folder) == variant and os.path.getmtime(variant) == stamp)
t.check("another spec gives another file", pbr.write_pbr_file(dict(spec, options=dict(spec["options"], rotation=40.0)), folder) != variant)

# --- the texture set
found = pbr.guess_maps(TEXTURES)
t.check("a texture set is read by the names of its files", {s: os.path.basename(p) for s, p in found.items()} == {
    "base_color": "Wood_Color.png", "roughness": "Wood_Roughness.png", "metalness": "Wood_Metalness.png", "normal": "Wood_NormalGL.png",
    "ao": "Wood_AmbientOcclusion.png", "height": "Wood_Displacement.png"}, found)
other = work + "/poly"
os.makedirs(other)
for name in ("brick_diff_2k.jpg", "brick_rough_2k.jpg", "brick_nor_gl_2k.exr", "brick_disp_2k.png", "brick_ao_2k.jpg", "brick_arm_2k.jpg"):
    open(other + "/" + name, "wb").write(b"x")
poly = {s: os.path.basename(p) for s, p in pbr.guess_maps(other).items()}
t.check("Poly Haven names are found too", poly.get("base_color") == "brick_diff_2k.jpg" and poly.get("roughness") == "brick_rough_2k.jpg" and poly.get("normal") == "brick_nor_gl_2k.exr"
        and poly.get("height") == "brick_disp_2k.png" and poly.get("ao") == "brick_ao_2k.jpg", poly)
t.check("a folder that does not exist gives nothing", pbr.guess_maps(work + "/nowhere") == {})

# --- what comes from outside
hostile = pbr.normalize_spec({"name": "x y/../z", "values": {"nope": 1, "base": "abc", "base_color": [1, 2], "specular_roughness": 99},
                              "maps": {"base_color": "`system('x')`.png", "roughness": "relative/r.png", "normal": "/tmp/n.txt", "ao": "/tmp/a.png", "bogus": "/tmp/b.png",
                                       "height": 5, "metalness": "/tmp/m`.png"},
                              "options": {"tiling": 1e9, "rotation": "x", "offset": (1,), "tint": "no", "normal_format": "Mac", "ao_strength": -3}})
t.check("a hostile spec keeps only plain absolute image paths", hostile["maps"] == {"ao": "/tmp/a.png"}, hostile["maps"])
t.check("unknown inputs go, numbers are bounded", "nope" not in hostile["values"] and hostile["values"]["specular_roughness"] <= 1000.0 and hostile["values"]["base_color"] == (0.8, 0.8, 0.8), hostile["values"])
t.check("options are bounded or default", hostile["options"]["tiling"] <= 1000.0 and hostile["options"]["rotation"] == 0.0 and hostile["options"]["offset"] == (0.0, 0.0)
        and hostile["options"]["tint"] == (1.0, 1.0, 1.0) and hostile["options"]["normal_format"] == "OpenGL" and hostile["options"]["ao_strength"] == 0.0, hostile["options"])
t.check("the name is a safe name", hostile["name"].replace("_", "").isalnum(), hostile["name"])
t.check("a damaged comment is not a spec", pbr.read_pbr_spec("<!-- bsm_karma_pbr AAAA -->") is None)

# --- MaterialX
try:
    import MaterialX as mx
except ImportError:
    mx = None
    print("note: no MaterialX Python module here, the documents are not validated by MaterialX")
if mx is not None:
    libraries = mx.createDocument()
    mx.loadLibraries(mx.getDefaultDataFolders() if hasattr(mx, "getDefaultDataFolders") else mx.getDefaultDataLibraryFolders(), mx.getDefaultDataSearchPath(), libraries)

    def valid(text):
        document = mx.createDocument()
        document.importLibrary(libraries)
        path = work + "/validate.mtlx"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        mx.readFromXmlFile(document, path)
        return document.validate()
    cases = {
        "default": default,
        "all maps": spec,
        "all maps, OpenGL": dict(spec, options=dict(spec["options"], normal_format="OpenGL", gloss=False, rotation=0.0, tiling=1.0, offset=(0.0, 0.0))),
        "ao only": {"name": "AO", "maps": {"ao": ALL["ao"]}, "options": {"ao_strength": 0.5, "tint": (0.9, 0.9, 0.9)}},
        "normal only, DirectX": {"name": "N", "maps": {"normal": ALL["normal"]}, "options": {"normal_format": "DirectX"}},
        "height only": {"name": "H", "maps": {"height": ALL["height"]}},
        "constants only": {"name": "C", "values": {"metalness": 1.0, "coat": 1.0, "subsurface": 0.5, "base_color": (1.0, 0.7, 0.3)}},
        "emission and opacity": {"name": "E", "maps": {"emission": ALL["emission"], "opacity": ALL["opacity"]}},
    }
    for label, case in cases.items():
        ok, why = valid(pbr.build_pbr_mtlx(case))
        t.check("MaterialX validates the PBR material: " + label, ok, why[:200])

shutil.rmtree(work, ignore_errors=True)
t.done()
