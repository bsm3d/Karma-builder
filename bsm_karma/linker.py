# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Material Linker rules and references in the stage, and the material edit nodes wired into the render chain.

# Houdini : 21 and 22

import hou
import re
import uuid
from .config import (MATERIAL_DEFAULT_ROOT, MATERIAL_EDIT_COUNT_PARM, MATERIAL_EDIT_ENABLE_PARM, MATERIAL_EDIT_LOAD_PARM,
                     MATERIAL_EDIT_NODE, MATERIAL_EDIT_PATH_PARM, MATERIAL_EDIT_TYPE, MATERIAL_LINK_TYPE)
from .nodeutil import _base_node_type_name, _is_tool_node_candidate, _mark_tool_node
from .util import _has_expression

# --------------------------------------------------
# bug trouvé et fixé: an object made in the viewport is wired after the displayed node, that is after Karma Render Settings: the
# Material Linker (upstream) never sees it, nor does the final render (it reads the stage at Karma Render Settings). The nodes
# of the user wired after it: the first of each chain (the heads, plugged into Karma Render Settings) and the last (the tips).
def _loose_geometry(stage):
    settings = stage.node("karma_settings") if stage is not None else None
    if settings is None:
        return [], []
    seen, todo = {}, list(settings.outputs())
    while todo:
        node = todo.pop(0)
        if node.path() in seen or _is_tool_node_candidate(node, node.name()):
            continue
        seen[node.path()] = node
        todo.extend(node.outputs())
    nodes = list(seen.values())
    heads = [n for n in nodes if any(source is not None and source.path() == settings.path() for source in n.inputs())]
    tips = [n for n in nodes if not any(o.path() in seen for o in n.outputs())]
    return heads, tips

# --------------------------------------------------
# Unplugs the heads from Karma Render Settings (their own chains stay as they are) and merges the tips into a node of the user's,
# named my_objects: it is the Geometry source of the build, which puts it before the materials.
def _adopt_loose_geometry(stage, heads, tips):
    settings = stage.node("karma_settings")
    for head in heads:
        for index, source in enumerate(head.inputs()):
            if source is not None and settings is not None and source.path() == settings.path():
                head.setInput(index, None)
    merge = stage.createNode("merge", "my_objects")
    for index, tip in enumerate(tips):
        merge.setInput(index, tip)
    merge.moveToGoodPosition()
    return merge

# --------------------------------------------------
def _material_linker_node(stage):
    if stage is None:
        return None
    node = stage.node("material_linker")
    if node is not None and _base_node_type_name(node) == "materiallinker" and _is_tool_node_candidate(node):
        return node
    return None

# ----------------------------------------------------------------------
def _get_or_create_material_linker(stage):
    node = _material_linker_node(stage)
    if node is None:
        if stage.node("material_linker") is not None:
            raise hou.OperationFailed(
                "{} was not created by Karma Builder: rename it, the tool never changes nodes it did not build.".format(
                    stage.node("material_linker").path()))
        node = stage.createNode("materiallinker", "material_linker")
    _mark_tool_node(node)
    return node

# ----------------------------------------------------------------
def _insert_material_linker_in_chain(stage, linker, log_callback):
    matlib = stage.node("mtlx_materials")
    if matlib is None:
        log_callback("[WARN] No material library found: build the environment first.")
        return False

    if linker.input(0) != matlib:
        for node in matlib.outputs():
            if node == linker:
                continue
            for index, source in enumerate(node.inputs()):
                if source == matlib:
                    node.setInput(index, linker)
        linker.setInput(0, matlib)
    return True

# --------------------------------------------------
def _material_edit_node(stage):
    if stage is None:
        return None
    node = stage.node(MATERIAL_EDIT_NODE)
    if node is not None and _base_node_type_name(node) == MATERIAL_EDIT_TYPE and _is_tool_node_candidate(node):
        return node
    return None

# ----------------------------------------------------------------------
def _get_or_create_material_edit(stage):
    node = _material_edit_node(stage)
    if node is None:
        existing = stage.node(MATERIAL_EDIT_NODE)
        if existing is not None:
            raise hou.OperationFailed(
                "{} was not created by Karma Builder: rename it, the tool never changes nodes it did not build.".format(
                    existing.path()))
        node = stage.createNode(MATERIAL_EDIT_TYPE, MATERIAL_EDIT_NODE)
    _mark_tool_node(node)
    return node

# ----------------------------------------------------------------
# The Edit Material LOP sits right after the Material Linker, so it sees the referenced materials.
def _insert_material_edit_in_chain(linker, edit):
    if edit.input(0) == linker:
        return
    for node in linker.outputs():
        if node == edit:
            continue
        for index, source in enumerate(node.inputs()):
            if source == linker:
                node.setInput(index, edit)
    edit.setInput(0, linker)

# ----------------------------------------------------------------------
def _material_edit_load(edit, material_path):
    if _has_expression(material_path):
        return ["the material path contains an expression"]
    count = edit.parm(MATERIAL_EDIT_COUNT_PARM)
    if count is not None and count.evalAsInt() < 1:
        count.insertMultiParmInstance(0)
    path_parm = edit.parm(MATERIAL_EDIT_PATH_PARM)
    if path_parm is None:
        return ["no '{}' parameter on {}: this Houdini's Edit Material LOP has another layout".format(
            MATERIAL_EDIT_PATH_PARM, edit.path())]
    path_parm.set(material_path)
    enable = edit.parm(MATERIAL_EDIT_ENABLE_PARM)
    if enable is not None:
        enable.set(1)
    load = edit.parm(MATERIAL_EDIT_LOAD_PARM)
    if load is None:
        return ["no Load button '{}' on {}: press Load yourself".format(MATERIAL_EDIT_LOAD_PARM, edit.path())]
    try:
        load.pressButton()
    except hou.Error as exc:
        return ["Load failed: {}".format(exc)]
    return []

# ----------------------------------------
# (index, dst_prim_path, file_path, file_prim_path) per reference.
# The multiparm layout is read and written by name: another Houdini version may rename it.
def _linker_set(linker, pattern, index, value):
    parm = linker.parm(pattern.format(index))
    if parm is None:
        raise ValueError("the Material Linker of this Houdini has no '{}' parameter (found on {})".format(
            pattern.format(index), linker.type().nameWithCategory()))
    parm.set(value)

# ----------------------------------------
def _linker_references(linker):
    refs = []
    count = linker.parm("num_files").evalAsInt() if linker.parm("num_files") is not None else 0
    for i in range(1, count + 1):
        dst = linker.parm("primpath_{}".format(i))
        src = linker.parm("filepath_{}".format(i))
        ref_prim = linker.parm("filerefprimpath_{}".format(i))
        if dst is None or src is None or ref_prim is None:
            continue
        refs.append((i, dst.evalAsString(), src.evalAsString(), ref_prim.evalAsString()))
    return refs

# ----------------------------------------
def _linker_rules(linker):
    rules = []
    count = linker.parm("num_links").evalAsInt() if linker.parm("num_links") is not None else 0
    for i in range(1, count + 1):
        owner = linker.parm("link_prim_{}".format(i))
        includes_parm = linker.parm("link_includes_{}".format(i))
        if owner is None or includes_parm is None:
            continue
        includes = [p.strip() for p in includes_parm.evalAsString().splitlines() if p.strip()]
        rules.append((i, owner.evalAsString().strip(), includes))
    return rules

# ------------------------------------------------------------
def _unique_material_path(linker, wanted):
    taken = set(dst for _, dst, _, _ in _linker_references(linker))
    try:
        stage = linker.stage()
    except hou.Error:
        stage = None

    def is_free(path):
        if path in taken:
            return False
        if stage is not None and stage.GetPrimAtPath(path):
            return False
        return True

    if is_free(wanted):
        return wanted
    match = re.search(r"(\d+)$", wanted)
    stem = wanted[:match.start()] if match else wanted
    number = int(match.group(1)) + 1 if match else 2
    while not is_free("{}{}".format(stem, number)):
        number += 1
    return "{}{}".format(stem, number)

# ----------------------------------------
def _linker_add_reference(linker, file_path, file_prim_path, label):
    if any(_has_expression(text) for text in (file_path, file_prim_path, label)):
        raise ValueError("refusing a material path that contains an expression")
    for _, dst, ref_file, ref_prim in _linker_references(linker):
        if ref_file == file_path and ref_prim == file_prim_path:
            return dst

    wanted = hou.lop.makeValidPrimPath("{}/{}".format(MATERIAL_DEFAULT_ROOT, label))
    dst_path = _unique_material_path(linker, wanted)

    folder = linker.parm("num_files")
    if folder is None:
        raise ValueError("the Material Linker of this Houdini has no 'num_files' parameter")
    folder.insertMultiParmInstance(folder.evalAsInt())
    index = folder.evalAsInt()
    _linker_set(linker, "enabled_{}", index, 1)
    _linker_set(linker, "createprims_{}", index, 1)
    _linker_set(linker, "filepath_{}", index, file_path)
    _linker_set(linker, "filerefprimpath_{}", index, file_prim_path)
    _linker_set(linker, "primpath_{}", index, dst_path)
    return dst_path

# ------------------------------------
def _linker_unassign(linker, prim_paths):
    prim_set = set(prim_paths)
    removed = 0
    folder = linker.parm("num_links")
    # Walk backwards so deleting a rule does not shift the indices still to visit.
    for index, owner, includes in reversed(_linker_rules(linker)):
        kept = [p for p in includes if p not in prim_set]
        if len(kept) == len(includes):
            continue
        removed += len(includes) - len(kept)
        if kept:
            linker.parm("link_includes_{}".format(index)).set("\n".join(kept))
        else:
            folder.removeMultiParmInstance(index - 1)
    return removed

# ------------------------------------------------------------
# Bind the material to the prims. A prim has one material, so it leaves its previous rule.
def _linker_assign(linker, material_path, prim_paths):
    prim_paths = [p for p in prim_paths if p]
    if not prim_paths:
        return 0
    _linker_unassign(linker, prim_paths)

    for index, owner, includes in _linker_rules(linker):
        if owner == material_path:
            merged = includes + [p for p in prim_paths if p not in includes]
            linker.parm("link_includes_{}".format(index)).set("\n".join(merged))
            return len(prim_paths)

    folder = linker.parm("num_links")
    if folder is None:
        raise ValueError("the Material Linker of this Houdini has no 'num_links' parameter")
    folder.insertMultiParmInstance(folder.evalAsInt())
    index = folder.evalAsInt()
    _linker_set(linker, "link_enabled_{}", index, 1)
    _linker_set(linker, "link_id_{}", index, str(uuid.uuid4()))
    _linker_set(linker, "link_type_{}", index, MATERIAL_LINK_TYPE)
    _linker_set(linker, "link_prim_{}", index, material_path)
    _linker_set(linker, "link_includes_{}", index, "\n".join(prim_paths))
    _linker_set(linker, "link_excludes_{}", index, "")
    _linker_set(linker, "link_reversed_{}", index, 0)
    _linker_set(linker, "link_ispathexpression_{}", index, 0)
    return len(prim_paths)
