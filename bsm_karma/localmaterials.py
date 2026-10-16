# localmaterials.py - BSM Karma Builder - downloaded material files dragged onto prims: payload, checks, thumbnails
# Version : 2026.10.15.1 | Revision : 16-10-2026 | Auteur : BSM

import json
import os
import xml.etree.ElementTree as ElementTree
from hutil.Qt import QtCore, QtGui
from .util import _has_expression, _is_inside

LOCAL_FILE_KEY = "bsm_local_files"
MATERIAL_SUFFIXES = (".mtlx", ".usd", ".usda", ".usdc", ".usdz")
MAX_FILES_PER_DROP = 50
MAX_MTLX_BYTES = 4 * 1024 * 1024
PICTURE_SUFFIXES = (".png", ".jpg", ".jpeg")
PICTURE_HINTS = ("color", "colour", "diff", "albedo", "basecolor", "base_color")
PICTURE_SKIP = ("normal", "nor_", "rough", "disp", "height", "_ao", "metal", "opacity", "bump", "_gl", "_dx")
MTLX_MATERIAL_ROOT = "/MaterialX/Materials"


# ------------------------------------------------------------
# What a drag from the list of downloaded materials carries: plain file paths, checked again where they are dropped.
def local_payload(paths):
    return json.dumps({LOCAL_FILE_KEY: [str(path).replace("\\", "/") for path in paths]})


# ------------------------------------------------------------
def is_local_payload(text):
    try:
        data = json.loads(text)
    except ValueError:
        return False
    return isinstance(data, dict) and LOCAL_FILE_KEY in data


# ------------------------------------------------------------
# Material names of a .mtlx file read as text, for a Houdini whose USD cannot open the file. A file with a DOCTYPE or
# entities is refused (entity expansion), and so is a big one.
def mtlx_materials(path):
    if os.path.getsize(path) > MAX_MTLX_BYTES:
        return []
    with open(path, "rb") as handle:
        data = handle.read()
    if b"<!doctype" in data.lower() or b"<!entity" in data.lower():
        return []
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return []
    found = []
    for element in root.iter("surfacematerial"):
        name = element.get("name")
        if name:
            found.append((name, "{}/{}".format(MTLX_MATERIAL_ROOT, name)))
    return found


# ------------------------------------------------------------
# Material descriptors (label, file_path, prim_path, id) of the files of a drop, and the reason for each file that does
# not give one. The drop can come from any application: only material files that lie in one of the `roots` (the
# download folders) are taken. `lister(path)` is the USD reader of Houdini, the text reader is the fallback.
def local_assets(text, roots, lister=None):
    assets, failures = [], []
    try:
        names = json.loads(text).get(LOCAL_FILE_KEY, [])
    except (ValueError, AttributeError):
        return [], ["unreadable drop"]
    if not isinstance(names, list):
        return [], ["unreadable drop"]
    folders = [folder for folder in roots if folder and os.path.isdir(folder)]
    for name in names[:MAX_FILES_PER_DROP]:
        if not isinstance(name, str) or not name:
            continue
        label = os.path.basename(name)
        if _has_expression(name):
            failures.append("{}: refused, the path contains an expression".format(label))
            continue
        if not os.path.isabs(name) or not name.lower().endswith(MATERIAL_SUFFIXES) or not os.path.isfile(name):
            failures.append("{}: not a material file".format(label))
            continue
        if not any(_is_inside(folder, name) for folder in folders):
            failures.append("{}: outside the download folder".format(label))
            continue
        materials = []
        if lister is not None:
            try:
                materials = lister(name)
            except Exception:   # pxr raises Tf.ErrorException, which has no narrower base here
                materials = []
        if not materials and name.lower().endswith(".mtlx"):
            materials = mtlx_materials(name)
        if not materials:
            failures.append("{}: no material found in the file".format(label))
            continue
        material, prim = materials[0]
        assets.append({"label": material, "file_path": name, "prim_path": prim, "id": prim})
    return assets, failures


# ------------------------------------------------------------
# A picture of the material for its thumbnail: the color map next to the .mtlx file, or in a textures folder below it.
def preview_picture(mtlx_path):
    folder = os.path.dirname(mtlx_path)
    candidates = []
    for sub in (folder, os.path.join(folder, "textures"), os.path.join(folder, "Textures")):
        try:
            names = sorted(os.listdir(sub))
        except OSError:
            continue
        candidates.extend(os.path.join(sub, n) for n in names if n.lower().endswith(PICTURE_SUFFIXES))
    wanted = [p for p in candidates if any(h in os.path.basename(p).lower() for h in PICTURE_HINTS)
              and not any(s in os.path.basename(p).lower() for s in PICTURE_SKIP)]
    if wanted:
        return wanted[0]
    plain = [p for p in candidates if not any(s in os.path.basename(p).lower() for s in PICTURE_SKIP)]
    return plain[0] if plain else ""


# ------------------------------------------------------------
# Square thumbnail, cropped from the middle of the picture; an empty icon when it cannot be read.
def thumbnail(picture, edge):
    if not picture:
        return QtGui.QIcon()
    reader = QtGui.QImageReader(picture)
    if hasattr(reader, "setAllocationLimit"):
        reader.setAllocationLimit(0)
    size = reader.size()
    if size.width() < 1 or size.height() < 1:
        return QtGui.QIcon()
    scale = float(edge * 2) / min(size.width(), size.height())
    if scale < 1.0:
        reader.setScaledSize(QtCore.QSize(max(1, int(size.width() * scale)), max(1, int(size.height() * scale))))
    image = reader.read()
    if image.isNull():
        return QtGui.QIcon()
    pixmap = QtGui.QPixmap.fromImage(image).scaled(edge, edge, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
    x, y = max(0, (pixmap.width() - edge) // 2), max(0, (pixmap.height() - edge) // 2)
    return QtGui.QIcon(pixmap.copy(x, y, edge, edge))
