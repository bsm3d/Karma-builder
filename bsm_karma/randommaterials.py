# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Random materials: a color, and a finish, drawn from ranges the user sets
# Houdini : 21 and 22 (plain Python, also runs without Houdini)
# Version : 1.0.0

import colorsys
import hashlib
import json
import math
import os
import random
from .basicmaterials import build_mtlx, data_folder

KINDS = ("Any", "Plastic", "Matte", "Metal", "Paint")
DEFAULT_RANGES = {"hue_from": 0.0, "hue_to": 360.0, "sat_min": 0.35, "sat_max": 0.9, "val_min": 0.35, "val_max": 0.95}
MAX_PER_DROP = 200


# ------------------------------------------------------------
def srgb_to_linear(value):
    value = min(max(float(value), 0.0), 1.0)
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


# ------------------------------------------------------------
def _clean_ranges(ranges):
    merged = dict(DEFAULT_RANGES)
    for key in DEFAULT_RANGES:
        if key in (ranges or {}) and math.isfinite(float(ranges[key])):
            merged[key] = float(ranges[key])
    merged["sat_min"], merged["sat_max"] = sorted((min(max(merged["sat_min"], 0.0), 1.0), min(max(merged["sat_max"], 0.0), 1.0)))
    merged["val_min"], merged["val_max"] = sorted((min(max(merged["val_min"], 0.0), 1.0), min(max(merged["val_max"], 0.0), 1.0)))
    merged["hue_from"] = merged["hue_from"] % 360.0
    merged["hue_to"] = merged["hue_to"] % 360.0 if merged["hue_to"] != 360.0 else 360.0
    return merged


# ------------------------------------------------------------
# A hue between `hue_from` and `hue_to` going up (from 300 to 60 is magenta, red and orange), in degrees. The two equal
# is a single hue; 0 and 360 is the whole circle.
def _hue(rng, hue_from, hue_to):
    span = (hue_to - hue_from) % 360.0
    if hue_to == 360.0 and hue_from == 0.0:
        span = 360.0
    return (hue_from + rng.random() * span) % 360.0


# ------------------------------------------------------------
def random_color(rng, ranges, saturation_cap=1.0, value_floor=0.0):
    hue = _hue(rng, ranges["hue_from"], ranges["hue_to"])
    saturation = min(rng.uniform(ranges["sat_min"], ranges["sat_max"]), saturation_cap)
    value = max(rng.uniform(ranges["val_min"], ranges["val_max"]), value_floor)
    red, green, blue = colorsys.hsv_to_rgb(hue / 360.0, saturation, value)
    return (srgb_to_linear(red), srgb_to_linear(green), srgb_to_linear(blue))


# ------------------------------------------------------------
def random_values(seed, kind="Any", ranges=None):
    ranges = _clean_ranges(ranges)
    rng = random.Random("{}|{}|{}".format(int(seed), kind, json.dumps(ranges, sort_keys=True)))
    chosen = kind if kind in KINDS and kind != "Any" else rng.choice(KINDS[1:])
    if chosen == "Metal":
        return chosen, {"base_color": random_color(rng, ranges, saturation_cap=0.55, value_floor=0.6), "metalness": 1.0,
                        "specular_roughness": round(rng.uniform(0.1, 0.4), 3)}
    if chosen == "Matte":
        return chosen, {"base_color": random_color(rng, ranges), "specular_roughness": round(rng.uniform(0.65, 0.95), 3), "specular": 0.3}
    if chosen == "Paint":
        return chosen, {"base_color": random_color(rng, ranges), "specular_roughness": round(rng.uniform(0.2, 0.4), 3), "coat": 1.0,
                        "coat_roughness": 0.03}
    return chosen, {"base_color": random_color(rng, ranges), "specular_roughness": round(rng.uniform(0.12, 0.45), 3)}


# ------------------------------------------------------------
def random_name(seed, kind, ranges):
    key = "{}|{}|{}".format(int(seed), kind, json.dumps(_clean_ranges(ranges), sort_keys=True))
    return "Random_{}".format(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8])


# ------------------------------------------------------------
def random_material_file(seed, kind="Any", ranges=None, folder=None):
    folder = folder or data_folder("materials_random")
    kind_used, values = random_values(seed, kind, ranges)
    name = random_name(seed, kind, ranges)
    path = "{}/{}.mtlx".format(folder, name)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(build_mtlx(name, values))
    return path
