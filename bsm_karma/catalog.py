# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Material catalog drops, trust checks and stage prims
# Houdini : 21 and 22
# Version : 1.0.0

import hashlib
import hou
import json
import os
from .config import AMD_LIBRARY_URL, AMD_SOURCE_ID, CATALOG_SOURCE_SUFFIXES, MATERIAL_DEFAULT_ROOT, STAGE_TARGET_LIMIT
from .util import _has_expression, _is_inside, _normalized_path, _private_temp_dir

# ------------------------------------------------------------
# ATTENTION -> la source AMD de Houdini fait ses requêtes sans timeout (et sa liste sans vérification TLS),
# on teste donc la connexion avant, sinon une machine hors ligne gèle l'interface. Renvoie (ok, reason).
def _amd_library_reachable(timeout=6.0):
    try:
        import requests
    except ImportError:
        return True, ""  # cannot check: let Houdini try
    try:
        response = requests.get(AMD_LIBRARY_URL + "/materials/count/", timeout=timeout)
        response.raise_for_status()
        return True, ""
    except requests.RequestException as exc:
        return False, str(exc).splitlines()[0][:140]


# ------------------------------------------------------------
# Reason a payload's source must not be built, or "". An AMD source with a payload-supplied folder would
# extract a package wherever the payload says, so it must be the folder connected in the Materials tab.
def _catalog_source_problem(identifier, args, amd_folder):
    if _has_expression(identifier) or _has_expression(args):
        return "the source contains an expression"
    if identifier == AMD_SOURCE_ID:
        if not amd_folder:
            return "connect the AMD MaterialX Library from this tab first"
        if os.path.normcase(os.path.realpath(hou.text.expandString(str(args)))) != os.path.normcase(os.path.realpath(amd_folder)):
            return "the download folder is not the one connected in this tab"
        return ""
    path = hou.text.expandString(str(identifier))
    if path.lower().endswith(CATALOG_SOURCE_SUFFIXES) and os.path.isfile(path):
        return ""
    return "unsupported material source"


# wrapper layer -> the .mtlx it stands for, so a drop references the real file
_CATALOG_WRAPPERS = {}


# --------------------------------------------------------------------------------
# The gallery only takes USD stages: wrap a .mtlx in a layer that sublayers it.
def _material_catalog_file(path):
    if os.path.splitext(path)[1].lower() != ".mtlx":
        return path
    if "@" in path or "\n" in path or "\r" in path:
        raise ValueError("the path contains a character that cannot be written in a USD asset reference")
    key = hashlib.md5(path.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    wrapper = os.path.join(_private_temp_dir(), "catalog_{}.usda".format(key)).replace("\\", "/")
    with open(wrapper, "w", encoding="utf-8") as handle:
        handle.write("#usda 1.0\n(\n    subLayers = [@{}@]\n)\n".format(path.replace("\\", "/")))
    _CATALOG_WRAPPERS[_normalized_path(wrapper)] = path
    return wrapper


# ------------------------------------------------------------------------------------------
# Drag payload to material descriptors (label, file_path, prim_path, id). The payload is untrusted, any
# application can start a drag, and so is remote catalog metadata: see the trust checks. `source_factory` is for
# tests.
def _parse_catalog_drop(json_text, amd_folder=None, source_factory=None):
    factory = source_factory or hou.AssetGalleryDataSource
    data = json.loads(json_text)
    assets = []
    failures = []
    fields = zip(
        data.get("ids", []), data.get("assettypes", []), data.get("labels", []),
        data.get("filepaths", []), data.get("asset_data", []), data.get("sources", []),
    )
    for ident, asset_type, label, file_path, asset_data, source in fields:
        if asset_type != "material":
            continue
        try:
            blind = json.loads(asset_data) if asset_data else {}
        except ValueError:
            blind = {}
        texts = (ident, label, file_path, blind.get("name", ""), blind.get("refprimpath", ""))
        if any(_has_expression(text) for text in texts):
            failures.append("{}: refused, a value contains an expression".format(label))
            continue
        problem = _catalog_source_problem(source[0], source[1], amd_folder)
        if problem:
            failures.append("{}: {}".format(label, problem))
            continue
        try:
            source_obj = factory(source[0], source[1])
            if source[0] == AMD_SOURCE_ID:
                # The remote metadata decides where the package is written: it must stay in the download folder.
                target = source_obj.filePath(ident)
                if not target or _has_expression(target) or not _is_inside(amd_folder, hou.text.expandString(target)) \
                        or not _is_inside(amd_folder, hou.text.expandString(file_path)):
                    failures.append("{}: the material path is outside the download folder".format(label))
                    continue
            error = source_obj.prepareItemForUse(ident)
        except hou.Error as exc:
            error = str(exc)
        if error:
            failures.append("{}: {}".format(label, error))
            continue
        assets.append({
            "label": blind.get("name", label),
            "file_path": _CATALOG_WRAPPERS.get(_normalized_path(file_path), file_path),
            "prim_path": blind.get("refprimpath", ""),
            "id": ident,
        })
    return assets, failures


# ------------------------------------
def _list_materials_in_file(file_path):
    from pxr import Usd, UsdShade
    stage = Usd.Stage.Open(hou.text.expandString(file_path))
    if stage is None:
        return []
    return [(prim.GetName(), str(prim.GetPath())) for prim in stage.Traverse() if prim.IsA(UsdShade.Material)]


# --------------------------------------------------
def _stage_target_prims(stage, limit=STAGE_TARGET_LIMIT):
    from pxr import UsdGeom, UsdShade
    # /World/Environment is the tool's own fog and clouds
    skip_roots = ("/Render", "/lights", "/cameras", "/World/Environment", MATERIAL_DEFAULT_ROOT)
    result = []
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if any(path == root or path.startswith(root + "/") for root in skip_roots):
            continue
        if prim.IsA(UsdShade.Material) or prim.IsA(UsdShade.Shader):
            continue
        if not (prim.IsA(UsdGeom.Gprim) or prim.IsA(UsdGeom.Xform) or prim.IsA(UsdGeom.Scope)
                or prim.IsA(UsdGeom.PointInstancer)):
            continue
        result.append((path, str(prim.GetPath().GetParentPath()), prim.GetTypeName()))
        if len(result) >= limit:
            break
    return result


# ------------------------------------------------------------
def _bound_material_name(stage, prim_path):
    from pxr import UsdShade
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        return ""
    material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    return material.GetPath().name if material else ""
