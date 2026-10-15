# PythonModule of the BSM Karma Builder HDA (hou.phm() on the node).
#
# The asset carries bsm_karma.py and the presets as sections. They run in their own module, bsm_karma_hda,
# so they never clash with a bsm_karma.py that is on the Python path.
#
# Revision : 10-10-2026 | Auteur : BSM
import hashlib
import sys
import types

MODULE_NAME = "bsm_karma_hda"


# --------------------------------------------------
# The tool module for the embedded source. The code runs once per distinct source: a second press reuses it,
# a newer version of the asset replaces it.
def load_tool(definition):
    sections = definition.sections()
    code = sections["bsm_karma_py"].contents()
    digest = hashlib.sha1(code.encode("utf-8"), usedforsecurity=False).hexdigest()

    module = sys.modules.get(MODULE_NAME)
    if module is not None and getattr(module, "_hda_source_digest", None) == digest:
        return module

    if module is not None:
        # older version loaded: close its dialog first
        old_dialog = getattr(module, "bsm_karma_ui_dialog", None)
        if old_dialog is not None:
            try:
                old_dialog.close()
            except RuntimeError:
                pass  # the Qt object is already gone

    module = types.ModuleType(MODULE_NAME)
    module.__file__ = "bsm_karma.py (embedded in the BSM Karma Builder HDA)"
    module.EMBEDDED_PRESETS = sections["bsm_karma_presets_json"].contents()
    module._hda_source_digest = digest
    sys.modules[MODULE_NAME] = module
    try:
        exec(compile(code, "bsm_karma.py", "exec"), module.__dict__)
    except Exception:
        del sys.modules[MODULE_NAME]
        raise
    return module


# ------------------------------------------------------------
# Opens the Karma Builder dialog (or brings a second launch in place of the first).
def open_builder(node):
    module = load_tool(node.type().definition())
    module.main()
    return module
