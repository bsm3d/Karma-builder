# Basic materials and the .mtlx editing of the material editor: the files written, the values changed, the textures kept,
# the variants, the checks. In Houdini the files are also opened with USD.
#
# Revision : 16-10-2026 | Auteur : BSM
import os
import shutil
import tempfile
from _common import Checker, load_tool

hou, k = load_tool()
import bsm_karma.basicmaterials as basic
import bsm_karma.mtlxedit as edit

t = Checker("material editor")
work = tempfile.mkdtemp(prefix="bsm_editor_")

TEXTURED = """<?xml version="1.0"?>
<materialx version="1.38">
  <!-- a textured material, shaped like the ambientCG ones -->
  <tiledimage name="Color_tex" type="color3"><input name="file" type="filename" value="Wood_Color.png" colorspace="srgb_texture" />
    <input name="uvtiling" type="vector2" value="2, 2" /></tiledimage>
  <tiledimage name="Rough_tex" type="float"><input name="file" type="filename" value="Wood_Roughness.png" />
    <input name="uvtiling" type="vector2" value="2, 2" /></tiledimage>
  <tiledimage name="Normal_tex" type="vector3"><input name="file" type="filename" value="Wood_NormalGL.png" /></tiledimage>
  <normalmap name="NM" type="vector3"><input name="in" type="vector3" nodename="Normal_tex" /><input name="scale" type="float" value="1" /></normalmap>
  <standard_surface name="SR_Wood" type="surfaceshader">
    <input name="base_color" type="color3" nodename="Color_tex" />
    <input name="specular_roughness" type="float" nodename="Rough_tex" />
    <input name="normal" type="vector3" nodename="NM" />
    <input name="metalness" type="float" value="0.2" />
  </standard_surface>
  <displacement name="Disp" type="displacementshader"><input name="displacement" type="float" value="0.1" /><input name="scale" type="float" value="1" /></displacement>
  <surfacematerial name="Wood" type="material">
    <input name="surfaceshader" type="surfaceshader" nodename="SR_Wood" />
    <input name="displacementshader" type="displacementshader" nodename="Disp" />
  </surfacematerial>
</materialx>
"""


# ------------------------------------------------------------
def inputs_of(text, tag="standard_surface"):
    root = edit.parse(text)
    node = next(root.iter(tag))
    return {e.get("name"): e for e in node.findall("input")}


# --- the basic materials
t.check("sixteen basic materials", len(basic.BASIC_MATERIALS) == 16, len(basic.BASIC_MATERIALS))
bad = [name for name, values in basic.BASIC_MATERIALS.items() for key in values if key not in basic.INPUT_TYPES]
t.check("each of them only uses inputs of the standard surface", not bad, bad)
folder = work + "/basic"
os.makedirs(folder)
for name in basic.BASIC_MATERIALS:
    path = basic.basic_material_file(name, folder)
    root = edit.parse(open(path, encoding="utf-8").read())
    material = next(root.iter("surfacematerial"))
    surface = edit.find_surface(root)
    ok = material.get("name") == basic.safe_name(name) and surface is not None and surface.get("name") == "SR_" + basic.safe_name(name)
    if not ok:
        t.check("{}: a material and its surface".format(name), False)
t.check("each basic material is a valid file with a material and a surface", True)
stamp = os.path.getmtime(basic.basic_material_file("Gold", folder))
t.check("the file of a material is not written again when it is there", os.path.getmtime(basic.basic_material_file("Gold", folder)) == stamp)
skin = inputs_of(open(basic.basic_material_file("Skin", folder), encoding="utf-8").read())
t.check("Skin has subsurface with a radius per channel", skin["subsurface"].get("value") == "0.65" and skin["subsurface_radius"].get("value") == "1, 0.35, 0.2", {k: v.get("value") for k, v in skin.items()})
glass = inputs_of(open(basic.basic_material_file("Glass", folder), encoding="utf-8").read())
t.check("Glass transmits", glass["transmission"].get("value") == "1" and glass["base"].get("value") == "0")
t.check("a default is not written", "specular_IOR" not in glass)
t.check("names are made safe", basic.safe_name("Car Paint") == "Car_Paint" and basic.safe_name("3d") == "M_3d" and basic.safe_name("../x") == "x" and basic.safe_name("") == "Material")

# --- describe
d = edit.describe(TEXTURED)
t.check("describe: surface, material and the textured inputs", d["surface"] == "SR_Wood" and d["material"] == "Wood" and d["inputs"]["base_color"]["kind"] == "connected"
        and d["inputs"]["specular_roughness"]["kind"] == "connected" and d["inputs"]["metalness"] == {"kind": "value", "value": 0.2}
        and d["inputs"]["subsurface"]["kind"] == "default", d["inputs"]["metalness"])
t.check("describe: normal map, displacement, tiling and files found", d["has_normal"] and d["has_displacement"] and d["has_tiling"] and d["has_files"] and d["textured"])
plain = edit.describe(open(basic.basic_material_file("Steel", folder), encoding="utf-8").read())
t.check("describe: a basic material has no texture", not plain["textured"] and not plain["has_files"] and plain["inputs"]["metalness"]["value"] == 1.0)
for text, why in (("<nope", "invalid XML"), ("<other/>", "not MaterialX"), ('<!DOCTYPE x [<!ENTITY a "b">]><materialx/>', "a DOCTYPE"), ("<materialx version='1.38'/>", "no surface")):
    try:
        edit.describe(text)
        raised = False
    except edit.MtlxError:
        raised = True
    t.check("describe refuses " + why, raised)

# --- apply_settings
out = edit.apply_settings(TEXTURED, {"values": {"subsurface": 0.5, "metalness": 0.9, "specular_IOR": 1.33, "thin_walled": True, "subsurface_color": (0.9, 0.3, 0.2)}})
i = inputs_of(out)
t.check("values are written with their type", i["subsurface"].get("value") == "0.5" and i["metalness"].get("value") == "0.9" and i["specular_IOR"].get("value") == "1.33"
        and i["thin_walled"].get("value") == "true" and i["subsurface_color"].get("type") == "color3" and i["subsurface_color"].get("value") == "0.9, 0.3, 0.2")
t.check("a texture that is not touched stays connected", i["base_color"].get("nodename") == "Color_tex" and i["normal"].get("nodename") == "NM")
t.check("the comment of the file is kept", "a textured material" in out)
out = edit.apply_settings(TEXTURED, {"values": {"base_color": (1, 0, 0)}})
i = inputs_of(out)
t.check("a value replaces a texture", i["base_color"].get("value") == "1, 0, 0" and i["base_color"].get("nodename") is None)
out = edit.apply_settings(TEXTURED, {"mods": {"tint": (1.0, 0.5, 0.25), "brightness": 2.0, "rough_scale": 0.5, "normal": 2.0, "disp": 3.0, "tiling": 2.0}})
root = edit.parse(out)
i = inputs_of(out)
mul = {n.get("name"): n for n in root.iter("multiply")}
t.check("a tint goes through a multiply node in front of the texture", i["base_color"].get("nodename") == "BSM_mul_base_color"
        and {e.get("name"): e for e in mul["BSM_mul_base_color"].findall("input")}["in1"].get("nodename") == "Color_tex"
        and {e.get("name"): e for e in mul["BSM_mul_base_color"].findall("input")}["in2"].get("value") == "2, 1, 0.5", i["base_color"].attrib)
t.check("the roughness is scaled the same way", i["specular_roughness"].get("nodename") == "BSM_mul_specular_roughness"
        and {e.get("name"): e for e in mul["BSM_mul_specular_roughness"].findall("input")}["in2"].get("value") == "0.5")
nm = {e.get("name"): e for e in root.find("normalmap").findall("input")}
t.check("normal strength, displacement scale and tiling are scaled", nm["scale"].get("value") == "2"
        and {e.get("name"): e for e in root.find("displacement").findall("input")}["scale"].get("value") == "3"
        and all({e.get("name"): e for e in n.findall("input")}["uvtiling"].get("value") in ("4, 4",) for n in root.iter("tiledimage") if n.get("name") != "Normal_tex"))
t.check("the normal map has a tiling of its own created", {e.get("name"): e for e in [n for n in root.iter("tiledimage") if n.get("name") == "Normal_tex"][0].findall("input")}["uvtiling"].get("value") == "2, 2")
t.check("the textures are still there", len(list(root.iter("tiledimage"))) == 3 and all(e.get("value") for n in root.iter("tiledimage") for e in n.findall("input") if e.get("name") == "file"))
t.check("no change asked: the same inputs", {n: e.attrib for n, e in inputs_of(edit.apply_settings(TEXTURED, {})).items()} == {n: e.attrib for n, e in inputs_of(TEXTURED).items()})
out = edit.apply_settings(open(basic.basic_material_file("Steel", folder), encoding="utf-8").read(), {"mods": {"tint": (0.5, 0.5, 0.5)}})
t.check("a constant color is not touched by a tint (the color control is for that)", "multiply" not in out)

# --- variants
src = work + "/dl/Wood"
os.makedirs(src)
open(src + "/Wood.mtlx", "w", encoding="utf-8").write(TEXTURED)
settings = {"values": {"subsurface": 0.4}, "mods": {"normal": 1.5}}
path = edit.write_variant(src + "/Wood.mtlx", settings)
t.check("the variant is written next to the original, with the hash in its name", os.path.dirname(path) == src and edit.VARIANT_RE.match(os.path.basename(path)), path)
t.check("the same settings give the same file", edit.write_variant(src + "/Wood.mtlx", settings) == path)
t.check("other settings give another file", edit.write_variant(src + "/Wood.mtlx", {"values": {"subsurface": 0.9}}) != path)
original, restored = edit.original_and_settings(path)
t.check("the variant knows its original and its settings", original == src + "/Wood.mtlx" and restored == settings, (original, restored))
t.check("a file the tool did not write is its own original", edit.original_and_settings(src + "/Wood.mtlx") == (src + "/Wood.mtlx", {}))
t.check("the variant is a valid file with the same material", edit.describe(open(path, encoding="utf-8").read())["material"] == "Wood")
kept_before, edit.VARIANTS_KEPT = edit.VARIANTS_KEPT, 3
made = [edit.write_variant(src + "/Wood.mtlx", {"values": {"subsurface": 0.01 * n + 0.01}}) for n in range(8)]
for number, old in enumerate(made[:5]):
    os.utime(old, (1_000_000_000 + number, 1_000_000_000 + number))
recent = made[5]
edit.write_variant(src + "/Wood.mtlx", {"values": {"subsurface": 0.5}})
left = [n for n in os.listdir(src) if edit.VARIANT_RE.match(n)]
t.check("copies beyond the newest ones and weeks old are removed", not any(os.path.basename(old) in left for old in made[:5]), left)
t.check("recent copies are kept, a scene saved earlier may use them", os.path.basename(recent) in left and os.path.basename(made[7]) in left, left)
edit.VARIANTS_KEPT = kept_before
t.check("by default fifty copies are kept", edit.VARIANTS_KEPT == 50 and edit.VARIANT_MIN_AGE_DAYS == 14)
t.check("the original is never removed or changed", open(src + "/Wood.mtlx", encoding="utf-8").read() == TEXTURED)
forged = src + "/Forged.bsm_00000000.mtlx"
open(forged, "w", encoding="utf-8").write('<?xml version="1.0"?>\n<!-- bsm_karma ' + edit._encode("../../etc/passwd", {}) + ' -->\n<materialx version="1.38"/>')
t.check("a variant that names another folder as its original is not followed", edit.original_and_settings(forged) == (forged, {}))

# --- save under a name
mine = work + "/mine"
os.makedirs(mine)
saved = edit.write_named(basic.basic_material_file("Skin", folder), {"values": {"subsurface": 0.9}}, "Face Skin!", mine)
described = edit.describe(open(saved, encoding="utf-8").read())
t.check("a named copy has the new name for its material and surface", saved == mine + "/Face_Skin.mtlx" and described["material"] == "Face_Skin" and described["surface"] == "SR_Face_Skin"
        and described["inputs"]["subsurface"]["value"] == 0.9, described["material"])

try:
    edit.write_named(src + "/Wood.mtlx", {}, "Wood", src)
    refused = False
except edit.MtlxError:
    refused = True
t.check("a name that is the file being edited is refused: the original is not overwritten", refused and open(src + "/Wood.mtlx", encoding="utf-8").read() == TEXTURED)
many = {"values": {key: (0.123456, 0.234567, 0.345678) if basic.INPUT_TYPES[key] == "color3" else 0.5 for key in basic.INPUT_TYPES if basic.INPUT_TYPES[key] != "boolean"},
        "mods": {"tint": (0.9, 0.8, 0.7), "brightness": 1.1, "rough_scale": 0.9, "normal": 1.2, "disp": 1.3, "tiling": 1.4}}
big = edit.write_variant(src + "/Wood.mtlx", many)
t.check("a variant with every setting still tells its original and settings", edit.original_and_settings(big)[0] == src + "/Wood.mtlx" and len(edit.original_and_settings(big)[1]["values"]) == len(many["values"]))

# --- random materials
import colorsys
import bsm_karma.randommaterials as rnd
kind, values = rnd.random_values(3, "Plastic")
t.check("random: the same seed and ranges give the same material", rnd.random_values(3, "Plastic") == (kind, values) and rnd.random_values(4, "Plastic")[1] != values)
t.check("random: another kind is another finish", rnd.random_values(3, "Metal")[1]["metalness"] == 1.0 and rnd.random_values(3, "Matte")[1]["specular_roughness"] >= 0.65
        and rnd.random_values(3, "Paint")[1]["coat"] == 1.0)
kinds = {rnd.random_values(n, "Any")[0] for n in range(60)}
t.check("random: Any draws every kind", kinds == set(rnd.KINDS[1:]), kinds)
ranges = {"hue_from": 100.0, "hue_to": 140.0, "sat_min": 0.5, "sat_max": 0.6, "val_min": 0.7, "val_max": 0.8}
off = 0
for n in range(200):
    color = rnd.random_values(n, "Plastic", ranges)[1]["base_color"]
    shown = [rnd.srgb_to_linear.__globals__["colorsys"].rgb_to_hsv(*[(c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055) for c in color])][0]
    if not (100.0 - 1 <= shown[0] * 360.0 <= 140.0 + 1 and 0.5 - 0.01 <= shown[1] <= 0.6 + 0.01 and 0.7 - 0.01 <= shown[2] <= 0.8 + 0.01):
        off += 1
t.check("random: the colors stay inside the hue, saturation and brightness ranges", off == 0, off)
wrap = {"hue_from": 300.0, "hue_to": 60.0}
hues = [colorsys.rgb_to_hsv(*[(c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055) for c in rnd.random_values(n, "Plastic", wrap)[1]["base_color"]])[0] * 360 for n in range(100)]
t.check("random: a hue range from 300 to 60 goes through red", all(h >= 299 or h <= 61 for h in hues) and any(h > 300 for h in hues) and any(h < 60 for h in hues))
t.check("random: a metal is never a dark or loud color", all(max(rnd.random_values(n, "Metal")[1]["base_color"]) > 0.3 for n in range(50)))
t.check("random: strange ranges are tidied", rnd.random_values(1, "Plastic", {"sat_min": 2.0, "sat_max": -1.0, "hue_from": 999})[1]["base_color"] is not None)
folder = work + "/random"
os.makedirs(folder)
first = rnd.random_material_file(3, "Plastic", None, folder)
t.check("random: a file with a safe name and a material of that name", edit.describe(open(first, encoding="utf-8").read())["material"] == os.path.splitext(os.path.basename(first))[0] and basic.safe_name(os.path.basename(first)[:-5]) == os.path.basename(first)[:-5])
stamp = os.path.getmtime(first)
t.check("random: the same settings reuse the file", rnd.random_material_file(3, "Plastic", None, folder) == first and os.path.getmtime(first) == stamp)
t.check("random: other ranges give another file", rnd.random_material_file(3, "Plastic", {"hue_from": 10.0}, folder) != first)

# --- Houdini: USD reads the files
usd_reads_mtlx = False
try:
    from pxr import Sdf, Usd, UsdShade
    usd_reads_mtlx = Sdf.FileFormat.FindByExtension("mtlx") is not None
    if not usd_reads_mtlx:
        print("note: this USD has no MaterialX file format plugin, the files are not opened with USD here")
except ImportError:
    pass
if usd_reads_mtlx:
    for label, file in (("a basic material", basic.basic_material_file("Skin", folder)), ("an edited textured material", path), ("a named copy", saved)):
        stage = Usd.Stage.Open(file)
        materials = [p for p in stage.Traverse() if p.IsA(UsdShade.Material)] if stage else []
        t.check("USD opens {} and finds its material".format(label), len(materials) == 1, [str(p.GetPath()) for p in materials])
# --- the MaterialX library, when this Python has it: the inputs of the table and the documents written are checked by it
try:
    import MaterialX as mx
except ImportError:
    mx = None
    print("note: no MaterialX Python module here, the documents are not validated by MaterialX")
if mx is not None:
    libraries = mx.createDocument()
    mx.loadLibraries(mx.getDefaultDataLibraryFolders(), mx.getDefaultDataSearchPath(), libraries)
    definition = libraries.getNodeDef("ND_standard_surface_surfaceshader")
    real = {i.getName(): (i.getType(), i.getValueString()) for i in definition.getActiveInputs()}
    wrong = []
    for key, kind, default in basic.SURFACE_INPUTS:
        if key not in real or real[key][0] != kind:
            wrong.append((key, kind, real.get(key)))
        elif kind == "float" and abs(float(real[key][1]) - float(default)) > 1e-6:
            wrong.append((key, default, real[key][1]))
        elif kind == "color3" and any(abs(float(a) - b) > 1e-6 for a, b in zip(real[key][1].split(","), default)):
            wrong.append((key, default, real[key][1]))
    t.check("the standard surface inputs of the table exist in MaterialX with the same type and default", not wrong, wrong)

    def valid(text):
        document = mx.createDocument()
        document.importLibrary(libraries)
        path = work + "/validate.mtlx"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        mx.readFromXmlFile(document, path)
        return document.validate()
    invalid = [name for name, values in basic.BASIC_MATERIALS.items() if not valid(basic.build_mtlx(name, values))[0]]
    t.check("every basic material is a valid MaterialX document", not invalid, invalid)
    everything = {"values": {key: (0.2, 0.3, 0.4) if basic.INPUT_TYPES[key] == "color3" else (True if basic.INPUT_TYPES[key] == "boolean" else 0.5) for key in basic.INPUT_TYPES},
                  "mods": {"tint": (0.9, 0.8, 0.7), "rough_scale": 0.5, "normal": 2.0, "disp": 3.0, "tiling": 2.0}}
    for label, text in (("a texture sample", TEXTURED), ("a texture sample edited", edit.apply_settings(TEXTURED, everything)),
                        ("its mods only", edit.apply_settings(TEXTURED, {"mods": everything["mods"]}))):
        ok, why = valid(text)
        t.check("MaterialX validates " + label, ok, why[:200])

shutil.rmtree(work, ignore_errors=True)
t.done()
