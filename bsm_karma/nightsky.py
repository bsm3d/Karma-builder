# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Night sky built as Karma geometry: stars as points with halo and twinkle, planets, and the Milky Way picture.

# Houdini : 21 and 22

import hashlib
import html
import math
import os
from hutil.Qt import QtGui
from .clouds2d import _cache_folder, _forget_old_textures
from .debuglog import _debug
from .util import _has_expression, _sky_data_file

NIGHT_CARD_PREFIX = "bsm_nightcard_"
NIGHT_POINTS_PREFIX = "bsm_stars_"
NIGHT_FILES_KEPT = 4

STAR_LIMIT_MAG = 6.8
# A star is a pin point whose brightness follows its magnitude: the angular size (degrees, times the Star Size slider) hardly
# grows, the flux does (10^(-0.4 (V - 2)), kept between FLUX_MIN and FLUX_MAX, a primvar the material multiplies the colour by).
# The faint ones are under a pixel, so the render itself shows them dimmer by their coverage. Only the bright ones have a halo.
STAR_SIZE_FAINT = 0.03
STAR_SIZE_STEP = 0.012
STAR_SIZE_FROM = 3.0
# what the air takes out of the red, green and blue light of a star per air mass (magnitudes): it reddens a star near the horizon
EXTINCTION = (0.12, 0.20, 0.35)
FLUX_MIN = 0.03
FLUX_MAX = 8.0
GLOW_SIZE = 0.10
GLOW_SIZE_STEP = 0.09

# the Milky Way sphere sits behind the clouds (70 km), the moon (84 km, its halo to 120 km at most) and the stars (140 km): all far, as the sky is
NIGHT_RADIUS = 150000.0
STARS_RADIUS = 140000.0
NIGHT_PRIM = "/World/Environment/NightSky"
NIGHT_STARS_PRIM = "/World/Environment/NightStars"
NIGHT_MATS = "/World/Environment/NightMaterials"
# the sphere SOP has no lat-long UVs: written per vertex, the seam fixed per face. The map is in right ascension, to the left
# of the picture, and the stars use the same direction: (cos dec cos ra, sin dec, -cos dec sin ra)
NIGHT_UV_VEX = """vector uvof(vector P) { vector p = normalize(P); return set(0.5 - atan2(-p.z, p.x) / (2 * PI), asin(clamp(p.y, -1, 1)) / PI + 0.5, 0); }
int vts[] = primvertices(0, vertexprim(0, @vtxnum));
float umin = 1, umax = 0;
foreach (int vt; vts) { vector q = uvof(point(0, "P", vertexpoint(0, vt))); umin = min(umin, q.x); umax = max(umax, q.x); }
vector uv = uvof(@P);
if (umax - umin > 0.5 && uv.x < 0.5) uv.x += 1;
v@uv = uv;"""

# One material file for the whole sky. The picture replaces the sky by the fade (opaque in the deep night). The stars take their
# colour from the points (displayColor) and twinkle with the clock and a phase of their own; the glow is a bigger sphere whose
# opacity falls off towards its edge (facing ratio), so a bright star has a soft halo whatever the resolution is.
NIGHT_MTLX = """<?xml version="1.0"?>
<materialx version="1.38">
  <geompropvalue name="point_color" type="color3">
    <input name="geomprop" type="string" value="displayColor" />
  </geompropvalue>
  <geompropvalue name="point_phase" type="float">
    <input name="geomprop" type="string" value="phase" />
  </geompropvalue>
  <time name="clock" type="float" />
  <multiply name="clock_speed" type="float">
    <input name="in1" type="float" nodename="clock" />
    <input name="in2" type="float" value="{twinkle_speed}" />
  </multiply>
  <multiply name="phase_turns" type="float">
    <input name="in1" type="float" nodename="point_phase" />
    <input name="in2" type="float" value="100" />
  </multiply>
  <add name="wave_angle" type="float">
    <input name="in1" type="float" nodename="clock_speed" />
    <input name="in2" type="float" nodename="phase_turns" />
  </add>
  <sin name="wave" type="float">
    <input name="in" type="float" nodename="wave_angle" />
  </sin>
  <geompropvalue name="point_scint" type="float">
    <input name="geomprop" type="string" value="scint" />
  </geompropvalue>
  <multiply name="twinkle_here" type="float">
    <input name="in1" type="float" nodename="point_scint" />
    <input name="in2" type="float" value="{twinkle}" />
  </multiply>
  <multiply name="wave_amount" type="float">
    <input name="in1" type="float" nodename="wave" />
    <input name="in2" type="float" nodename="twinkle_here" />
  </multiply>
  <add name="flicker_raw" type="float">
    <input name="in1" type="float" nodename="wave_amount" />
    <input name="in2" type="float" value="1" />
  </add>
  <max name="flicker" type="float">
    <input name="in1" type="float" nodename="flicker_raw" />
    <input name="in2" type="float" value="0" />
  </max>
  <geompropvalue name="point_flux" type="float">
    <input name="geomprop" type="string" value="flux" />
  </geompropvalue>
  <multiply name="flicker_flux" type="float">
    <input name="in1" type="float" nodename="flicker" />
    <input name="in2" type="float" nodename="point_flux" />
  </multiply>
  <multiply name="star_color" type="color3">
    <input name="in1" type="color3" nodename="point_color" />
    <input name="in2" type="float" nodename="flicker_flux" />
  </multiply>
  <multiply name="glow_color" type="color3">
    <input name="in1" type="color3" nodename="point_color" />
    <input name="in2" type="float" nodename="point_flux" />
  </multiply>
  <normal name="surface_normal" type="vector3">
    <input name="space" type="string" value="world" />
  </normal>
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
  <power name="falloff" type="float">
    <input name="in1" type="float" nodename="facing" />
    <input name="in2" type="float" value="6" />
  </power>
  <multiply name="glow_alpha" type="float">
    <input name="in1" type="float" nodename="falloff" />
    <input name="in2" type="float" value="{glow_alpha}" />
  </multiply>
  <convert name="glow_opacity" type="color3">
    <input name="in" type="float" nodename="glow_alpha" />
  </convert>
{milky_map}  <standard_surface name="SR_Star" type="surfaceshader">
    <input name="base" type="float" value="0" />
    <input name="specular" type="float" value="0" />
    <input name="emission" type="float" value="{star_emission}" />
    <input name="emission_color" type="color3" nodename="star_color" />
    <input name="opacity" type="color3" value="{fade}, {fade}, {fade}" />
  </standard_surface>
  <surfacematerial name="StarMat" type="material">
    <input name="surfaceshader" type="surfaceshader" nodename="SR_Star" />
  </surfacematerial>
  <standard_surface name="SR_Glow" type="surfaceshader">
    <input name="base" type="float" value="0" />
    <input name="specular" type="float" value="0" />
    <input name="emission" type="float" value="{glow_emission}" />
    <input name="emission_color" type="color3" nodename="glow_color" />
    <input name="opacity" type="color3" nodename="glow_opacity" />
  </standard_surface>
  <surfacematerial name="GlowMat" type="material">
    <input name="surfaceshader" type="surfaceshader" nodename="SR_Glow" />
  </surfacematerial>
</materialx>
"""

MILKY_MAP_MTLX = """  <position name="sky_position" type="vector3">
    <input name="space" type="string" value="world" />
  </position>
  <normalize name="sky_direction" type="vector3">
    <input name="in" type="vector3" nodename="sky_position" />
  </normalize>
  <extract name="sky_height" type="float">
    <input name="in" type="vector3" nodename="sky_direction" />
    <input name="index" type="integer" value="1" />
  </extract>
  <smoothstep name="above_horizon" type="float">
    <input name="in" type="float" nodename="sky_height" />
    <input name="low" type="float" value="-0.03" />
    <input name="high" type="float" value="0.05" />
  </smoothstep>
  <multiply name="milky_alpha" type="float">
    <input name="in1" type="float" nodename="above_horizon" />
    <input name="in2" type="float" value="{fade}" />
  </multiply>
  <convert name="milky_opacity" type="color3">
    <input name="in" type="float" nodename="milky_alpha" />
  </convert>
  <image name="milky_map" type="color3">
    <input name="file" type="filename" value="{file}" colorspace="Raw" />
  </image>
  <standard_surface name="SR_Milky" type="surfaceshader">
    <input name="base" type="float" value="0" />
    <input name="specular" type="float" value="0" />
    <input name="emission" type="float" value="{milky_emission}" />
    <input name="emission_color" type="color3" nodename="milky_map" />
    <input name="opacity" type="color3" nodename="milky_opacity" />
  </standard_surface>
  <surfacematerial name="MilkyMat" type="material">
    <input name="surfaceshader" type="surfaceshader" nodename="SR_Milky" />
  </surfacematerial>
"""

# ------------------------------------------------------------
# The pictures of datas/Sky this layer can use now: (milky way, stars), "" for a missing one.
def night_sources():
    return _sky_data_file("milky_way_1k.exr"), _sky_data_file("stars.npz")

# ------------------------------------------------------------
# Direction of a star on a unit sphere: the celestial pole is +Y, the right ascension grows to the left when the sky is seen
# from the inside with north up (so the stars come out as they are in the sky, not mirrored).
def star_direction(np, ra, dec):
    return np.stack([np.cos(dec) * np.cos(ra), np.sin(dec), -np.cos(dec) * np.sin(ra)], axis=-1)

# ------------------------------------------------------------
# The celestial pole rises to the latitude above the north horizon (north is -Z, as for the azimuth of the sun); the hours
# turn the sky round that axis (the stars go west as the sidereal hours grow). A 3 x 3 matrix for column vectors.
def celestial_rotation(np, latitude, hours):
    # hours is the local sidereal time: the stars of that right ascension cross the meridian (south, +Z) at that moment
    spin = -math.radians(float(hours) * 15.0 + 90.0)
    tilt = math.radians(float(latitude) - 90.0)
    ry = np.array([[math.cos(spin), 0.0, math.sin(spin)], [0.0, 1.0, 0.0], [-math.sin(spin), 0.0, math.cos(spin)]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(tilt), -math.sin(tilt)], [0.0, math.sin(tilt), math.cos(tilt)]])
    return rx @ ry

# ------------------------------------------------------------
# The three rotation angles of a transform that does the same (for the sphere of the Milky Way), in the order of the node.
def night_rotation(latitude, hours):
    import hou
    import numpy as np
    rotation = celestial_rotation(np, latitude, hours)
    # Houdini's matrices are for row vectors: the transpose
    matrix = hou.Matrix3(tuple(float(v) for v in rotation.T.reshape(-1)))
    return hou.Matrix4(matrix).extractRotates()

# ------------------------------------------------------------
# The Milky Way is a small picture that travels with the tool (datas/Sky/milky_way_1k.exr, 1024 x 512, linear, the gain applied,
# made by tools/make_milky_way.py from NASA's map): it is a soft glow, nothing is generated here and nothing is written.
def milky_way_texture_path():
    return _sky_data_file("milky_way_1k.exr")

# The stars (and the planets of an exact sky) as they stand for a latitude and a sidereal time: unit vectors in the world of the tool,
# magnitudes, colours dimmed and reddened by the air, flux, scintillation. What is under the horizon is left out. Shared by the points
# of the scene and by the sky plate of a composite.
def star_catalog(latitude, lst_hours, snapshot=None):
    import numpy as np
    from .ephemeris import precess
    stars_path = _sky_data_file("stars.npz")
    if not stars_path:
        raise OSError("no star catalogue found: datas/Sky/stars.npz is not beside the tool or in the Houdini preferences")
    rotation = celestial_rotation(np, latitude, lst_hours)
    data = np.load(stars_path)
    keep = data["vmag"] < STAR_LIMIT_MAG
    ra, dec = data["ra"][keep], data["dec"][keep]
    if snapshot is not None:
        # the exact sky: the catalogue is J2000, the stars have moved and the pole has turned since
        ra, dec = precess(np, ra, dec, snapshot["jd"], data["pm_ra"][keep], data["pm_dec"][keep])
    vmag = data["vmag"][keep].astype(np.float32)
    colour = data["color"][keep].astype(np.float32)
    if snapshot is not None:
        # the planets are stars that move: a position, a magnitude and a colour of their own
        planet_ra = np.array([p[1] for p in snapshot["planets"]])
        planet_dec = np.array([p[2] for p in snapshot["planets"]])
        ra, dec = np.concatenate([ra, planet_ra]), np.concatenate([dec, planet_dec])
        vmag = np.concatenate([vmag, np.array([p[3] for p in snapshot["planets"]], dtype=np.float32)])
        colour = np.concatenate([colour, np.array([p[4] for p in snapshot["planets"]], dtype=np.float32)])
        is_planet = np.concatenate([np.zeros(int(keep.sum()), dtype=bool), np.ones(len(planet_ra), dtype=bool)])
    else:
        is_planet = np.zeros(len(vmag), dtype=bool)
    world = star_direction(np, ra, dec) @ rotation.T
    # under the horizon nothing shows (the ground of the sky would be covered by stars); near it, the air dims and reddens
    altitude = np.degrees(np.arcsin(np.clip(world[:, 1], -1.0, 1.0)))
    visible = altitude > -1.0
    world, vmag, colour, altitude, is_planet = world[visible], vmag[visible], colour[visible], altitude[visible], is_planet[visible]
    mass = 1.0 / (np.sin(np.radians(np.clip(altitude, 0.0, 90.0))) + 0.50572 * (6.07995 + np.clip(altitude, 0.0, 90.0)) ** -1.6364)
    colour = colour * (10.0 ** (-0.4 * np.array(EXTINCTION)[None, :] * (mass[:, None] - 1.0))).astype(np.float32)
    # the scintillation grows with the air mass (to the power 1.5) and is gentler for a planet, which is a disc
    scint = np.clip(0.15 * mass ** 1.5, 0.15, 1.5) * np.where(is_planet, 0.4, 1.0)
    flux = np.clip(10.0 ** (-0.4 * (vmag - 2.0)), FLUX_MIN, np.where(is_planet, FLUX_MAX * 4.0, FLUX_MAX)).astype(np.float32)
    return {"world": world, "vmag": vmag, "colour": colour, "altitude": altitude, "is_planet": is_planet, "mass": mass, "scint": scint, "flux": flux}

# ------------------------------------------------------------
# ------------------------------------------------------------
# A USD file with the points of the night sky, turned for the latitude and the hour: Stars (all the catalogue, a width from the
# magnitude, a colour from B-V reddened by the air, a phase and a scintillation for the twinkle) and StarGlow (the bright ones again, bigger, for the halo).
# Points are drawn by Karma as little spheres, sharp at any resolution.
def star_points_file(latitude, lst_hours, size_scale, glow_limit, snapshot=None):
    import numpy as np
    from pxr import Sdf, Usd, UsdGeom, Vt
    stars_path = _sky_data_file("stars.npz")
    if not stars_path:
        raise OSError("no star catalogue found: datas/Sky/stars.npz is not beside the tool or in the Houdini preferences")
    key = "points4|{:.2f}|{:.3f}|{:.3f}|{:.2f}|{}|{}".format(float(latitude), float(lst_hours), float(size_scale), float(glow_limit),
                                                              os.path.getsize(stars_path), "" if snapshot is None else "{:.5f}".format(snapshot["jd"]))
    folder = _cache_folder()
    path = "{}/{}{}.usdc".format(folder, NIGHT_POINTS_PREFIX, hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12])
    if os.path.isfile(path):
        return path
    cat = star_catalog(latitude, lst_hours, snapshot)
    world, vmag, colour, is_planet, scint, flux = cat["world"], cat["vmag"], cat["colour"], cat["is_planet"], cat["scint"], cat["flux"]
    position = (world * STARS_RADIUS).astype(np.float32)
    size = np.radians((STAR_SIZE_FAINT + STAR_SIZE_STEP * np.clip(STAR_SIZE_FROM - vmag, 0.0, None)) * float(size_scale))
    width = (2.0 * STARS_RADIUS * np.tan(size / 2.0)).astype(np.float32)
    phase = np.random.default_rng(11).random(len(vmag)).astype(np.float32)

    temp = path + ".part.usdc"
    stage = Usd.Stage.CreateNew(temp)
    root = UsdGeom.Xform.Define(stage, "/NightStars")
    stage.SetDefaultPrim(root.GetPrim())

    def points(name, pos, wid, col, **extra):
        prim = UsdGeom.Points.Define(stage, "/NightStars/" + name)
        prim.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(pos)))
        prim.CreateWidthsAttr(Vt.FloatArray.FromNumpy(np.ascontiguousarray(wid)))
        prim.CreateDisplayColorPrimvar(UsdGeom.Tokens.vertex).Set(Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(col)))
        for key_name, values in extra.items():
            UsdGeom.PrimvarsAPI(prim.GetPrim()).CreatePrimvar(key_name, Sdf.ValueTypeNames.FloatArray, UsdGeom.Tokens.vertex).Set(
                Vt.FloatArray.FromNumpy(np.ascontiguousarray(values, dtype=np.float32)))
        return prim

    points("Stars", position, width, colour, phase=phase, flux=flux, scint=scint)
    bright = vmag < float(glow_limit)
    if bright.any():
        glow_size = np.radians((GLOW_SIZE + GLOW_SIZE_STEP * (float(glow_limit) - vmag[bright])) * float(size_scale))
        points("StarGlow", position[bright], (2.0 * STARS_RADIUS * np.tan(glow_size / 2.0)).astype(np.float32), colour[bright], flux=flux[bright])
    stage.GetRootLayer().Save()
    del stage
    os.replace(temp, path)
    _forget_old_textures(folder, keep=path, prefix=NIGHT_POINTS_PREFIX, count=NIGHT_FILES_KEPT)
    return path

# ------------------------------------------------------------
# The material file of the night sky, one per set of values (and per template, which is part of the key).
def night_card_file(milky_texture, fade, strength, twinkle, glow):
    if _has_expression(milky_texture):
        raise ValueError("refusing a night sky texture path that contains an expression")
    values = dict(fade="{:.3f}".format(float(fade)), star_emission="{:.4f}".format(30.0 * float(strength)), twinkle="{:.3f}".format(float(twinkle)),
                  twinkle_speed="18", glow_alpha="{:.3f}".format(0.10 * float(glow)), glow_emission="{:.4f}".format(2.0 * float(strength)))
    values["milky_map"] = MILKY_MAP_MTLX.format(file=html.escape(milky_texture, quote=True), fade=values["fade"],
                                                milky_emission="{:.4f}".format(0.3 * float(strength))) if milky_texture else ""
    key = "|".join("{}={}".format(k, values[k]) for k in sorted(values)) + "|" + NIGHT_MTLX
    folder = _cache_folder()
    path = "{}/{}{}.mtlx".format(folder, NIGHT_CARD_PREFIX, hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12])
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(NIGHT_MTLX.format(**values))
        _forget_old_textures(folder, keep=path, prefix=NIGHT_CARD_PREFIX, count=40)
    return path
