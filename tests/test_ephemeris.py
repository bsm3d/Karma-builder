# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Checks the ephemeris against dated events: sun, moon, planets, sidereal time, precession and the exact sky of a build.

# Revision : 21-10-2026 | Auteur : BSM
import math
import numpy as np
from _common import Checker, base_config, load_tool, scratch_dir

hou, k = load_tool()
import bsm_karma.ephemeris as e
import bsm_karma.nightsky as night

t = Checker("ephemeris")


def separation(a, b):
    return math.degrees(math.acos(max(-1, min(1, math.sin(a[1]) * math.sin(b[1]) + math.cos(a[1]) * math.cos(b[1]) * math.cos(a[0] - b[0])))))


jd = e.julian_date(2000, 1, 1, 12.0)
t.check("the Julian date of J2000 is 2451545.0", abs(jd - 2451545.0) < 1e-9, jd)
t.check("Greenwich sidereal time at J2000 is 18.6974 h", abs(e.local_sidereal_hours(jd, 0.0) - 18.6973746) < 1e-4, e.local_sidereal_hours(jd, 0.0))
t.check("the longitude is added to the sidereal time (15 degrees east is an hour)", abs((e.local_sidereal_hours(jd, 15.0) - e.local_sidereal_hours(jd, 0.0)) % 24 - 1.0) < 1e-9)
ra, dec = e.sun_equatorial(jd)
t.check("the sun at J2000 is at 18h45m, -23.03", abs(math.degrees(ra) / 15 - 18.752) < 0.01 and abs(math.degrees(dec) + 23.03) < 0.05, (math.degrees(ra) / 15, math.degrees(dec)))
noon = max(e.sky_snapshot(2024, 6, 21, 17.0 + step / 60.0, 43.65, -79.38)["sun"]["altitude"] for step in range(0, 40, 2))
t.check("Toronto, the 2024 solstice: the sun culminates at 69.8 degrees (90 - latitude + 23.44)", abs(noon - 69.79) < 0.15, noon)
equinox = e.sky_snapshot(2024, 3, 20, 6.5, 0.0, 0.0)
t.check("the equinox, on the equator at 6:30 UT: the sun has just risen, in the east", 0 < equinox["sun"]["altitude"] < 25 and 60 < equinox["sun"]["azimuth"] < 120, equinox["sun"])

full_jd = e.julian_date(2024, 1, 25, 17.9)
t.check("full moon 2024-01-25 17:54 UT: the moon is opposite the sun (within its latitude)", 173.0 < separation(e.sun_equatorial(full_jd), e.moon_equatorial(full_jd)[:2]) <= 180.0)
new_jd = e.julian_date(2024, 4, 8, 18.35)
t.check("new moon 2024-04-08 18:21 UT: the moon is on the sun (the eclipse of that day)", separation(e.sun_equatorial(new_jd), e.moon_equatorial(new_jd)[:2]) < 1.0)
old_jd = e.julian_date(2000, 1, 21, 4.67)
t.check("full moon 2000-01-21 04:40 UT", separation(e.sun_equatorial(old_jd), e.moon_equatorial(old_jd)[:2]) > 178.0)
t.check("the moon's distance stays between 55 and 64 earth radii", all(55.0 < e.moon_equatorial(e.julian_date(2024, 1, d, 0.0))[2] < 64.0 for d in range(1, 29)))
jd = e.julian_date(2020, 12, 21, 18.33)
t.check("the great conjunction of Jupiter and Saturn, 2020-12-21: 0.1 degree apart", separation(e.planet_equatorial("Jupiter", jd)[:2], e.planet_equatorial("Saturn", jd)[:2]) < 0.3)
closest = min(separation(e.planet_equatorial("Venus", e.julian_date(2023, 3, 1, h))[:2], e.planet_equatorial("Jupiter", e.julian_date(2023, 3, 1, h))[:2]) for h in range(24))
t.check("Venus and Jupiter, 2023-03-01: half a degree apart", closest < 0.8, closest)
jd = e.julian_date(2022, 12, 8, 5.0)
t.check("Mars at opposition, 2022-12-08: opposite the sun", separation(e.planet_equatorial("Mars", jd)[:2], e.sun_equatorial(jd)) > 174.0)
jd = e.julian_date(2023, 3, 1, 0.0)
t.check("magnitudes: Venus about -4, Jupiter about -2", -4.4 < e.planet_equatorial("Venus", jd)[2] < -3.6 and -2.4 < e.planet_equatorial("Jupiter", jd)[2] < -1.7)

# the sky of a place: Paris, 2024-01-25 17:54 UT (checked against the evening sky of that day)
snap = e.sky_snapshot(2024, 1, 25, 17.9, 48.85, 2.35)
planets = {p[0]: p for p in snap["planets"]}
jupiter = e.horizontal(planets["Jupiter"][1], planets["Jupiter"][2], snap["lst"], 48.85)
saturn = e.horizontal(planets["Saturn"][1], planets["Saturn"][2], snap["lst"], 48.85)
t.check("Paris that evening: the moon is rising in the east-north-east, full", 8 < snap["moon"]["altitude"] < 20 and 60 < snap["moon"]["azimuth"] < 85, snap["moon"])
t.check("Paris that evening: Jupiter high in the south, Saturn low in the south-west", 48 < jupiter[0] < 60 and 170 < jupiter[1] < 190 and 5 < saturn[0] < 20 and 225 < saturn[1] < 250, (jupiter, saturn))
t.check("Paris that evening: Venus and Mercury are not up (morning objects)", e.horizontal(planets["Venus"][1], planets["Venus"][2], snap["lst"], 48.85)[0] < 0
        and e.horizontal(planets["Mercury"][1], planets["Mercury"][2], snap["lst"], 48.85)[0] < 0)
t.check("the air mass is 1 at the zenith, 2 at 30 degrees, about 38 at the horizon", abs(e.airmass(90) - 1.0) < 0.01 and abs(e.airmass(30) - 2.0) < 0.05 and 35 < e.airmass(0) < 40)

stars_file = k._sky_data_file("stars.npz")
data = np.load(stars_file) if stars_file else None
if data is not None:
    i = int(np.argmax(data["dec"]))
    ra_d, dec_d = e.precess(np, data["ra"][i:i + 1], data["dec"][i:i + 1], e.julian_date(2026, 1, 1, 0.0), data["pm_ra"][i:i + 1], data["pm_dec"][i:i + 1])
    moved = math.degrees(float(np.hypot(float(dec_d[0] - data["dec"][i]), float(ra_d[0] - data["ra"][i]) * math.cos(data["dec"][i]))))
    t.check("precession moves the pole star about 0.15 degree in 26 years (up to 20 arc seconds a year in declination)", 0.05 < moved < 1.0, moved)
    sirius = int(np.argmin(data["vmag"]))
    r2, d2 = e.precess(np, data["ra"][sirius:sirius + 1], data["dec"][sirius:sirius + 1], e.julian_date(2000, 1, 1, 12.0))
    meridian = e.horizontal(float(r2[0]), float(d2[0]), math.degrees(float(r2[0])) / 15.0, 48.85)
    t.check("a star on the meridian: Sirius at its own sidereal time is due south, at 90 - latitude + declination",
            abs(meridian[1] - 180.0) < 0.01 and abs(meridian[0] - (90 - 48.85 + math.degrees(float(d2[0])))) < 0.01, meridian)
    rotation = night.celestial_rotation(np, 48.85, math.degrees(float(r2[0])) / 15.0)
    world = (night.star_direction(np, r2, d2) @ rotation.T)[0]
    alt = math.degrees(math.asin(world[1]))
    az = math.degrees(math.atan2(world[0], -world[2])) % 360.0
    t.check("the rotation of the sky agrees with the formulas (Sirius on the meridian)", abs(alt - meridian[0]) < 0.01 and abs(az - meridian[1]) < 0.01, (alt, az))
    lst = e.local_sidereal_hours(e.julian_date(2024, 1, 25, 17.9), 2.35)
    jup_ra, jup_dec = planets["Jupiter"][1], planets["Jupiter"][2]
    w = (night.star_direction(np, np.array([jup_ra]), np.array([jup_dec])) @ night.celestial_rotation(np, 48.85, lst).T)[0]
    a2, z2 = e.horizontal(jup_ra, jup_dec, lst, 48.85)
    t.check("the same for a planet at any time (east is +X, north is -Z)", abs(math.degrees(math.asin(w[1])) - a2) < 0.01 and abs(math.degrees(math.atan2(w[0], -w[2])) % 360.0 - z2) < 0.01, (a2, z2))

# the exact sky of a build: the sun takes its place from the date, the moon and the planets are in the picture
stage = hou.node("/stage")
out_dir = scratch_dir("ephemeris")
cam = stage.createNode("camera", "cam")
cfg = dict(base_config(out_dir), scene_mode="Environment", env_type="Physical Sky", camera_choice=cam.path(), geo_source="", enable_aovs=False,
           sky_exact=True, sky_year=2024, sky_month=1, sky_day=25, sky_hour=17.9, stars_latitude=48.85, stars_longitude=2.35,
           moon_enable=True, stars_enable=True, stars_milky=False, sky_elev=70.0, sky_azim=10.0)
logs = []
k.setup_karma_environment(cfg, logs.append)
sun_altitude = stage.node("physical_sky").parm("solar_altitude").eval() if stage.node("physical_sky").parm("solar_altitude") is not None else None
t.check("exact sky: the sun is where the date puts it, not where the sliders were", sun_altitude is not None and abs(sun_altitude + 12.7) < 0.3, sun_altitude)
t.check("exact sky: no warning, the moon and the night sky are built", not [l for l in logs if "WARN" in l] and stage.node("sky_moon") is not None and stage.node("sky_stars_ref") is not None,
        [l for l in logs if "WARN" in l])
if data is not None:
    prim = stage.node("karma_settings").stage().GetPrimAtPath("/World/Environment/NightStars/Stars")
    pts = np.array(prim.GetAttribute("points").Get(), dtype=float)
    direction = pts / np.linalg.norm(pts, axis=1)[:, None]
    target = np.array(e.world_vector(jupiter[0], jupiter[1]))
    nearest = math.degrees(math.acos(min(1.0, float(np.max(direction @ target)))))
    t.check("exact sky: a point stands where Jupiter is", nearest < 0.1, nearest)
    below = int((direction[:, 1] < math.sin(math.radians(-1.0)) - 1e-6).sum())
    t.check("exact sky: nothing under the horizon", below == 0, below)
    scint = np.array(prim.GetAttribute("primvars:scint").Get())
    altitudes = np.degrees(np.arcsin(direction[:, 1]))
    low, high = scint[(altitudes > 0) & (altitudes < 12)], scint[altitudes > 60]
    t.check("exact sky: stars twinkle more near the horizon than overhead", len(low) > 5 and len(high) > 5 and low.mean() > 2.0 * high.mean(),
            (float(low.mean()) if len(low) else None, float(high.mean()) if len(high) else None))
cfg2 = dict(cfg, sky_exact=False, sky_elev=45.0, sky_azim=100.0)
logs.clear()
k.setup_karma_environment(cfg2, logs.append)
t.check("exact sky off: the sliders are read again", abs(stage.node("physical_sky").parm("solar_altitude").eval() - 45.0) < 1e-6)
t.done()
