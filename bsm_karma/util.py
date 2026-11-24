# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Small helpers for maths, colours, paths and the temporary folder, shared by the other modules of the tool.

# Houdini : 21 and 22

import atexit
import hou
import math
import os
import shutil
import sys
import tempfile
from .config import DATAS_HDRIS, SKY_DATAS_PREFIX

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

# ------------------------------------------------------------
# The folder of the HDRI pictures that come with the tool: datas/ next to the package when it is there, else the
# copies embedded in the HDA, written once in the user preferences folder. "" when there is none (installed copy).
def _datas_folder():
    pkg = sys.modules.get(__package__)
    beside = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datas")
    # in the HDA the module has no file of its own, only the embedded copies can answer
    if os.path.isfile(__file__) and all(os.path.isfile(os.path.join(beside, n)) for n in DATAS_HDRIS):
        return beside.replace("\\", "/")
    embedded = getattr(pkg, "EMBEDDED_DATAS", None)
    if not embedded:
        return ""
    try:
        folder = os.path.join(hou.text.expandString("$HOUDINI_USER_PREF_DIR"), "bsm_karma", "datas")
        os.makedirs(folder, exist_ok=True)
        for name, section in embedded.items():
            if name.startswith(SKY_DATAS_PREFIX):
                continue   # the sky pictures have their own folder, see _sky_data_file
            target = os.path.join(folder, name)
            if os.path.isfile(target):
                continue
            # written aside then renamed: a half written picture must never look complete
            with open(target + ".part", "wb") as handle:
                handle.write(section.binaryContents())
            os.replace(target + ".part", target)
        return folder.replace("\\", "/")
    except (OSError, hou.Error) as exc:
        from .debuglog import _debug   # imported here: debuglog imports this module
        _debug("datas folder not available: {}".format(exc))
        return ""

# ------------------------------------------------------------
# A picture of datas/Sky: next to the package, in the Houdini preferences, or written there from the HDA. "" when it is
# nowhere: the caller draws without it.
def _sky_data_file(name):
    candidates = []
    if os.path.isfile(__file__):
        candidates.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datas", "Sky", name))
    try:
        pref = hou.text.expandString("$HOUDINI_USER_PREF_DIR")
    except hou.Error:
        pref = ""
    if pref and not pref.startswith("$"):
        target = os.path.join(pref, "bsm_karma", "datas", "Sky", name)
        candidates.append(target)
        embedded = getattr(sys.modules.get(__package__), "EMBEDDED_DATAS", None) or {}
        section = embedded.get(SKY_DATAS_PREFIX + name)
        if section is not None and not os.path.isfile(target):
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target + ".part", "wb") as handle:
                    handle.write(section.binaryContents())
                os.replace(target + ".part", target)
            except OSError as exc:
                from .debuglog import _debug
                _debug("sky picture {} not written: {}".format(name, exc))
    for path in candidates:
        if os.path.isfile(path):
            return path.replace("\\", "/")
    return ""

# ------------------------------------------------------------
# The folder the tool keeps its files in (the Houdini preferences, bsm_karma): datas, materials, clouds, debug log. Made
# when it is not there yet; "" when there is no preferences folder.
def _tool_data_folder():
    try:
        pref = hou.text.expandString("$HOUDINI_USER_PREF_DIR")
    except hou.Error:
        return ""
    if not pref or pref.startswith("$"):
        return ""
    folder = os.path.join(pref, "bsm_karma")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return ""
    return folder.replace("\\", "/")

# ------------------------------------------------------------
def _default_hdri_path():
    folder = _datas_folder()
    return "{}/{}".format(folder, DATAS_HDRIS[0]) if folder else "$HIP/hdri/overcast_sky.exr"

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
