# buildinfo.py - BSM Karma Builder - which build is running, and where it was loaded from
# Version : 2026.10.15.1 | Revision : 16-10-2026 | Auteur : BSM
#
# The build id is a short hash of the source of every module of the package. It changes with any change of the code,
# whether the tool runs from a folder, from scripts/python or from the HDA, and it is the same for the same code
# (line endings do not count). Compare it with tools/build_id.py run on the repository.

import hashlib
import os

CONFIG_MODULE = "config"


# ------------------------------------------------------------
def _normalized(text):
    return text.replace("\r\n", "\n")


# ------------------------------------------------------------
# {module name: source}. From the folder of the package, or from the sources the HDA carries.
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


# the id of what was loaded: read once, when the package is imported
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
def build_location():
    path = globals().get("__file__") or ""
    if os.path.isfile(path):
        return os.path.dirname(os.path.abspath(path)).replace("\\", "/")
    return "embedded in the HDA"


# ------------------------------------------------------------
def build_summary(version):
    return "BSM Karma Builder {} | build {} | from {}: {}".format(version, BUILD_ID, build_origin(), build_location())
