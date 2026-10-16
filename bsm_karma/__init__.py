# __init__.py - BSM Karma Builder - entry point of the bsm_karma package
# Version : 2026.10.15.1 | Revision : 15-10-2026 | Auteur : BSM

import sys
import traceback

# importlib.reload(bsm_karma) only runs this file: drop the submodules so they are read again too
if "bsm_karma_ui_dialog" in globals():
    for name in [n for n in sys.modules if n.startswith(__name__ + ".")]:
        del sys.modules[name]

import hou
from .build import setup_karma_environment
from .catalog import (_amd_library_reachable, _bound_material_name, _catalog_source_problem, _list_materials_in_file,
                      _material_catalog_file, _parse_catalog_drop, _stage_target_prims)
from .debuglog import _debug_exception, debug_log_path
from .config import AMD_LIBRARY_URL, AMD_SOURCE_ID, SCRIPT_VERSION, USD_CAMERA_PREFIX
from .environment import _stage_camera_prims
from .linker import (_get_or_create_material_edit, _get_or_create_material_linker, _insert_material_edit_in_chain,
                     _insert_material_linker_in_chain, _linker_add_reference, _linker_assign, _linker_references, _linker_rules,
                     _linker_unassign, _material_edit_load, _material_edit_node)
from .nodeutil import _is_tool_node_candidate
from .shelf import install
from .util import _private_temp_dir
from .window import KarmaBuilderUI


# re-exported names: the public entry points and what the tests reach for
__all__ = [
    "main", "KarmaBuilderUI", "setup_karma_environment", "SCRIPT_VERSION", "AMD_LIBRARY_URL", "AMD_SOURCE_ID",
    "USD_CAMERA_PREFIX", "_amd_library_reachable", "_bound_material_name", "_catalog_source_problem",
    "_list_materials_in_file", "_material_catalog_file", "_parse_catalog_drop", "_stage_target_prims",
    "_stage_camera_prims", "_get_or_create_material_linker", "_insert_material_linker_in_chain",
    "_get_or_create_material_edit", "_insert_material_edit_in_chain", "_material_edit_load", "_material_edit_node",
    "_linker_add_reference", "_linker_assign", "_linker_references", "_linker_rules", "_linker_unassign",
    "_is_tool_node_candidate", "_private_temp_dir", "bsm_karma_ui_dialog", "install",
]

# le dialogue est gardé en global pour qu'un second lancement ferme le premier;
# le `if not in globals()` garde la référence quand le shelf tool recharge le module (importlib.reload avant main)
if "bsm_karma_ui_dialog" not in globals():
    bsm_karma_ui_dialog = None


# --------------------------------------------------------
# Forget the dialog once it is destroyed, unless a newer one already replaced it.
def _forget_dialog(dialog_id):
    global bsm_karma_ui_dialog
    if bsm_karma_ui_dialog is not None and id(bsm_karma_ui_dialog) == dialog_id:
        bsm_karma_ui_dialog = None


# ------------------------------------------------------------
def main(kwargs=None):
    global bsm_karma_ui_dialog
    if bsm_karma_ui_dialog is not None:
        try:
            bsm_karma_ui_dialog.close()
        except RuntimeError:
            pass  # the Qt object was already deleted

    try:
        dialog = KarmaBuilderUI(hou.qt.mainWindow())
    except Exception:   # whatever went wrong while building the window: say where the details are, do not raise
        _debug_exception("main")
        traceback.print_exc()
        try:
            hou.ui.displayMessage("BSM Karma Builder could not open its window.\n\nDetails are in the debug log:\n{}".format(
                debug_log_path()), severity=hou.severityType.Error)
        except hou.Error:
            pass
        return
    dialog.destroyed.connect(lambda *_, dialog_id=id(dialog): _forget_dialog(dialog_id))
    bsm_karma_ui_dialog = dialog
    dialog.show()
