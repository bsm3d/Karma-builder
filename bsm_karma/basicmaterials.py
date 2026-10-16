# basicmaterials.py - BSM Karma Builder - the inputs of the MaterialX standard surface and the tool's own basic materials
# Version : 2026.10.15.1 | Revision : 16-10-2026 | Auteur : BSM

import os
import re
from .util import _private_temp_dir

# (name, type, default) of the standard_surface inputs the editor knows, MaterialX 1.38. Only an input that differs from
# its default is written to a file.
SURFACE_INPUTS = (
    ("base", "float", 1.0), ("base_color", "color3", (0.8, 0.8, 0.8)), ("diffuse_roughness", "float", 0.0), ("metalness", "float", 0.0),
    ("specular", "float", 1.0), ("specular_color", "color3", (1.0, 1.0, 1.0)), ("specular_roughness", "float", 0.2),
    ("specular_IOR", "float", 1.5), ("specular_anisotropy", "float", 0.0),
    ("transmission", "float", 0.0), ("transmission_color", "color3", (1.0, 1.0, 1.0)), ("transmission_depth", "float", 0.0),
    ("transmission_scatter", "color3", (0.0, 0.0, 0.0)), ("transmission_extra_roughness", "float", 0.0),
    ("subsurface", "float", 0.0), ("subsurface_color", "color3", (1.0, 1.0, 1.0)), ("subsurface_radius", "color3", (1.0, 1.0, 1.0)),
    ("subsurface_scale", "float", 1.0), ("subsurface_anisotropy", "float", 0.0),
    ("sheen", "float", 0.0), ("sheen_color", "color3", (1.0, 1.0, 1.0)), ("sheen_roughness", "float", 0.3),
    ("coat", "float", 0.0), ("coat_color", "color3", (1.0, 1.0, 1.0)), ("coat_roughness", "float", 0.1), ("coat_IOR", "float", 1.5),
    ("emission", "float", 0.0), ("emission_color", "color3", (1.0, 1.0, 1.0)),
    ("opacity", "color3", (1.0, 1.0, 1.0)), ("thin_walled", "boolean", False),
)
INPUT_TYPES = {name: kind for name, kind, _ in SURFACE_INPUTS}
INPUT_DEFAULTS = {name: default for name, _, default in SURFACE_INPUTS}

# the tool's own basic materials: name -> the inputs that differ from the defaults
BASIC_MATERIALS = {
    "Plastic": {"base_color": (0.8, 0.12, 0.1), "specular_roughness": 0.25},
    "Rubber": {"base_color": (0.04, 0.04, 0.045), "specular_roughness": 0.7, "specular": 0.4},
    "Steel": {"base_color": (0.56, 0.57, 0.58), "metalness": 1.0, "specular_roughness": 0.35},
    "Gold": {"base_color": (1.0, 0.766, 0.336), "metalness": 1.0, "specular_roughness": 0.2},
    "Chrome": {"base_color": (0.9, 0.9, 0.9), "metalness": 1.0, "specular_roughness": 0.02},
    "Copper": {"base_color": (0.955, 0.638, 0.538), "metalness": 1.0, "specular_roughness": 0.25},
    "Glass": {"base": 0.0, "transmission": 1.0, "specular_roughness": 0.0, "specular_IOR": 1.5},
    "Frosted": {"base": 0.0, "transmission": 1.0, "specular_roughness": 0.35, "transmission_color": (0.85, 0.93, 0.97)},
    "Skin": {"base_color": (0.8, 0.52, 0.42), "specular_roughness": 0.45, "specular_IOR": 1.4, "subsurface": 0.65,
             "subsurface_color": (0.9, 0.35, 0.25), "subsurface_radius": (1.0, 0.35, 0.2), "subsurface_scale": 0.5, "coat": 0.05},
    "Wax": {"base_color": (0.9, 0.82, 0.55), "specular_roughness": 0.4, "subsurface": 0.8, "subsurface_color": (0.95, 0.8, 0.4),
            "subsurface_radius": (1.0, 0.8, 0.5), "subsurface_scale": 0.5},
    "Marble": {"base_color": (0.9, 0.88, 0.85), "specular_roughness": 0.15, "subsurface": 0.4, "subsurface_radius": (0.8, 0.8, 0.8),
               "subsurface_scale": 0.4, "coat": 0.4, "coat_roughness": 0.05},
    "Ceramic": {"base_color": (0.9, 0.9, 0.88), "specular_roughness": 0.15, "coat": 1.0, "coat_roughness": 0.04},
    "Car Paint": {"base_color": (0.02, 0.1, 0.35), "metalness": 0.5, "specular_roughness": 0.3, "coat": 1.0, "coat_roughness": 0.03},
    "Fabric": {"base_color": (0.4, 0.3, 0.55), "specular_roughness": 0.9, "specular": 0.1, "sheen": 1.0,
               "sheen_color": (0.7, 0.6, 0.85), "sheen_roughness": 0.5},
    "Leather": {"base_color": (0.25, 0.12, 0.06), "specular_roughness": 0.55, "specular": 0.6, "coat": 0.15, "coat_roughness": 0.35},
    "Emissive": {"base_color": (0.0, 0.0, 0.0), "emission": 3.0, "emission_color": (1.0, 0.9, 0.7)},
}


# ------------------------------------------------------------
# A name that MaterialX takes for a node and USD for a prim.
def safe_name(text):
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")
    if not name:
        name = "Material"
    if not (name[0].isalpha() or name[0] == "_"):
        name = "M_" + name
    return name[:64]


# ------------------------------------------------------------
def format_value(kind, value):
    if kind == "color3":
        return ", ".join("{:.6g}".format(float(v)) for v in value)
    if kind == "boolean":
        return "true" if value else "false"
    return "{:.6g}".format(float(value))


# ------------------------------------------------------------
def _same(kind, left, right):
    if kind == "color3":
        return all(abs(float(a) - float(b)) < 1e-6 for a, b in zip(left, right))
    if kind == "boolean":
        return bool(left) == bool(right)
    return abs(float(left) - float(right)) < 1e-6


# ------------------------------------------------------------
# The text of a .mtlx file with one standard surface and its material.
def build_mtlx(name, values):
    name = safe_name(name)
    lines = ['<?xml version="1.0"?>', '<materialx version="1.38">',
             '  <standard_surface name="SR_{}" type="surfaceshader">'.format(name)]
    for key, kind, default in SURFACE_INPUTS:
        if key in values and not _same(kind, values[key], default):
            lines.append('    <input name="{}" type="{}" value="{}" />'.format(key, kind, format_value(kind, values[key])))
    lines += ["  </standard_surface>", '  <surfacematerial name="{}" type="material">'.format(name),
              '    <input name="surfaceshader" type="surfaceshader" nodename="SR_{}" />'.format(name), "  </surfacematerial>",
              "</materialx>", ""]
    return "\n".join(lines)


# ------------------------------------------------------------
# Folder of the tool's data in the Houdini preferences (a private temp folder when there is none).
def data_folder(sub):
    import hou
    folders = []
    try:
        pref = hou.text.expandString("$HOUDINI_USER_PREF_DIR")
        if pref and not pref.startswith("$"):
            folders.append(os.path.join(pref, "bsm_karma", sub))
    except (hou.Error, AttributeError):
        pass
    folders.append(os.path.join(_private_temp_dir(), sub))
    for folder in folders:
        if "`" in folder:
            continue
        try:
            os.makedirs(folder, exist_ok=True)
            return folder.replace("\\", "/")
        except OSError:
            continue
    raise OSError("no folder for the materials")


# ------------------------------------------------------------
# The file of a basic material, written when it is first needed (the same text again when it exists).
def basic_material_file(name, folder=None):
    if name not in BASIC_MATERIALS:
        raise KeyError(name)
    folder = folder or data_folder("materials_basic")
    path = "{}/{}.mtlx".format(folder, safe_name(name))
    text = build_mtlx(name, BASIC_MATERIALS[name])
    try:
        with open(path, encoding="utf-8") as handle:
            if handle.read() == text:
                return path
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path
