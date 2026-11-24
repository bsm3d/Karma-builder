# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Moon placement on the ecliptic from the sun and the phase, with its material and the halo sphere around the disc.

# Houdini : 21 and 22

import hashlib
import html
import math
import os
from .clouds2d import CLOUD_UV_VEX, _cache_folder, _forget_old_textures
from .util import _has_expression

MOON_PREFIX = "bsm_moon_"
MOON_FILES_KEPT = 40
OBLIQUITY = 23.44
MOON_LIGHT_BASE = 0.25
MOON_COLOR = (0.82, 0.87, 1.0)
# the halo is a sphere this many times wider than the disc, its opacity falls off towards the edge
HALO_SCALE = 2.4
HALO_COLOR = (0.75, 0.82, 1.0)
EARTHSHINE = 0.035

# the sphere SOPs have no normals: without them the terminator is faceted
MOON_VEX = CLOUD_UV_VEX + "\nv@N = normalize(point(0, \"P\", vertexpoint(0, @vtxnum)));"
HALO_VEX = "v@N = normalize(point(0, \"P\", vertexpoint(0, @vtxnum)));"

# The disc is lit by the sun like a ball: its normal against the direction of the sun (a constant of the file, the moon is far
# enough for the sun to be a direction), a soft terminator and a little earthshine on the dark side. The halo is a bigger sphere
# whose opacity falls off with the distance to its centre as seen from the camera (1 - r)^2.6: a glow that blends, nothing at the edge.
MOON_MTLX = """<?xml version="1.0"?>
<materialx version="1.38">
{map_node}  <normal name="surface_normal" type="vector3">
    <input name="space" type="string" value="world" />
  </normal>
  <dotproduct name="sun_facing" type="float">
    <input name="in1" type="vector3" nodename="surface_normal" />
    <input name="in2" type="vector3" value="{sun_dir}" />
  </dotproduct>
  <smoothstep name="terminator" type="float">
    <input name="in" type="float" nodename="sun_facing" />
    <input name="low" type="float" value="-0.03" />
    <input name="high" type="float" value="0.15" />
  </smoothstep>
  <max name="lit" type="float">
    <input name="in1" type="float" nodename="terminator" />
    <input name="in2" type="float" value="{earthshine}" />
  </max>
  <multiply name="moon_color" type="color3">
    <input name="in1" type="color3" {color_input} />
    <input name="in2" type="float" nodename="lit" />
  </multiply>
  <standard_surface name="SR_Moon" type="surfaceshader">
    <input name="base" type="float" value="0" />
    <input name="specular" type="float" value="0" />
    <input name="emission" type="float" value="{emission}" />
    <input name="emission_color" type="color3" nodename="moon_color" />
    <input name="opacity" type="color3" value="{fade}, {fade}, {fade}" />
  </standard_surface>
  <surfacematerial name="Moon" type="material">
    <input name="surfaceshader" type="surfaceshader" nodename="SR_Moon" />
  </surfacematerial>
  <viewdirection name="view" type="vector3">
    <input name="space" type="string" value="world" />
  </viewdirection>
  <dotproduct name="facing_raw" type="float">
    <input name="in1" type="vector3" nodename="surface_normal" />
    <input name="in2" type="vector3" nodename="view" />
  </dotproduct>
  <absval name="facing" type="float">
    <input name="in" type="float" nodename="facing_raw" />
  </absval>
  <multiply name="facing_squared" type="float">
    <input name="in1" type="float" nodename="facing" />
    <input name="in2" type="float" nodename="facing" />
  </multiply>
  <subtract name="radius_squared" type="float">
    <input name="in1" type="float" value="1" />
    <input name="in2" type="float" nodename="facing_squared" />
  </subtract>
  <power name="halo_radius" type="float">
    <input name="in1" type="float" nodename="radius_squared" />
    <input name="in2" type="float" value="0.5" />
  </power>
  <subtract name="halo_inverse" type="float">
    <input name="in1" type="float" value="1" />
    <input name="in2" type="float" nodename="halo_radius" />
  </subtract>
  <power name="falloff" type="float">
    <input name="in1" type="float" nodename="halo_inverse" />
    <input name="in2" type="float" value="2.6" />
  </power>
  <multiply name="halo_alpha" type="float">
    <input name="in1" type="float" nodename="falloff" />
    <input name="in2" type="float" value="{halo_alpha}" />
  </multiply>
  <convert name="halo_opacity" type="color3">
    <input name="in" type="float" nodename="halo_alpha" />
  </convert>
  <standard_surface name="SR_MoonHalo" type="surfaceshader">
    <input name="base" type="float" value="0" />
    <input name="specular" type="float" value="0" />
    <input name="emission" type="float" value="{halo_emission}" />
    <input name="emission_color" type="color3" value="{halo_color}" />
    <input name="opacity" type="color3" nodename="halo_opacity" />
  </standard_surface>
  <surfacematerial name="MoonHalo" type="material">
    <input name="surfaceshader" type="surfaceshader" nodename="SR_MoonHalo" />
  </surfacematerial>
</materialx>
"""

# ------------------------------------------------------------
# Moon position from the sun's place and the phase slider (0 new, 0.25 first quarter, 0.5 full, 0.75 last quarter).
# The sun is turned round an axis from the ecliptic pole by the elongation (phase x 360 degrees), in the star frame: the moon follows its own inclined elliptical path.
# Returns unit vectors (world, azimuth 0 is -Z) of the moon and the sun, the moon's altitude and the illuminated part.
def moon_state(cfg):
    import numpy as np
    from .ephemeris import apply_exact_sky, world_vector
    from .nightsky import celestial_rotation, star_direction
    cfg = apply_exact_sky(cfg)
    if cfg.get("_snapshot"):
        return _exact_moon_state(np, cfg, cfg["_snapshot"], world_vector)
    sun_alt = math.radians(float(cfg.get("sky_elev", 30.0)))
    sun_az = math.radians(float(cfg.get("sky_azim", 0.0)))
    sun = np.array([math.sin(sun_az) * math.cos(sun_alt), math.sin(sun_alt), -math.cos(sun_az) * math.cos(sun_alt)])
    rotation = celestial_rotation(np, float(cfg.get("stars_latitude", 45.0)), float(cfg.get("stars_time", 0.0)))
    in_stars = rotation.T @ sun
    elongation = math.radians(float(cfg.get("moon_phase", 0.5)) * 360.0)
    pole = star_direction(np, math.radians(270.0), math.radians(90.0 - OBLIQUITY))
    # the sliders can put the sun anywhere, not only on the ecliptic: the axis is the ecliptic pole made square to the sun, so the
    # path of the moon goes through the sun (new moon), the point opposite it (full moon) and is tilted as the ecliptic is
    axis = pole - in_stars * float(np.dot(pole, in_stars))
    length = float(np.linalg.norm(axis))
    axis = axis / length if length > 1e-6 else np.cross(in_stars, np.array([1.0, 0.0, 0.0]))
    axis = axis / np.linalg.norm(axis)
    # Rodrigues: the sun turned about that axis
    turned = (in_stars * math.cos(elongation) + np.cross(axis, in_stars) * math.sin(elongation)
              + axis * float(np.dot(axis, in_stars)) * (1.0 - math.cos(elongation)))
    moon = rotation @ turned
    moon = moon / np.linalg.norm(moon)
    altitude = math.degrees(math.asin(max(-1.0, min(1.0, float(moon[1])))))
    azimuth = math.degrees(math.atan2(float(moon[0]), -float(moon[2]))) % 360.0
    shown = min(max((altitude + 3.0) / 5.0, 0.0), 1.0)
    fade = round(shown * shown * (3.0 - 2.0 * shown) * 20.0) / 20.0
    daylight = min(max((math.degrees(sun_alt) + 6.0) / 16.0, 0.0), 1.0)
    return {"active": bool(cfg.get("moon_enable")) and fade > 0.0, "fade": fade, "altitude": altitude, "azimuth": azimuth,
            "moon": moon, "sun": sun, "lit": (1.0 - float(np.dot(moon, sun))) / 2.0, "daylight": daylight}

# ------------------------------------------------------------
# The exact sky: the moon and the sun are where the ephemeris puts them (the moon with its parallax), the phase is the angle
# between them (the slider is not read).
def _exact_moon_state(np, cfg, snapshot, world_vector):
    sun = np.array(world_vector(snapshot["sun"]["altitude"], snapshot["sun"]["azimuth"]))
    moon = np.array(world_vector(snapshot["moon"]["altitude"], snapshot["moon"]["azimuth"]))
    altitude, azimuth = snapshot["moon"]["altitude"], snapshot["moon"]["azimuth"] % 360.0
    shown = min(max((altitude + 3.0) / 5.0, 0.0), 1.0)
    fade = round(shown * shown * (3.0 - 2.0 * shown) * 20.0) / 20.0
    daylight = min(max((snapshot["sun"]["altitude"] + 6.0) / 16.0, 0.0), 1.0)
    s_ra, s_dec, m_ra, m_dec = snapshot["sun"]["ra"], snapshot["sun"]["dec"], snapshot["moon"]["ra"], snapshot["moon"]["dec"]
    cos_elongation = math.sin(s_dec) * math.sin(m_dec) + math.cos(s_dec) * math.cos(m_dec) * math.cos(s_ra - m_ra)
    return {"active": bool(cfg.get("moon_enable")) and fade > 0.0, "fade": fade, "altitude": altitude, "azimuth": azimuth, "moon": moon, "sun": sun,
            "lit": (1.0 - cos_elongation) / 2.0, "daylight": daylight}

# ------------------------------------------------------------
# The material file of the moon, one per set of values (the template is part of the key).
def moon_file(emission, fade, texture, sun_dir, halo, daylight_halo=1.0):
    if _has_expression(texture):
        raise ValueError("refusing a moon texture path that contains an expression")
    if texture:
        color_input = 'nodename="moon_map"'
        map_node = ('  <image name="moon_map" type="color3">\n    <input name="file" type="filename" value="{}" colorspace="srgb_texture" />\n'
                    '  </image>\n').format(html.escape(texture, quote=True))
    else:
        color_input = 'value="{}"'.format(", ".join("{:.4f}".format(float(c)) for c in MOON_COLOR))
        map_node = ""
    values = dict(map_node=map_node, color_input=color_input, earthshine="{:.4f}".format(EARTHSHINE), emission="{:.4f}".format(float(emission)),
                  fade="{:.3f}".format(float(fade)), sun_dir=", ".join("{:.4f}".format(float(c)) for c in sun_dir),
                  halo_alpha="{:.4f}".format(1.1 * float(halo) * float(fade) * float(daylight_halo)),
                  halo_emission="{:.4f}".format(1.1 * float(emission)), halo_color=", ".join("{:.3f}".format(c) for c in HALO_COLOR))
    key = "|".join("{}={}".format(k, values[k]) for k in sorted(values)) + "|" + MOON_MTLX
    folder = _cache_folder()
    path = "{}/{}{}.mtlx".format(folder, MOON_PREFIX, hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12])
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(MOON_MTLX.format(**values))
        _forget_old_textures(folder, keep=path, prefix=MOON_PREFIX, count=MOON_FILES_KEPT)
    return path
