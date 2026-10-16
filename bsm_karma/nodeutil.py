# nodeutil.py - BSM Karma Builder - helpers to create, mark and set nodes
# Version : 1.0.0 | Revision : 15-10-2026 | Auteur : BSM

import contextlib
import hou
import re
from .config import TOOL_NODE_TAG_KEY, TOOL_NODE_TAG_VALUE
from .debuglog import _debug, _debug_node_label

# ----------------------------------------
def _pset(node, name, value, log_callback, quiet=False):
    p = node.parm(name)
    if p is not None:
        try:
            if p.isLocked(): p.lock(False)
            try:
                p.set(value)
            except TypeError:
                p.set(str(value))
            return True
        except hou.PermissionError:
            _debug("locked parm {}.{}".format(_debug_node_label(node), name))
            if not quiet: log_callback(f"  [WARN] Locked parm: '{name}' on {node.name()}")
            return False
    _debug("no parm '{}' on {}".format(name, _debug_node_label(node)))
    return False


# ------------------------------------------------------------------------
def _base_node_type_name(node):
    try:
        return node.type().name().split("::", 1)[0]
    except (hou.Error, AttributeError):
        return ""


def _mark_tool_node(node):
    if node is None:
        return
    try:
        node.setUserData(TOOL_NODE_TAG_KEY, TOOL_NODE_TAG_VALUE)
    except hou.Error:
        pass


# ----------------------------------------------------------------------
# Only the tag proves that the tool built a node. A node that merely has the same name or the same type is the
# user's: it is never deleted, rewired, moved or retagged.
def _is_tool_node_candidate(node, node_name=None):
    if node is None:
        return False
    try:
        return node.userData(TOOL_NODE_TAG_KEY) == TOOL_NODE_TAG_VALUE
    except hou.Error:
        return False


def _get_or_create_node(parent, node_type, node_name):
    n = parent.node(node_name)
    if n is None:
        n = parent.createNode(node_type, node_name)
    elif not _is_tool_node_candidate(n, node_name):
        # a node of the user's that only shares the name: the tool leaves it alone and stops
        raise hou.OperationFailed(
            "{} ({}) was not created by BSM Karma Builder: rename it, the tool never changes nodes it did not build.".format(
                n.path(), _base_node_type_name(n)))
    _mark_tool_node(n)
    return n


# ------------------------------------------------------------
def _safe_connect(node, prev):
    if node is not None and prev is not None and node.input(0) != prev:
        node.setInput(0, prev)


# ------------------------------------------------------------
# Houdini cooks the stage after every node change, and a running Karma viewport restarts each time. While the
# network is being built, cooking is paused (manual update), then put back: one cook at the end. A session that
# was already in manual mode is left alone.
@contextlib.contextmanager
def _paused_cooking(log_callback=None):
    previous = None
    try:
        current = hou.updateModeSetting()
        if current != hou.updateMode.Manual:
            hou.setUpdateMode(hou.updateMode.Manual)
            previous = current
    except (hou.Error, AttributeError) as exc:
        _debug("cooking not paused: {}".format(exc))
    try:
        yield
    finally:
        if previous is not None:
            try:
                hou.setUpdateMode(previous)
            except (hou.Error, AttributeError) as exc:
                _debug("update mode not restored: {}".format(exc))
                if log_callback is not None:
                    log_callback("[WARN] Houdini's update mode could not be put back: set it to Auto Update yourself (status bar).")


# ------------------------------------------------------------
def _get_or_create_stage():
    stage = hou.node("/stage")
    if stage is None:
        obj = hou.node("/obj")
        stage = obj.createNode("lopnet", "karma_render")
    return stage


def _set_light_color(node, rgb):
    color_parm = _find_usd_input_parm(node, "color")
    tuple_candidates = [
        color_parm.tuple().name() if color_parm is not None else "xn__inputscolor_i0a",
        "inputscolor",
        "lightcolor",
        "light_color",
        "color",
    ]
    for parm_name in tuple_candidates:
        pt = node.parmTuple(parm_name)
        if pt is None or len(pt) != 3:
            continue
        try:
            for p in pt:
                if p.isLocked():
                    p.lock(False)
            pt.set(rgb)
            return True
        except (hou.Error, TypeError):
            pass

    for pt in node.parmTuples():
        pname = pt.name().lower()
        if len(pt) == 3 and "color" in pname and ("input" in pname or "light" in pname):
            try:
                for p in pt:
                    if p.isLocked():
                        p.lock(False)
                pt.set(rgb)
                return True
            except (hou.Error, TypeError):
                pass
    return False


# ------------------------------------------------------------
def _set_first_existing_parm(node, parm_names, value, log_callback):
    for parm_name in parm_names:
        if _pset(node, parm_name, value, log_callback, quiet=True):
            return True
    return False


# ----------------------------------------------------------------
def _set_first_existing_parm_tuple(node, parm_names, values, log_callback):
    values = tuple(values)
    for parm_name in parm_names:
        pt = node.parmTuple(parm_name)
        if pt is None or len(pt) != len(values):
            continue
        try:
            for p in pt:
                if p.isLocked():
                    p.lock(False)
            pt.set(values)
            return True
        except (hou.Error, TypeError):
            continue
    return False


# ------------------------------------------------------------
def _set_menu_parm_by_keywords(node, parm_names, keywords, log_callback):
    keys = tuple(str(k).lower() for k in (keywords or ()))
    if not keys:
        return False

    for parm_name in parm_names:
        parm = node.parm(parm_name)
        if parm is None:
            continue
        try:
            items = list(parm.menuItems())
            labels = list(parm.menuLabels())
        except hou.Error:
            continue

        for idx, item in enumerate(items):
            label = labels[idx] if idx < len(labels) else ""
            blob = "{} {}".format(item, label).lower()
            if not any(k in blob for k in keys):
                continue

            for candidate in (item, idx):
                try:
                    if parm.isLocked():
                        parm.lock(False)
                    parm.set(candidate)
                    return True
                except (hou.Error, TypeError):
                    pass
    return False


# --------------------------------------------------
# ATTENTION -> le suffixe de xn__inputs<token>_<hash> change d'une version à l'autre,
# d'où la recherche par pattern ('width', 'color'...) et jamais par nom exact
def _find_usd_input_parm(node, token):
    pattern = re.compile(r"^xn__inputs{}_(?!control)[a-z0-9]+$".format(re.escape(token)), re.IGNORECASE)
    for parm in node.parms():
        if pattern.match(parm.name()):
            return parm
    return None


# --------------------------------------------------------
def _set_usd_input(node, token, value, log_callback, quiet=True):
    parm = _find_usd_input_parm(node, token)
    if parm is None:
        return False
    return _pset(node, parm.name(), value, log_callback, quiet=quiet)


# ------------------------------------------------------------
def _menu_has_value(parm, value):
    try:
        items = list(parm.menuItems())
    except hou.OperationFailed:
        return True
    return value in items


# ----------------------------------------------------------------------
def _remove_tool_node(stage, node_name, log_callback, reason=""):
    node = stage.node(node_name)
    if node is None or not _is_tool_node_candidate(node, node_name):
        return False
    try:
        node.destroy()
    except hou.OperationFailed as exc:
        log_callback("[WARN] Could not remove {}: {}".format(node_name, exc))
        return False
    if reason:
        log_callback("[INFO] Removed {} ({}).".format(node_name, reason))
    return True


# --------------------------------------------------
def _set_menu_token(node, parm_names, token, log_callback, label=None):
    for name in parm_names:
        parm = node.parm(name)
        if parm is None:
            continue
        if not _menu_has_value(parm, token):
            log_callback("[WARN] {}: '{}' is not available on {}.{}".format(label or name, token, node.name(), name))
            return False
        return _pset(node, name, token, log_callback, quiet=True)
    return False


# ----------------------------------------
# bug trouvé et fixé: layoutChildren() sur tout /stage déplaçait aussi les nodes de l'utilisateur,
# on ne range plus que ceux de l'outil
def _layout_tool_nodes(stage):
    nodes = [node for node in stage.children() if _is_tool_node_candidate(node, node.name())]
    if nodes:
        stage.layoutChildren(nodes)
