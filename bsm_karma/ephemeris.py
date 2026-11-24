# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Low precision ephemeris giving where the sun, the moon, the planets and the stars are for a date, a time and a place.

# Houdini : 21 and 22

import math

# Low precision theories (Paul Schlyter's elements with their main perturbations, Meeus for the sidereal time and the precession):
# the sun and the planets are good to a few arc minutes, the moon to about 2 arc minutes over a few centuries around 2000.
# Enough to put every body where the eye sees it; nothing here is meant for an observatory.
DEG = math.pi / 180.0

# planets: heliocentric elements at the epoch d = JD - 2451543.5 (1999 Dec 31.0): N, i, w, a, e, M each as (value, rate per day)
PLANETS = {
    "Mercury": ((48.3313, 3.24587e-5), (7.0047, 5.00e-8), (29.1241, 1.01444e-5), (0.387098, 0.0), (0.205635, 5.59e-10), (168.6562, 4.0923344368)),
    "Venus": ((76.6799, 2.46590e-5), (3.3946, 2.75e-8), (54.8910, 1.38374e-5), (0.723330, 0.0), (0.006773, -1.302e-9), (48.0052, 1.6021302244)),
    "Mars": ((49.5574, 2.11081e-5), (1.8497, -1.78e-8), (286.5016, 2.92961e-5), (1.523688, 0.0), (0.093405, 2.516e-9), (18.6021, 0.5240207766)),
    "Jupiter": ((100.4542, 2.76854e-5), (1.3030, -1.557e-7), (273.8777, 1.64505e-5), (5.20256, 0.0), (0.048498, 4.469e-9), (19.8950, 0.0830853001)),
    "Saturn": ((113.6634, 2.38980e-5), (2.4886, -1.081e-7), (339.3939, 2.97661e-5), (9.55475, 0.0), (0.055546, -9.499e-9), (316.9670, 0.0334442282)),
}
# what the eye sees: a colour for each (linear, for the point), from the usual descriptions
PLANET_COLORS = {"Mercury": (0.85, 0.82, 0.78), "Venus": (1.0, 0.97, 0.88), "Mars": (1.0, 0.55, 0.35), "Jupiter": (1.0, 0.92, 0.78), "Saturn": (1.0, 0.88, 0.62)}

# ------------------------------------------------------------
def julian_date(year, month, day, hours_ut):
    y, m = int(year), int(month)
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + float(day) + b - 1524.5 + float(hours_ut) / 24.0

# ------------------------------------------------------------
def local_sidereal_hours(jd, longitude_east):
    t = (jd - 2451545.0) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t - t * t * t / 38710000.0
    return ((gmst + float(longitude_east)) % 360.0) / 15.0

# ------------------------------------------------------------
def _kepler(m_deg, e):
    m = m_deg * DEG
    big_e = m + e * math.sin(m) * (1.0 + e * math.cos(m))
    for _ in range(30):
        step = (big_e - e * math.sin(big_e) - m) / (1.0 - e * math.cos(big_e))
        big_e -= step
        if abs(step) < 1e-12:
            break
    return big_e

# ------------------------------------------------------------
def _elements(table, d):
    return [value + rate * d for value, rate in table]

# ------------------------------------------------------------
def _ecliptic_to_equatorial(x, y, z, d):
    ecl = (23.4393 - 3.563e-7 * d) * DEG
    xe, ye, ze = x, y * math.cos(ecl) - z * math.sin(ecl), y * math.sin(ecl) + z * math.cos(ecl)
    return math.atan2(ye, xe) % (2.0 * math.pi), math.atan2(ze, math.hypot(xe, ye))

# ------------------------------------------------------------
# Geocentric sun on the ecliptic of the date: (x, y) in astronomical units, the distance and the true longitude.
def _sun_ecliptic(d):
    w = 282.9404 + 4.70935e-5 * d
    e = 0.016709 - 1.151e-9 * d
    m = 356.0470 + 0.9856002585 * d
    big_e = _kepler(m, e)
    xv, yv = math.cos(big_e) - e, math.sqrt(1.0 - e * e) * math.sin(big_e)
    r = math.hypot(xv, yv)
    lon = math.atan2(yv, xv) + w * DEG
    return r * math.cos(lon), r * math.sin(lon), r, lon, w + m

# ------------------------------------------------------------
def sun_equatorial(jd):
    d = jd - 2451543.5
    xs, ys, _, _, _ = _sun_ecliptic(d)
    return _ecliptic_to_equatorial(xs, ys, 0.0, d)

# ------------------------------------------------------------
# The moon: Schlyter's elements with the main perturbations of the longitude, the latitude and the distance (in earth radii).
def moon_equatorial(jd):
    d = jd - 2451543.5
    n, i, w, a, e, m = (125.1228 - 0.0529538083 * d, 5.1454, 318.0634 + 0.1643573223 * d, 60.2666, 0.054900, 115.3654 + 13.0649929509 * d)
    ms = 356.0470 + 0.9856002585 * d
    ls = 282.9404 + 4.70935e-5 * d + ms
    lm = n + w + m
    dd, f = lm - ls, lm - n
    big_e = _kepler(m, e)
    xv, yv = a * (math.cos(big_e) - e), a * math.sqrt(1.0 - e * e) * math.sin(big_e)
    v, r = math.atan2(yv, xv), math.hypot(xv, yv)
    vw = v + w * DEG
    nr, ir = n * DEG, i * DEG
    xh = r * (math.cos(nr) * math.cos(vw) - math.sin(nr) * math.sin(vw) * math.cos(ir))
    yh = r * (math.sin(nr) * math.cos(vw) + math.cos(nr) * math.sin(vw) * math.cos(ir))
    zh = r * math.sin(vw) * math.sin(ir)
    lon = math.degrees(math.atan2(yh, xh))
    lat = math.degrees(math.atan2(zh, math.hypot(xh, yh)))

    def s(angle):
        return math.sin(angle * DEG)

    lon += (-1.274 * s(m - 2 * dd) + 0.658 * s(2 * dd) - 0.186 * s(ms) - 0.059 * s(2 * m - 2 * dd) - 0.057 * s(m - 2 * dd + ms)
            + 0.053 * s(m + 2 * dd) + 0.046 * s(2 * dd - ms) + 0.041 * s(m - ms) - 0.035 * s(dd) - 0.031 * s(m + ms)
            - 0.015 * s(2 * f - 2 * dd) + 0.011 * s(m - 4 * dd))
    lat += (-0.173 * s(f - 2 * dd) - 0.055 * s(m - f - 2 * dd) - 0.046 * s(m + f - 2 * dd) + 0.033 * s(f + 2 * dd) + 0.017 * s(2 * m + f))
    r += -0.58 * math.cos((m - 2 * dd) * DEG) - 0.46 * math.cos(2 * dd * DEG)
    x, y, z = (r * math.cos(lon * DEG) * math.cos(lat * DEG), r * math.sin(lon * DEG) * math.cos(lat * DEG), r * math.sin(lat * DEG))
    ra, dec = _ecliptic_to_equatorial(x, y, z, d)
    return ra, dec, r

# ------------------------------------------------------------
# A planet seen from the earth: right ascension and declination of the date, the magnitude.
def planet_equatorial(name, jd):
    d = jd - 2451543.5
    n, i, w, a, e, m = _elements(PLANETS[name], d)
    big_e = _kepler(m, e)
    xv, yv = a * (math.cos(big_e) - e), a * math.sqrt(1.0 - e * e) * math.sin(big_e)
    v, r = math.atan2(yv, xv), math.hypot(xv, yv)
    vw = v + w * DEG
    nr, ir = n * DEG, i * DEG
    xh = r * (math.cos(nr) * math.cos(vw) - math.sin(nr) * math.sin(vw) * math.cos(ir))
    yh = r * (math.sin(nr) * math.cos(vw) + math.cos(nr) * math.sin(vw) * math.cos(ir))
    zh = r * math.sin(vw) * math.sin(ir)
    lon = math.degrees(math.atan2(yh, xh))
    lat = math.degrees(math.atan2(zh, math.hypot(xh, yh)))
    mj = 19.8950 + 0.0830853001 * d
    msat = 316.9670 + 0.0334442282 * d

    def s(angle):
        return math.sin(angle * DEG)

    def c(angle):
        return math.cos(angle * DEG)

    if name == "Jupiter":
        lon += (-0.332 * s(2 * mj - 5 * msat - 67.6) - 0.056 * s(2 * mj - 2 * msat + 21) + 0.042 * s(3 * mj - 5 * msat + 21)
                - 0.036 * s(mj - 2 * msat) + 0.022 * c(mj - msat) + 0.023 * s(2 * mj - 3 * msat + 52) - 0.016 * s(mj - 5 * msat - 69))
    elif name == "Saturn":
        lon += (0.812 * s(2 * mj - 5 * msat - 67.6) - 0.229 * c(2 * mj - 4 * msat - 2) + 0.119 * s(mj - 2 * msat - 3)
                + 0.046 * s(2 * mj - 6 * msat - 69) + 0.014 * s(mj - 3 * msat + 32))
        lat += -0.020 * c(2 * mj - 4 * msat - 2) + 0.018 * s(2 * mj - 6 * msat - 49)
    xh, yh, zh = (r * math.cos(lon * DEG) * math.cos(lat * DEG), r * math.sin(lon * DEG) * math.cos(lat * DEG), r * math.sin(lat * DEG))
    xs, ys, sun_distance, _, _ = _sun_ecliptic(d)
    xg, yg, zg = xh + xs, yh + ys, zh
    distance = math.sqrt(xg * xg + yg * yg + zg * zg)
    ra, dec = _ecliptic_to_equatorial(xg, yg, zg, d)
    # phase angle and visual magnitude (Mallama / the Astronomical Almanac forms)
    fv = math.degrees(math.acos(max(-1.0, min(1.0, (r * r + distance * distance - sun_distance * sun_distance) / (2.0 * r * distance)))))
    base = 5.0 * math.log10(r * distance)
    mag = {"Mercury": -0.36 + base + 0.027 * fv + 2.2e-13 * fv ** 6, "Venus": -4.34 + base + 0.013 * fv + 4.2e-7 * fv ** 3,
           "Mars": -1.51 + base + 0.016 * fv, "Jupiter": -9.25 + base + 0.014 * fv, "Saturn": -9.0 + base + 0.044 * fv}[name]
    return ra, dec, mag

# ------------------------------------------------------------
# Precession from J2000 to the date (Meeus 21.2), the proper motion first: arrays of right ascension and declination in radians.
def precess(np, ra, dec, jd, pm_ra=None, pm_dec=None):
    t = (jd - 2451545.0) / 36525.0
    if pm_ra is not None:
        years = t * 100.0
        ra = ra + pm_ra * years
        dec = dec + pm_dec * years
    zeta = (2306.2181 * t + 0.30188 * t * t + 0.017998 * t ** 3) / 3600.0 * DEG
    z = (2306.2181 * t + 1.09468 * t * t + 0.018203 * t ** 3) / 3600.0 * DEG
    theta = (2004.3109 * t - 0.42665 * t * t - 0.041833 * t ** 3) / 3600.0 * DEG
    a = np.cos(dec) * np.sin(ra + zeta)
    b = math.cos(theta) * np.cos(dec) * np.cos(ra + zeta) - math.sin(theta) * np.sin(dec)
    c = math.sin(theta) * np.cos(dec) * np.cos(ra + zeta) + math.cos(theta) * np.sin(dec)
    return (np.arctan2(a, b) + z) % (2.0 * math.pi), np.arcsin(np.clip(c, -1.0, 1.0))

# ------------------------------------------------------------
# Horizontal coordinates (altitude, azimuth from the north through the east, degrees) of a place of the sky of the date.
def horizontal(ra, dec, lst_hours, latitude):
    hour = (lst_hours * 15.0 * DEG) - ra
    lat = latitude * DEG
    sin_alt = math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(hour)
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))
    south = math.atan2(math.sin(hour), math.cos(hour) * math.sin(lat) - math.tan(dec) * math.cos(lat))
    return math.degrees(alt), (math.degrees(south) + 180.0) % 360.0

# ------------------------------------------------------------
# The unit vector of the tool's world (azimuth 0 is -Z, 90 is +X, up is +Y) for an altitude and an azimuth in degrees.
def world_vector(altitude, azimuth):
    alt, az = altitude * DEG, azimuth * DEG
    return (math.sin(az) * math.cos(alt), math.sin(alt), -math.cos(az) * math.cos(alt))

# ------------------------------------------------------------
# Everything for one instant and one place. The moon is the topocentric one (its parallax, up to a degree, is taken off the
# altitude). Planets come as (name, ra, dec, magnitude, colour) of the date.
def sky_snapshot(year, month, day, hours_ut, latitude, longitude_east):
    jd = julian_date(year, month, day, hours_ut)
    lst = local_sidereal_hours(jd, longitude_east)
    sun_ra, sun_dec = sun_equatorial(jd)
    sun_alt, sun_az = horizontal(sun_ra, sun_dec, lst, latitude)
    moon_ra, moon_dec, moon_distance = moon_equatorial(jd)
    moon_alt, moon_az = horizontal(moon_ra, moon_dec, lst, latitude)
    moon_alt -= math.degrees(math.asin(1.0 / moon_distance)) * math.cos(moon_alt * DEG)
    planets = []
    for name in PLANETS:
        ra, dec, mag = planet_equatorial(name, jd)
        planets.append((name, ra, dec, mag, PLANET_COLORS[name]))
    return {"jd": jd, "lst": lst, "sun": {"ra": sun_ra, "dec": sun_dec, "altitude": sun_alt, "azimuth": sun_az},
            "moon": {"ra": moon_ra, "dec": moon_dec, "altitude": moon_alt, "azimuth": moon_az, "distance": moon_distance},
            "planets": planets}

# ------------------------------------------------------------
# The settings of a build with the exact sky switched on (cfg "sky_exact", the date, the UT hour, the place): the sun's altitude
# and azimuth and the sidereal time are taken from the date instead of the sliders, and the snapshot rides along for the moon,
# the planets and the stars. Without it, cfg comes back as it is. It can be applied twice: the second one finds the same values.
def apply_exact_sky(cfg):
    if not cfg.get("sky_exact"):
        return cfg
    snapshot = sky_snapshot(int(cfg.get("sky_year", 2026)), int(cfg.get("sky_month", 10)), int(cfg.get("sky_day", 21)), float(cfg.get("sky_hour", 12.0)),
                            float(cfg.get("stars_latitude", 45.0)), float(cfg.get("stars_longitude", 0.0)))
    out = dict(cfg)
    out["sky_elev"], out["sky_azim"], out["stars_time"] = snapshot["sun"]["altitude"], snapshot["sun"]["azimuth"], snapshot["lst"]
    out["_snapshot"] = snapshot
    return out

# ------------------------------------------------------------
# The air the light goes through (Kasten and Young): 1 at the zenith, about 38 at the horizon.
def airmass(altitude_deg):
    h = max(float(altitude_deg), -1.0)
    return 1.0 / (math.sin(h * DEG) + 0.50572 * (6.07995 + h) ** -1.6364)
