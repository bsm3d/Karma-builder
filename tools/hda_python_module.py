# Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : PythonModule of the HDA (hou.phm() on the node): serves the modules stored in the asset as a package
# Houdini : 21 and 22
# Version : 1.0.0
#
# The asset carries every module of the bsm_karma package and the presets as sections. An import hook serves
# them as the package bsm_karma_hda, so the relative imports of the tool work as on disk and nothing clashes
# with a bsm_karma package that is on the Python path.

import hashlib
import importlib
import importlib.abc
import importlib.util
import sys

MODULE_NAME = "bsm_karma_hda"
SOURCE_PREFIX = "bsm_karma_src_"


# ------------------------------------------------------------
# Gives the embedded sources to the import system.
class SectionLoader(importlib.abc.Loader):

    def __init__(self, sources):
        self.sources = sources

    def create_module(self, spec):
        return None

    # --------------------------------------------------
    def exec_module(self, module):
        key = "__init__" if module.__name__ == MODULE_NAME else module.__name__[len(MODULE_NAME) + 1:]
        module.__file__ = "{}.py (embedded in the Karma Builder HDA)".format(key)
        exec(compile(self.sources[key], key + ".py", "exec"), module.__dict__)


# ------------------------------------------------------------
class SectionFinder(importlib.abc.MetaPathFinder):

    def __init__(self, loader):
        self.loader = loader

    def find_spec(self, fullname, path=None, target=None):
        if fullname == MODULE_NAME:
            return importlib.util.spec_from_loader(fullname, self.loader, is_package=True)
        if fullname.startswith(MODULE_NAME + ".") and fullname[len(MODULE_NAME) + 1:] in self.loader.sources:
            return importlib.util.spec_from_loader(fullname, self.loader)
        return None


# ------------------------------------------------------------
def forget_package():
    for name in [n for n in sys.modules if n == MODULE_NAME or n.startswith(MODULE_NAME + ".")]:
        del sys.modules[name]
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, SectionFinder)]


# --------------------------------------------------
# The tool module for the embedded sources. The code runs once per distinct set of sources: a second press
# reuses it, a newer version of the asset replaces it.
def load_tool(definition):
    sections = definition.sections()
    sources = {name[len(SOURCE_PREFIX):]: sections[name].contents() for name in sections if name.startswith(SOURCE_PREFIX)}
    presets = sections["bsm_karma_presets_json"].contents()
    digest = hashlib.sha1(repr(sorted(sources.items()) + [presets]).encode("utf-8"), usedforsecurity=False).hexdigest()

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
    forget_package()

    sys.meta_path.insert(0, SectionFinder(SectionLoader(sources)))
    try:
        module = importlib.import_module(MODULE_NAME)
    except Exception:
        forget_package()
        raise
    module.EMBEDDED_PRESETS = presets
    module._hda_source_digest = digest
    return module


# ------------------------------------------------------------
# The tool module of an asset, or None after telling the user why it could not be loaded. Without a node, the asset
# is found by its type name (the shelf button has no node).
def _tool_or_message(node, type_name):
    import hou
    try:
        if node is not None:
            definition = node.type().definition()
        else:
            definition = hou.nodeType(hou.lopNodeTypeCategory(), type_name).definition()
        return load_tool(definition)
    except Exception:   # a damaged or incomplete asset: tell the user, leave nothing half loaded
        import traceback
        forget_package()
        hou.ui.displayMessage("Karma Builder could not load its code from this asset.\nRebuild it with: hython build_hda.py",
                              details=traceback.format_exc(), severity=hou.severityType.Error)
        return None


# ------------------------------------------------------------
# Opens the Karma Builder dialog (or brings a second launch in place of the first).
def open_builder(node=None, type_name="bsm::karma_builder::1.0"):
    module = _tool_or_message(node, type_name)
    if module is None:
        return None
    module.main()
    return module


# ------------------------------------------------------------
# Creates the shelf button that opens the tool without a node (see shelf.py of the package).
def install_shelf(node=None, type_name="bsm::karma_builder::1.0"):
    import hou
    import importlib
    module = _tool_or_message(node, type_name)
    if module is None:
        return None
    shelf = importlib.import_module(module.__name__ + ".shelf")
    try:
        report = shelf.install_shelf(asset=True, type_name=node.type().name() if node is not None else type_name)
    except (OSError, hou.Error) as exc:
        hou.ui.displayMessage("The shelf could not be created.", details=str(exc), severity=hou.severityType.Error)
        return None
    hou.ui.displayMessage("The 'Karma Builder' button is ready.", details="\n".join(report))
    return report
