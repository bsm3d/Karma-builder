# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : A general purpose PBR material written as a MaterialX file, with texture slots
# Houdini : 21 and 22 (plain Python, also runs without Houdini)
# Version : 1.0.0

import base64
import copy
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ElementTree
from .basicmaterials import INPUT_DEFAULTS, INPUT_TYPES, format_value, safe_name
from .util import _has_expression

PBR_MARKER = "bsm_karma_pbr"
MARKER_RE = re.compile(r"<!--\s*bsm_karma_pbr\s+([A-Za-z0-9+/=]+)\s*-->")
MARKER_SEARCH_BYTES = 65536
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".tga", ".tx", ".webp")
DISP_SCALE_DEFAULT = 0.02

SLOTS = (
    ("base_color", "Base Color", "color3"), ("roughness", "Roughness", "float"), ("metalness", "Metalness", "float"),
    ("normal", "Normal", "vector3"), ("ao", "Ambient Occlusion", "float"), ("height", "Displacement", "float"),
    ("emission", "Emission", "color3"), ("opacity", "Opacity", "float"),
)
SLOT_NAMES = tuple(slot for slot, _, _ in SLOTS)

DEFAULT_OPTIONS = {
    "normal_format": "OpenGL", "gloss": False, "ao_strength": 1.0, "tiling": 1.0, "offset": (0.0, 0.0), "rotation": 0.0,
    "tint": (1.0, 1.0, 1.0), "brightness": 1.0, "rough_scale": 1.0, "normal_strength": 1.0, "disp_scale": DISP_SCALE_DEFAULT,
    "disp_mid": 0.5,
}
NORMAL_FORMATS = ("OpenGL", "DirectX")

# the names that map files carry, by slot: the first word found in a file name decides
SLOT_WORDS = (
    ("normal", ("normalgl", "normaldx", "normal", "nrm", "nor_", "_nor")),
    ("roughness", ("roughness", "rough", "gloss")),
    ("metalness", ("metalness", "metallic", "metal")),
    ("ao", ("ambientocclusion", "occlusion", "_ao", "ao_", "-ao")),
    ("height", ("displacement", "height", "disp", "bump")),
    ("emission", ("emissive", "emission", "emit")),
    ("opacity", ("opacity", "alpha", "transparency", "mask")),
    ("base_color", ("basecolor", "base_color", "albedo", "diffuse", "color", "colour", "diff", "col")),
)


# ------------------------------------------------------------
def default_spec(name="PBR"):
    return {"name": safe_name(name), "values": {"base_color": (0.8, 0.8, 0.8), "specular_roughness": 0.45},
            "maps": {}, "options": copy.deepcopy(DEFAULT_OPTIONS)}


# ------------------------------------------------------------
def _number(value, low, high, default):
    try:
        return min(max(float(value), low), high)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------
def normalize_spec(spec):
    clean = default_spec(str((spec or {}).get("name", "PBR")))
    for key, value in ((spec or {}).get("values") or {}).items():
        if key not in INPUT_TYPES:
            continue
        kind = INPUT_TYPES[key]
        if kind == "color3":
            try:
                clean["values"][key] = tuple(_number(v, 0.0, 100.0, 0.0) for v in value)[:3] if len(value) == 3 else INPUT_DEFAULTS[key]
            except TypeError:
                continue
        elif kind == "boolean":
            clean["values"][key] = bool(value)
        else:
            clean["values"][key] = _number(value, 0.0, 1000.0, INPUT_DEFAULTS[key])
    for slot, path in ((spec or {}).get("maps") or {}).items():
        if slot in SLOT_NAMES and isinstance(path, str) and path.strip():
            path = path.strip().replace("\\", "/")
            if not _has_expression(path) and os.path.isabs(path) and path.lower().endswith(IMAGE_SUFFIXES) and len(path) < 1024:
                clean["maps"][slot] = path
    given = (spec or {}).get("options") or {}
    options = clean["options"]
    if given.get("normal_format") in NORMAL_FORMATS:
        options["normal_format"] = given["normal_format"]
    options["gloss"] = bool(given.get("gloss", False))
    for key, low, high in (("ao_strength", 0.0, 1.0), ("tiling", 0.01, 1000.0), ("rotation", -360.0, 360.0), ("brightness", 0.0, 100.0),
                           ("rough_scale", 0.0, 100.0), ("normal_strength", 0.0, 100.0), ("disp_scale", 0.0, 1000.0), ("disp_mid", 0.0, 1.0)):
        if key in given:
            options[key] = _number(given[key], low, high, DEFAULT_OPTIONS[key])
    for key in ("offset", "tint"):
        if key in given:
            try:
                size = 2 if key == "offset" else 3
                values = tuple(_number(v, -1000.0, 1000.0, 0.0) if key == "offset" else _number(v, 0.0, 100.0, 1.0) for v in given[key])
                if len(values) == size:
                    options[key] = values
            except TypeError:
                pass
    return clean


# ------------------------------------------------------------
def _vector(values):
    return ", ".join("{:.6g}".format(float(v)) for v in values)


# ------------------------------------------------------------
class _Builder:
    def __init__(self, spec):
        self.spec = spec
        self.root = ElementTree.Element("materialx", {"version": "1.38"})
        self.surface = None
        self.used = set()

    # ------------------------------------------------------------
    def node(self, tag, name, kind, **inputs):
        element = ElementTree.SubElement(self.root, tag, {"name": name, "type": kind})
        for key, (itype, value, connection) in inputs.items():
            entry = ElementTree.SubElement(element, "input", {"name": key, "type": itype})
            if connection is not None:
                entry.set("nodename", connection)
                if value is not None:
                    entry.set("output", value)
            elif value is not None:
                entry.set("value", value)
        return element

    # ------------------------------------------------------------
    def texcoord(self):
        options = self.spec["options"]
        if abs(options["rotation"]) < 1e-9:
            return None
        self.node("texcoord", "uv", "vector2")
        self.node("rotate2d", "uv_rotated", "vector2", **{"in": ("vector2", None, "uv"), "amount": ("float", "{:.6g}".format(options["rotation"]), None)})
        return "uv_rotated"

    # ------------------------------------------------------------
    def image(self, slot, kind, uv):
        options = self.spec["options"]
        name = "T_" + slot
        element = ElementTree.SubElement(self.root, "tiledimage", {"name": name, "type": kind})
        entry = ElementTree.SubElement(element, "input", {"name": "file", "type": "filename", "value": self.spec["maps"][slot]})
        if slot in ("base_color", "emission"):
            entry.set("colorspace", "srgb_texture")
        if abs(options["tiling"] - 1.0) > 1e-9:
            ElementTree.SubElement(element, "input", {"name": "uvtiling", "type": "vector2", "value": _vector((options["tiling"],) * 2)})
        if any(abs(v) > 1e-9 for v in options["offset"]):
            ElementTree.SubElement(element, "input", {"name": "uvoffset", "type": "vector2", "value": _vector(options["offset"])})
        if uv is not None:
            ElementTree.SubElement(element, "input", {"name": "texcoord", "type": "vector2", "nodename": uv})
        return name

    # ------------------------------------------------------------
    def connect(self, name, kind, source):
        ElementTree.SubElement(self.surface, "input", {"name": name, "type": kind, "nodename": source})

    # ------------------------------------------------------------
    def constant(self, key):
        kind = INPUT_TYPES[key]
        values = self.spec["values"]
        if key in values and not _same(kind, values[key], INPUT_DEFAULTS[key]):
            ElementTree.SubElement(self.surface, "input", {"name": key, "type": kind, "value": format_value(kind, values[key])})


# ------------------------------------------------------------
def _same(kind, left, right):
    if kind == "color3":
        return all(abs(float(a) - float(b)) < 1e-6 for a, b in zip(left, right))
    if kind == "boolean":
        return bool(left) == bool(right)
    return abs(float(left) - float(right)) < 1e-6


# ------------------------------------------------------------
def build_pbr_mtlx(spec):
    kept = normalize_spec(spec)
    spec = copy.deepcopy(kept)
    builder = _Builder(spec)
    name = spec["name"]
    options, maps = spec["options"], spec["maps"]
    uv = builder.texcoord()
    builder.surface = ElementTree.Element("standard_surface", {"name": "SR_" + name, "type": "surfaceshader"})
    handled = set()

    # the nodes come before the surface in the file; the surface is added to the tree after them
    if "base_color" in maps:
        source = builder.image("base_color", "color3", uv)
        factor = tuple(float(v) * options["brightness"] for v in options["tint"])
        if any(abs(v - 1.0) > 1e-9 for v in factor):
            builder.node("multiply", "M_base_color", "color3", in1=("color3", None, source), in2=("color3", _vector(factor), None))
            source = "M_base_color"
        if "ao" in maps:
            ao = builder.image("ao", "float", uv)
            if options["ao_strength"] < 1.0 - 1e-9:
                builder.node("mix", "AO_strength", "float", bg=("float", "1", None), fg=("float", None, ao), mix=("float", "{:.6g}".format(options["ao_strength"]), None))
                ao = "AO_strength"
            builder.node("multiply", "AO_base_color", "color3", in1=("color3", None, source), in2=("float", None, ao))
            source = "AO_base_color"
        builder.connect("base_color", "color3", source)
        handled.add("base_color")
    elif "ao" in maps:
        ao = builder.image("ao", "float", uv)
        if options["ao_strength"] < 1.0 - 1e-9:
            builder.node("mix", "AO_strength", "float", bg=("float", "1", None), fg=("float", None, ao), mix=("float", "{:.6g}".format(options["ao_strength"]), None))
            ao = "AO_strength"
        base = tuple(float(v) * options["brightness"] * float(t) for v, t in zip(spec["values"].get("base_color", INPUT_DEFAULTS["base_color"]), options["tint"]))
        builder.node("multiply", "AO_base_color", "color3", in1=("color3", _vector(base), None), in2=("float", None, ao))
        builder.connect("base_color", "color3", "AO_base_color")
        handled.add("base_color")
    else:
        factor = tuple(float(t) * options["brightness"] for t in options["tint"])
        if any(abs(v - 1.0) > 1e-9 for v in factor):
            spec["values"]["base_color"] = tuple(float(v) * f for v, f in zip(spec["values"].get("base_color", INPUT_DEFAULTS["base_color"]), factor))

    if "roughness" in maps:
        source = builder.image("roughness", "float", uv)
        if options["gloss"]:
            builder.node("invert", "R_invert", "float", **{"in": ("float", None, source)})
            source = "R_invert"
        if abs(options["rough_scale"] - 1.0) > 1e-9:
            builder.node("multiply", "R_scale", "float", in1=("float", None, source), in2=("float", "{:.6g}".format(options["rough_scale"]), None))
            source = "R_scale"
        builder.connect("specular_roughness", "float", source)
        handled.add("specular_roughness")
    elif abs(options["rough_scale"] - 1.0) > 1e-9:
        spec["values"]["specular_roughness"] = min(1.0, float(spec["values"].get("specular_roughness", INPUT_DEFAULTS["specular_roughness"])) * options["rough_scale"])

    if "metalness" in maps:
        builder.connect("metalness", "float", builder.image("metalness", "float", uv))
        handled.add("metalness")

    if "normal" in maps:
        source = builder.image("normal", "vector3", uv)
        if options["normal_format"] == "DirectX":
            builder.node("separate3", "N_split", "multioutput", **{"in": ("vector3", None, source)})
            builder.node("invert", "N_green", "float", **{"in": ("float", "outy", "N_split")})
            builder.node("combine3", "N_flipped", "vector3", in1=("float", "outx", "N_split"), in2=("float", None, "N_green"), in3=("float", "outz", "N_split"))
            source = "N_flipped"
        builder.node("normalmap", "N_map", "vector3", **{"in": ("vector3", None, source), "scale": ("float", "{:.6g}".format(options["normal_strength"]), None)})
        builder.connect("normal", "vector3", "N_map")

    if "emission" in maps:
        builder.connect("emission_color", "color3", builder.image("emission", "color3", uv))
        handled.add("emission_color")
        if "emission" not in spec["values"]:
            spec["values"]["emission"] = 1.0
    if "opacity" in maps:
        source = builder.image("opacity", "float", uv)
        builder.node("convert", "O_color", "color3", **{"in": ("float", None, source)})
        builder.connect("opacity", "color3", "O_color")
        handled.add("opacity")

    for key in INPUT_TYPES:
        if key not in handled:
            builder.constant(key)

    displacement = None
    if "height" in maps:
        source = builder.image("height", "float", uv)
        if abs(options["disp_mid"]) > 1e-9:
            builder.node("subtract", "D_mid", "float", in1=("float", None, source), in2=("float", "{:.6g}".format(options["disp_mid"]), None))
            source = "D_mid"
        builder.node("displacement", "D_shader", "displacementshader", displacement=("float", None, source), scale=("float", "{:.6g}".format(options["disp_scale"]), None))
        displacement = "D_shader"

    builder.root.append(builder.surface)
    material = ElementTree.SubElement(builder.root, "surfacematerial", {"name": name, "type": "material"})
    ElementTree.SubElement(material, "input", {"name": "surfaceshader", "type": "surfaceshader", "nodename": "SR_" + name})
    if displacement is not None:
        ElementTree.SubElement(material, "input", {"name": "displacementshader", "type": "displacementshader", "nodename": displacement})
    ElementTree.indent(builder.root, space="  ")
    text = ElementTree.tostring(builder.root, encoding="unicode")
    # the comment holds the spec as it came in: the constants that the options changed above are not in it
    return '<?xml version="1.0"?>\n<!-- {} {} -->\n{}\n'.format(PBR_MARKER, _encode(kept), text)


# ------------------------------------------------------------
def _encode(spec):
    return base64.b64encode(json.dumps(spec, sort_keys=True, default=list).encode("utf-8")).decode("ascii")


# ------------------------------------------------------------
def read_pbr_spec(text):
    found = MARKER_RE.search(text[:MARKER_SEARCH_BYTES])
    if not found:
        return None
    try:
        return normalize_spec(json.loads(base64.b64decode(found.group(1)).decode("utf-8")))
    except (ValueError, TypeError, UnicodeDecodeError):
        return None


# ------------------------------------------------------------
# Writes the file of a spec in `folder`: PBR.mtlx for the first one of a name, then name.bsm_<hash>.mtlx for each edit, so a
# change always makes a new file name (Karma does not reload a file whose name did not change). The same spec gives the same file.
def write_pbr_file(spec, folder, base=False):
    spec = normalize_spec(spec)
    text = build_pbr_mtlx(spec)
    name = spec["name"]
    if base:
        path = "{}/{}.mtlx".format(folder.replace("\\", "/"), name)
    else:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        path = "{}/{}.bsm_{}.mtlx".format(folder.replace("\\", "/"), name, digest)
    try:
        with open(path, encoding="utf-8") as handle:
            if handle.read() == text:
                return path
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


# ------------------------------------------------------------
# The maps of a folder, found by the words in their names (base_color, albedo, diff..., roughness, normal, ao, height...). A
# name that fits several slots goes to the first of SLOT_WORDS. Returns {slot: path}.
def guess_maps(folder):
    found = {}
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(IMAGE_SUFFIXES))
    except OSError:
        return found
    taken = set()
    for slot, words in SLOT_WORDS:
        for name in names:
            if name not in taken and any(word in name.lower() for word in words):
                found[slot] = "{}/{}".format(folder.replace("\\", "/"), name)
                taken.add(name)
                break
    return found
