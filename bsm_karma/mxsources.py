# Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Download MaterialX materials from ambientCG and Poly Haven (no extra install)
# Houdini : 21 and 22 (plain Python, also runs without Houdini)
# Version : 1.0.0
#
# The requests made here follow what the open source materialxmaterials tool (Bernard Kwok, Apache 2.0,
# https://pypi.org/project/materialxmaterials/) does, minus its MaterialX dependency: ambientCG gives a list of
# download links and a zip per material, Poly Haven gives a JSON list of files per asset. Everything that comes back
# from a server is untrusted: hosts are limited, sizes are capped and paths are checked before a file is written.

import csv
import io
import os
import re
import zipfile
from urllib.parse import parse_qs, urlparse

USER_AGENT = "Karma-Builder/1.0"
ALLOWED_HOST_SUFFIXES = ("ambientcg.com", "polyhaven.com", "polyhaven.org")
TIMEOUT = (10, 60)
MAX_FILE_BYTES = 800 * 1024 ** 2
MAX_LIST_BYTES = 60 * 1024 ** 2
MAX_FILES = 200
ZIP_MAX_FILES = 5000
ZIP_MAX_BYTES = 4 * 1024 ** 3
CHUNK = 64 * 1024

AMBIENTCG_LIST_URL = "https://ambientCG.com/api/v2/downloads_csv"
POLYHAVEN_ASSETS_URL = "https://api.polyhaven.com/assets"
POLYHAVEN_FILES_URL = "https://api.polyhaven.com/files"

# no leading dash or dot, no path separator
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
AMBIENTCG_RESOLUTIONS = ("1", "2", "4", "8")
POLYHAVEN_RESOLUTIONS = ("1k", "2k", "4k", "8k")


class DownloadError(Exception):
    pass


class DownloadCancelled(Exception):
    pass


# ------------------------------------------------------------
def _check_url(url):
    parts = urlparse(str(url))
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES):
        raise DownloadError("refusing an address that is not https on ambientCG or Poly Haven: {}".format(str(url)[:120]))


# ------------------------------------------------------------
def _fetch(session, url, cancel, limit, params=None):
    _check_url(url)
    response = session.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, stream=True)
    status = getattr(response, "status_code", 200)
    if status == 404:
        raise DownloadError("the server has nothing at {} (HTTP 404): check the name".format(urlparse(str(url)).path[:80]))
    if status >= 400:
        raise DownloadError("the server answered HTTP {} for {}".format(status, urlparse(str(url)).path[:80]))
    response.raise_for_status()
    declared = response.headers.get("Content-Length") if hasattr(response, "headers") else None
    if declared and str(declared).isdigit() and int(declared) > limit:
        raise DownloadError("the file is larger than {} MB".format(limit // 1024 ** 2))
    chunks, size = [], 0
    for chunk in response.iter_content(chunk_size=CHUNK):
        if cancel is not None and cancel.is_set():
            raise DownloadCancelled()
        size += len(chunk)
        if size > limit:
            raise DownloadError("the file is larger than {} MB".format(limit // 1024 ** 2))
        chunks.append(chunk)
    return b"".join(chunks)


# ------------------------------------------------------------
def check_name(name):
    name = str(name).strip()
    if not NAME_RE.match(name):
        raise ValueError("the name must be letters, digits, _ . - and cannot start with a dash or a dot (for example WoodFloor038)")
    return name


# ------------------------------------------------------------
def relative_path(path):
    text = str(path).replace("\\", "/")
    parts = text.split("/")
    if (not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text) or "`" in text
            or any(part in ("", ".", "..") for part in parts)):
        raise DownloadError("a file path from the server is not safe: {!r}".format(text[:100]))
    return "/".join(parts)


# ------------------------------------------------------------
def _write(folder, rel, data):
    root = os.path.realpath(folder)
    path = os.path.realpath(os.path.join(root, relative_path(rel)))
    if os.path.commonpath([root, path]) != root:
        raise DownloadError("a file path leaves its folder: {!r}".format(rel[:100]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


# ------------------------------------------------------------
def safe_extract(zip_path, base_folder):
    target = os.path.join(base_folder, os.path.splitext(os.path.basename(zip_path))[0])
    os.makedirs(target, exist_ok=True)
    root = os.path.realpath(target)
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        if len(infos) > ZIP_MAX_FILES or sum(info.file_size for info in infos) > ZIP_MAX_BYTES:
            raise ValueError("{} is too large to unpack".format(os.path.basename(zip_path)))
        for info in infos:
            name = info.filename
            if "`" in name:
                raise ValueError("{} holds a file name with a backtick, refused".format(os.path.basename(zip_path)))
            destination = os.path.realpath(os.path.join(root, name))
            if os.path.commonpath([root, destination]) != root:
                raise ValueError("{} holds a path that leaves its folder, refused".format(os.path.basename(zip_path)))
        archive.extractall(root)
    return target


# ------------------------------------------------------------
def list_files(folder, suffix):
    found = []
    for current, _, names in os.walk(folder):
        for name in names:
            if name.lower().endswith(suffix):
                found.append(os.path.join(current, name))
    return found


# ------------------------------------------------------------
# ambientCG: one CSV row per material, resolution and format (assetId, downloadAttribute such as 2K-PNG, downloadLink).
def ambientcg_catalog(session, cancel=None):
    data = _fetch(session, AMBIENTCG_LIST_URL, cancel, MAX_LIST_BYTES,
                  params={"method": "PBRPhotogrammetry", "type": "Material", "sort": "Alphabet"})
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8", errors="replace"))))
    return [row for row in rows if row.get("assetId") and row.get("downloadAttribute") and row.get("downloadLink")]


# ------------------------------------------------------------
def ambientcg_names(rows):
    return sorted({row["assetId"] for row in rows if NAME_RE.match(row["assetId"])}, key=str.lower)


# ------------------------------------------------------------
def download_ambientcg(session, rows, asset_id, resolution, fmt, folder, log, cancel=None):
    asset_id = check_name(asset_id)
    if str(resolution) not in AMBIENTCG_RESOLUTIONS or str(fmt).upper() not in ("PNG", "JPG", "JPEG"):
        raise ValueError("resolution or format not offered by ambientCG")
    wanted = "{}K-{}".format(resolution, "JPG" if str(fmt).upper() == "JPEG" else str(fmt).upper())
    matches = [row for row in rows if row["assetId"] == asset_id]
    if not matches:
        raise DownloadError("ambientCG has no material called {}".format(asset_id))
    chosen = [row for row in matches if row["downloadAttribute"].upper() == wanted]
    if not chosen:
        raise DownloadError("{} is not offered as {}; available: {}".format(
            asset_id, wanted, ", ".join(sorted(row["downloadAttribute"] for row in matches))))
    url = chosen[0]["downloadLink"]
    log("Downloading {} ({}) from ambientCG ...".format(asset_id, wanted))
    data = _fetch(session, url, cancel, MAX_FILE_BYTES)
    name = (parse_qs(urlparse(url).query).get("file") or [""])[0]
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.zip$", name):
        name = "{}_{}.zip".format(asset_id, wanted)
    os.makedirs(folder, exist_ok=True)
    path = _write(folder, name, data)
    if not zipfile.is_zipfile(path):
        raise DownloadError("what ambientCG sent is not a zip file")
    log("Saved {} ({:.1f} MB).".format(name, len(data) / 1024 ** 2))
    return path


# ------------------------------------------------------------
def polyhaven_catalog(session, cancel=None):
    import json
    data = _fetch(session, POLYHAVEN_ASSETS_URL, cancel, MAX_LIST_BYTES, params={"type": "textures"})
    assets = json.loads(data.decode("utf-8", errors="replace"))
    if not isinstance(assets, dict):
        raise DownloadError("Poly Haven sent an answer that is not a list of assets")
    return assets


# ------------------------------------------------------------
def polyhaven_names(assets):
    return sorted((name for name in assets if NAME_RE.match(str(name))), key=str.lower)


# ------------------------------------------------------------
# The .mtlx of an asset and its textures, in <folder>/<id>_materialx/. EXR textures are taken as PNG when the server has
# them, like materialxmaterials does, and the .mtlx is changed to match. Returns the .mtlx path.
def download_polyhaven(session, asset_id, resolution, folder, log, cancel=None):
    import json
    asset_id = check_name(asset_id)
    if str(resolution) not in POLYHAVEN_RESOLUTIONS:
        raise ValueError("resolution not offered by Poly Haven")
    log("Looking for {} on Poly Haven ...".format(asset_id))
    files = json.loads(_fetch(session, "{}/{}".format(POLYHAVEN_FILES_URL, asset_id), cancel, MAX_LIST_BYTES).decode("utf-8", errors="replace"))
    mtlx_by_res = files.get("mtlx") if isinstance(files, dict) else None
    if not mtlx_by_res:
        raise DownloadError("{} has no MaterialX files on Poly Haven".format(asset_id))
    entry = (mtlx_by_res.get(resolution) or {}).get("mtlx") if isinstance(mtlx_by_res.get(resolution), dict) else None
    if not entry or not entry.get("url"):
        raise DownloadError("{} has no MaterialX at {}; available: {}".format(asset_id, resolution, ", ".join(sorted(mtlx_by_res))))
    textures = {path: info.get("url") for path, info in (entry.get("include") or {}).items() if isinstance(info, dict) and info.get("url")}
    if len(textures) + 1 > MAX_FILES:
        raise DownloadError("too many files for one material")

    mtlx_text = _fetch(session, entry["url"], cancel, MAX_LIST_BYTES).decode("utf-8", errors="replace")
    target = os.path.join(folder, "{}_materialx".format(asset_id))
    renames = {}
    for index, (rel, url) in enumerate(sorted(textures.items()), 1):
        relative_path(rel)
        data = None
        if rel.lower().endswith(".exr"):
            png_url = url.replace("/exr/", "/png/").replace(".exr", ".png")
            try:
                data = _fetch(session, png_url, cancel, MAX_FILE_BYTES)
                renames[os.path.basename(rel)] = os.path.splitext(os.path.basename(rel))[0] + ".png"
                rel = os.path.splitext(rel)[0] + ".png"
            except (DownloadError, OSError):   # the PNG is only a preference: the EXR is used when the server has none
                data = None
        if data is None:
            data = _fetch(session, url, cancel, MAX_FILE_BYTES)
        log("[{}/{}] {}".format(index, len(textures), rel))
        _write(target, rel, data)
    for old, new in renames.items():
        mtlx_text = mtlx_text.replace(old, new)
    return _write(target, "{}.mtlx".format(asset_id), mtlx_text.encode("utf-8"))
