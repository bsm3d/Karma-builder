# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Computes the build id as a short hash of the package sources and reports which build is running and where it was loaded from.

# Houdini : 21 and 22 (plain Python, also runs without Houdini)
# Short hash of the source of every module, line endings ignored: the same code gives the same id, whatever the way it is loaded.
# Compare with tools/build_id.py run on the repository.

import hashlib
import os

CONFIG_MODULE = "config"

# ------------------------------------------------------------
def _normalized(text):
    return text.replace("\r\n", "\n")

# ------------------------------------------------------------
def package_sources(folder=None):
    folder = folder or os.path.dirname(os.path.abspath(globals().get("__file__") or ""))
    if folder and os.path.isfile(os.path.join(folder, CONFIG_MODULE + ".py")):
        sources = {}
        for name in sorted(os.listdir(folder)):
            if name.endswith(".py"):
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    sources[name[:-3]] = _normalized(handle.read())
        return sources
    spec = globals().get("__spec__")
    loader_sources = getattr(getattr(spec, "loader", None), "sources", None)
    if loader_sources:
        return {name: _normalized(text) for name, text in loader_sources.items()}
    return {}

# ------------------------------------------------------------
def _id_of(sources):
    digest = hashlib.sha1(usedforsecurity=False)
    for name in sorted(sources):
        digest.update("{}\0{}\0".format(name, sources[name]).encode("utf-8"))
    return digest.hexdigest()[:8] if sources else "unknown"

# ------------------------------------------------------------
def folder_build_id(folder=None):
    return _id_of(package_sources(folder))

BUILD_ID = folder_build_id()

# ------------------------------------------------------------
def build_origin():
    name = __name__.split(".")[0]
    path = globals().get("__file__") or ""
    if name.endswith("_hda"):
        return "the HDA (code embedded in the asset)"
    folder = os.path.dirname(os.path.abspath(path)).replace("\\", "/")
    if "/scripts/python/" in folder + "/":
        return "an installed copy (scripts/python)"
    return "a folder"

# ------------------------------------------------------------
def build_tag():
    origin = build_origin()
    word = "HDA" if origin.startswith("the HDA") else ("installed" if origin.startswith("an installed") else "folder")
    return "build {}, {}".format(BUILD_ID, word)

# ------------------------------------------------------------
def build_location():
    path = globals().get("__file__") or ""
    if os.path.isfile(path):
        return os.path.dirname(os.path.abspath(path)).replace("\\", "/")
    return "embedded in the HDA"

# ------------------------------------------------------------
def build_summary(version):
    return "Karma Builder {} | build {} | from {}: {}".format(version, BUILD_ID, build_origin(), build_location())
