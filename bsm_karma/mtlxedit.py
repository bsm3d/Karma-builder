# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Reads and changes MaterialX .mtlx files for the material editor, writing settings variants and reading embedded settings.

# Houdini : 21 and 22 (plain Python, also runs without Houdini)

import base64
import hashlib
import json
import math
import os
import re
import time
import xml.etree.ElementTree as ElementTree
from .basicmaterials import INPUT_DEFAULTS, INPUT_TYPES, format_value, safe_name

MAX_FILE_BYTES = 4 * 1024 * 1024
VARIANTS_KEPT = 50
VARIANT_MIN_AGE_DAYS = 14
EMBED_SEARCH_BYTES = 16384
VARIANT_RE = re.compile(r"^(?P<stem>.+)\.bsm_(?P<hash>[0-9a-f]{8})\.mtlx$")
EMBED_RE = re.compile(r"<!--\s*bsm_karma\s+([A-Za-z0-9+/=]+)\s*-->")
CONNECTION_ATTRIBUTES = ("nodename", "nodegraph", "output", "interfacename", "channels")
DEFAULT_MODS = {"tint": (1.0, 1.0, 1.0), "brightness": 1.0, "rough_scale": 1.0, "normal": 1.0, "disp": 1.0, "tiling": 1.0}

ElementTree.register_namespace("xi", "http://www.w3.org/2001/XInclude")

# ------------------------------------------------------------
class MtlxError(Exception):
    pass

# ------------------------------------------------------------
# The file as a tree, comments kept. A DOCTYPE or entities are refused (entity expansion), and so is a big file.
def parse(text):
    data = text.encode("utf-8") if isinstance(text, str) else text
    if len(data) > MAX_FILE_BYTES:
        raise MtlxError("the file is too big")
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise MtlxError("a DOCTYPE or entities in the file")
    parser = ElementTree.XMLParser(target=ElementTree.TreeBuilder(insert_comments=True))
    try:
        parser.feed(data)
        root = parser.close()
    except ElementTree.ParseError as exc:
        raise MtlxError("not valid XML: {}".format(exc))
    if root.tag != "materialx":
        raise MtlxError("not a MaterialX file")
    return root

# ------------------------------------------------------------
def read_text(path):
    if os.path.getsize(path) > MAX_FILE_BYTES:
        raise MtlxError("the file is too big")
    with open(path, encoding="utf-8") as handle:
        return handle.read()

# ------------------------------------------------------------
def _parents(root):
    return {child: parent for parent in root.iter() for child in parent}

# ------------------------------------------------------------
def _named(root, tag, name):
    for element in root.iter(tag):
        if element.get("name") == name:
            return element
    return None

# ------------------------------------------------------------
def find_surface(root):
    for material in root.iter("surfacematerial"):
        for entry in material.findall("input"):
            if entry.get("name") == "surfaceshader" and entry.get("nodename"):
                found = _named(root, "standard_surface", entry.get("nodename"))
                if found is not None:
                    return found
    return next(root.iter("standard_surface"), None)

# ------------------------------------------------------------
def _input(element, name):
    for entry in element.findall("input"):
        if entry.get("name") == name:
            return entry
    return None

# ------------------------------------------------------------
def _is_connected(entry):
    return entry is not None and any(entry.get(a) for a in ("nodename", "nodegraph", "interfacename"))

# ------------------------------------------------------------
def parse_value(kind, text):
    try:
        if kind in ("color3", "vector2"):
            parts = [float(p) for p in str(text).split(",")]
            return tuple(parts) if len(parts) == (3 if kind == "color3" else 2) and all(math.isfinite(p) for p in parts) else None
        if kind == "boolean":
            return str(text).strip().lower() == "true"
        number = float(text)
        return number if math.isfinite(number) else None
    except ValueError:
        return None

# ------------------------------------------------------------
def describe(text):
    root = parse(text)
    surface = find_surface(root)
    if surface is None:
        raise MtlxError("no standard_surface in this file: use Open Network")
    material = next((m.get("name") for m in root.iter("surfacematerial")), "")
    inputs = {}
    for key, kind in INPUT_TYPES.items():
        default = INPUT_DEFAULTS[key]
        entry = _input(surface, key)
        if entry is None:
            inputs[key] = {"kind": "default", "value": default}
        elif _is_connected(entry):
            inputs[key] = {"kind": "connected", "value": default}
        else:
            value = parse_value(kind, entry.get("value", ""))
            inputs[key] = {"kind": "value", "value": default if value is None else value}
    normal = next(iter(list(root.iter("normalmap")) + list(root.iter("bump"))), None)
    displacement = next(root.iter("displacement"), None)
    return {
        "material": material, "surface": surface.get("name", ""), "inputs": inputs,
        "textured": any(i["kind"] == "connected" for i in inputs.values()) or next(root.iter("image"), None) is not None
        or next(root.iter("tiledimage"), None) is not None,
        "has_normal": normal is not None, "has_displacement": displacement is not None,
        "has_tiling": next(root.iter("tiledimage"), None) is not None,
        "has_files": any(e.get("type") == "filename" for e in root.iter("input")),
    }

# ------------------------------------------------------------
def _clear_connection(entry):
    for attribute in CONNECTION_ATTRIBUTES:
        entry.attrib.pop(attribute, None)

# ------------------------------------------------------------
def _insert_multiply(container, surface, key, kind, factor):
    entry = _input(surface, key)
    if not _is_connected(entry):
        return False
    name = "BSM_mul_{}".format(key)
    multiply = ElementTree.SubElement(container, "multiply", {"name": name, "type": kind})
    source = ElementTree.SubElement(multiply, "input", {"name": "in1", "type": kind})
    for attribute in CONNECTION_ATTRIBUTES:
        if entry.get(attribute) is not None:
            source.set(attribute, entry.get(attribute))
    ElementTree.SubElement(multiply, "input", {"name": "in2", "type": kind, "value": format_value(kind, factor)})
    _clear_connection(entry)
    entry.attrib.pop("value", None)
    entry.set("nodename", name)
    return True

# ------------------------------------------------------------
def _scale_input_value(element, name, kind, factor, default):
    entry = _input(element, name)
    if entry is None:
        entry = ElementTree.SubElement(element, "input", {"name": name, "type": kind})
    current = parse_value(kind, entry.get("value", "")) if entry.get("value") is not None else default
    if current is None:
        current = default
    if kind == "vector2":
        entry.set("value", ", ".join("{:.6g}".format(float(v) * factor) for v in current))
    else:
        entry.set("value", "{:.6g}".format(float(current) * factor))

# ------------------------------------------------------------
def _number_of(value):
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None

# ------------------------------------------------------------
def _color_of(value):
    if isinstance(value, (list, tuple)) and len(value) == 3 and all(_number_of(v) is not None for v in value):
        return tuple(float(v) for v in value)
    return None

# ------------------------------------------------------------
# The settings that the editor writes, out of whatever a file says it holds (a comment of any file can say anything): known
# inputs and mods only, numbers that are finite, colors of three numbers.
def clean_settings(settings):
    settings = settings if isinstance(settings, dict) else {}
    values, mods = {}, {}
    given = settings.get("values")
    for key, value in (given if isinstance(given, dict) else {}).items():
        kind = INPUT_TYPES.get(key)
        if kind == "color3":
            value = _color_of(value)
        elif kind == "boolean":
            value = bool(value)
        elif kind is not None:
            value = _number_of(value)
        if kind is not None and value is not None:
            values[key] = value
    given = settings.get("mods")
    for key, value in (given if isinstance(given, dict) else {}).items():
        if key in DEFAULT_MODS:
            value = _color_of(value) if key == "tint" else _number_of(value)
            if value is not None:
                mods[key] = value
    return {"values": values, "mods": mods}

# ------------------------------------------------------------
# settings = {"values": {input: value}, "mods": {tint, brightness, rough_scale, normal, disp, tiling}}. A value replaces
# what drives the input (a texture too); the mods scale what stays a texture (1 is no change).
def apply_settings(text, settings):
    settings = clean_settings(settings)
    root = parse(text)
    surface = find_surface(root)
    if surface is None:
        raise MtlxError("no standard_surface in this file")
    parents = _parents(root)
    container = parents.get(surface, root)
    for key, value in (settings.get("values") or {}).items():
        if key not in INPUT_TYPES:
            continue
        kind = INPUT_TYPES[key]
        entry = _input(surface, key)
        if entry is None:
            entry = ElementTree.SubElement(surface, "input", {"name": key})
        _clear_connection(entry)
        entry.set("type", kind)
        entry.set("value", format_value(kind, value))

    mods = dict(DEFAULT_MODS)
    mods.update(settings.get("mods") or {})
    tint = [float(v) * float(mods["brightness"]) for v in mods["tint"]]
    if any(abs(v - 1.0) > 1e-6 for v in tint):
        _insert_multiply(container, surface, "base_color", "color3", tint)
    if abs(float(mods["rough_scale"]) - 1.0) > 1e-6:
        _insert_multiply(container, surface, "specular_roughness", "float", float(mods["rough_scale"]))
    if abs(float(mods["normal"]) - 1.0) > 1e-6:
        for node in list(root.iter("normalmap")) + list(root.iter("bump")):
            _scale_input_value(node, "scale", "float", float(mods["normal"]), 1.0)
    if abs(float(mods["disp"]) - 1.0) > 1e-6:
        for node in root.iter("displacement"):
            _scale_input_value(node, "scale", "float", float(mods["disp"]), 1.0)
    if abs(float(mods["tiling"]) - 1.0) > 1e-6:
        for node in root.iter("tiledimage"):
            _scale_input_value(node, "uvtiling", "vector2", float(mods["tiling"]), (1.0, 1.0))
    ElementTree.indent(root, space="  ")
    return '<?xml version="1.0"?>\n' + ElementTree.tostring(root, encoding="unicode") + "\n"

# ------------------------------------------------------------
def _encode(original, settings):
    return base64.b64encode(json.dumps({"original": original, "settings": settings}, sort_keys=True).encode("utf-8")).decode("ascii")

# ------------------------------------------------------------
def read_embedded(text):
    found = EMBED_RE.search(text[:EMBED_SEARCH_BYTES])
    if not found:
        return None
    try:
        data = json.loads(base64.b64decode(found.group(1)).decode("utf-8"))
        return str(data["original"]), clean_settings(data["settings"])
    except (ValueError, KeyError, TypeError):
        return None

# ------------------------------------------------------------
def _settings_key(settings):
    return json.dumps(settings, sort_keys=True, default=list)

# ------------------------------------------------------------
def original_and_settings(path):
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read(EMBED_SEARCH_BYTES + 64)
    except OSError:
        return path, {}
    embedded = read_embedded(text)
    if embedded is None:
        return path, {}
    original = os.path.join(os.path.dirname(path), embedded[0]).replace("\\", "/")
    if os.path.basename(original) != embedded[0] or not os.path.isfile(original):
        return path, {}
    return original, embedded[1]

# ------------------------------------------------------------
def write_variant(original, settings):
    text = read_text(original)
    new_text = apply_settings(text, settings)
    folder, name = os.path.split(original)
    stem = os.path.splitext(name)[0]
    digest = hashlib.sha1((name + _settings_key(settings)).encode("utf-8")).hexdigest()[:8]
    path = "{}/{}.bsm_{}.mtlx".format(folder.replace("\\", "/"), stem, digest)
    if not os.path.isfile(path):
        head, _, rest = new_text.partition("\n")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("{}\n<!-- bsm_karma {} -->\n{}".format(head, _encode(name, settings), rest))
        _prune(folder, stem, keep=path)
    return path

# ------------------------------------------------------------
def _prune(folder, stem, keep):
    try:
        mine = []
        for name in os.listdir(folder):
            found = VARIANT_RE.match(name)
            if found and found.group("stem") == stem:
                mine.append(os.path.join(folder, name))
        mine.sort(key=os.path.getmtime, reverse=True)
        # a scene saved earlier may still point at an older copy: only the copies beyond the newest ones and a few weeks old go
        limit = time.time() - VARIANT_MIN_AGE_DAYS * 86400
        for old in mine[VARIANTS_KEPT:]:
            if os.path.normcase(os.path.abspath(old)) != os.path.normcase(os.path.abspath(keep)) and os.path.getmtime(old) < limit:
                os.remove(old)
    except OSError:
        pass

# ------------------------------------------------------------
def write_named(original, settings, name, folder):
    text = read_text(original)
    new_text = apply_settings(text, settings)
    root = parse(new_text)
    wanted = safe_name(name)
    surface = find_surface(root)
    old_surface = surface.get("name") if surface is not None else None
    for material in root.iter("surfacematerial"):
        material.set("name", wanted)
        break
    if surface is not None:
        new_surface = "SR_" + wanted
        for entry in root.iter("input"):
            if entry.get("nodename") == old_surface:
                entry.set("nodename", new_surface)
        surface.set("name", new_surface)
    ElementTree.indent(root, space="  ")
    path = "{}/{}.mtlx".format(folder.replace("\\", "/"), wanted)
    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(original)):
        raise MtlxError("that name is the file being edited: choose another name")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0"?>\n' + ElementTree.tostring(root, encoding="unicode") + "\n")
    return path
