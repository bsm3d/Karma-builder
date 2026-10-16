# util.py - BSM Karma Builder - small helpers: math, colors, paths, temp folder
# Version : 1.0.0 | Revision : 15-10-2026 | Auteur : BSM

import atexit
import hou
import math
import os
import shutil
import tempfile

#--------------------------------------------------------------------------------
def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


# ------------------------------------------------------------
def _kelvin_to_rgb(temp_k):
    t = _clamp(float(temp_k), 1000.0, 40000.0) / 100.0
    if t <= 66.0:
        r = 255.0
        g = 99.4708025861 * math.log(max(t, 1.0)) - 161.1195681661
        if t <= 19.0:
            b = 0.0
        else:
            b = 138.5177312231 * math.log(max(t - 10.0, 1.0)) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60.0) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60.0) ** -0.0755148492)
        b = 255.0

    return (
        _clamp(r / 255.0, 0.0, 1.0),
        _clamp(g / 255.0, 0.0, 1.0),
        _clamp(b / 255.0, 0.0, 1.0),
    )


# --------------------------------------------------
def _apply_tint(rgb, tint):
    t = _clamp(float(tint), -1.0, 1.0)
    if t >= 0.0:
        m = (1.0 + t * 0.45, 1.0 - t * 0.35, 1.0 + t * 0.45)
    else:
        tg = abs(t)
        m = (1.0 - tg * 0.25, 1.0 + tg * 0.45, 1.0 - tg * 0.25)

    return (
        _clamp(rgb[0] * m[0], 0.0, 2.0),
        _clamp(rgb[1] * m[1], 0.0, 2.0),
        _clamp(rgb[2] * m[2], 0.0, 2.0),
    )


# --------------------------------------------------------------------------------
def _apply_saturation(rgb, saturation):
    sat = _clamp(float(saturation), 0.0, 2.0)
    lum = rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722
    return (
        _clamp(lum + (rgb[0] - lum) * sat, 0.0, 2.0),
        _clamp(lum + (rgb[1] - lum) * sat, 0.0, 2.0),
        _clamp(lum + (rgb[2] - lum) * sat, 0.0, 2.0),
    )


# ATTENTION -> expandString exécute les backticks (`system("...")`) et un parm aussi quand son node calcule.
# Tout ce que l'utilisateur n'a pas tapé (drop, métadonnées de catalogue) est refusé s'il en contient.


# --------------------------------------------------
def _has_expression(text):
    return "`" in str(text)


# --------------------------------------------------
# A file name can carry a backtick expression (an archive from anywhere may hold such names) and expandString
# would run it as soon as the path is expanded. Whatever the user did not type goes through here first.
def _expand_plain_path(path):
    if _has_expression(path):
        raise ValueError("the path contains a backtick expression, refused: {!r}".format(path))
    return hou.text.expandString(path)


_private_temp = None


# ------------------------------------------------------------
# ATTENTION -> des noms prévisibles dans le temp partagé permettent à un autre utilisateur de pré-créer un lien,
# d'où un dossier privé par session
def _private_temp_dir():
    global _private_temp
    if _private_temp is None or not os.path.isdir(_private_temp):
        _private_temp = tempfile.mkdtemp(prefix="bsm_karma_")
        atexit.register(shutil.rmtree, _private_temp, True)
    return _private_temp


# --------------------------------------------------
def _is_inside(folder, path):
    folder = os.path.normcase(os.path.realpath(folder))
    path = os.path.normcase(os.path.realpath(path))
    try:
        return os.path.commonpath([folder, path]) == folder
    except ValueError:  # different drives
        return False


#----------------------------------------------------------------------
def _normalized_path(path):
    return os.path.normcase(os.path.normpath(hou.text.expandString(path)))


#--------------------------------------------------------------------------------
def _normalize_output_path_extension(path, output_format):
    ext = ".exr" if str(output_format).upper() == "EXR" else ".png"
    root, cur_ext = os.path.splitext(path)
    # "beauty.$F4" has no extension: the frame token must survive, not be swapped for ".exr"
    if not cur_ext or "$" in cur_ext or "`" in cur_ext:
        return path + ext
    if cur_ext.lower() != ext:
        return root + ext
    return path
