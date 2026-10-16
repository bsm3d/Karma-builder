# shelf.py - BSM Karma Builder - create the shelf button (and install the package) from inside Houdini
# Version : 1.0.0 | Revision : 16-10-2026 | Auteur : BSM

import hou
import os
import shutil
from xml.sax.saxutils import escape
from .buildinfo import BUILD_ID
from .debuglog import _debug
from .util import _has_expression

SHELF_NAME = "bsm_karma"
SHELF_LABEL = "BSM Karma"
TOOL_NAME = "bsm_karma_builder"
TOOL_LABEL = "Karma Builder"
DEFAULT_ICON = "PLASMA_App"
ICON_FILE = "icone_Bsm_Karma.png"
ASSET_TYPE_NAME = "bsm::karma_builder::1.0"

SCRIPT_PACKAGE = """import importlib
import bsm_karma
importlib.reload(bsm_karma)
bsm_karma.main()
"""

SCRIPT_ASSET = """import hou
node_type = hou.nodeType(hou.lopNodeTypeCategory(), "{type_name}")
if node_type is None:
    hou.ui.displayMessage("The BSM Karma Builder asset is not installed in this Houdini.")
else:
    node_type.hdaModule().open_builder()
"""


# ------------------------------------------------------------
def tool_script(asset=False, type_name=ASSET_TYPE_NAME):
    return SCRIPT_ASSET.format(type_name=type_name) if asset else SCRIPT_PACKAGE


# ------------------------------------------------------------
def build_shelf_xml(script, icon=DEFAULT_ICON):
    if "]]>" in script:
        raise ValueError("the script cannot hold the end of a CDATA block")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<shelfDocument>\n'
            '  <toolshelf name="{shelf}" label="{shelf_label}">\n    <memberTool name="{tool}"/>\n  </toolshelf>\n\n'
            '  <tool name="{tool}" label="{label}" icon="{icon}">\n'
            '    <helpText><![CDATA[Opens BSM Karma Builder: Karma lighting, sky, atmosphere, materials and render settings in /stage.]]></helpText>\n'
            '    <script scriptType="python"><![CDATA[{script}]]></script>\n  </tool>\n</shelfDocument>\n').format(
        shelf=SHELF_NAME, shelf_label=SHELF_LABEL, tool=TOOL_NAME, label=TOOL_LABEL, icon=escape(icon, {'"': "&quot;"}),
        script=script)


# ------------------------------------------------------------
def preferences_folder():
    folder = hou.text.expandString("$HOUDINI_USER_PREF_DIR")
    if not folder or folder.startswith("$") or _has_expression(folder) or not os.path.isabs(folder):
        raise OSError("the Houdini preferences folder is unknown: {!r}".format(folder))
    if not os.path.isdir(folder):
        raise OSError("the Houdini preferences folder does not exist: {}".format(folder))
    return folder


# ------------------------------------------------------------
def _same_folder(first, second):
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


# ------------------------------------------------------------
# Copy the package folder to scripts/python of the preferences. A folder already there is kept as bsm_karma.bak
# (one backup, the previous backup is replaced). Returns a line for the report.
def install_package(source, pref_dir):
    target = os.path.join(pref_dir, "scripts", "python", "bsm_karma")
    if _same_folder(source, target):
        return "The package is already in {}.".format(target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    backup = target + ".bak"
    if os.path.isdir(target):
        if os.path.isdir(backup):
            shutil.rmtree(backup)
        os.replace(target, backup)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "bsm_karma_debug.log*"))
    return "Package copied to {}{}.".format(target, " (the previous one is kept as bsm_karma.bak)" if os.path.isdir(backup) else "")


# ------------------------------------------------------------
# Icon of the tool: the picture next to the package is copied to the preferences so the shelf does not depend on
# the repository staying where it is.
def _icon_for(source, pref_dir):
    if not source:
        return DEFAULT_ICON
    for folder in (os.path.dirname(source), source):
        candidate = os.path.join(folder, ICON_FILE)
        if os.path.isfile(candidate):
            target_dir = os.path.join(pref_dir, "bsm_karma")
            os.makedirs(target_dir, exist_ok=True)
            target = os.path.join(target_dir, ICON_FILE)
            shutil.copyfile(candidate, target)
            return target.replace("\\", "/")
    return DEFAULT_ICON


# ------------------------------------------------------------
# Write the .shelf file, reload the shelves and put the shelf in a shelf set so it shows. Each step that cannot
# be done is said in the report instead of stopping the others.
def install_shelf(asset=False, source=None, type_name=ASSET_TYPE_NAME, pref_dir=None):
    report = []
    pref_dir = pref_dir or preferences_folder()
    toolbar = os.path.join(pref_dir, "toolbar")
    os.makedirs(toolbar, exist_ok=True)
    path = os.path.join(toolbar, "bsm_karma.shelf")
    icon = _icon_for(source, pref_dir)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(build_shelf_xml(tool_script(asset, type_name), icon))
    report.append("Shelf file written: {}".format(path))
    try:
        hou.shelves.reloadShelfFiles()
        report.append("Shelves reloaded.")
    except (hou.Error, AttributeError) as exc:
        report.append("Restart Houdini to see the shelf (reload failed: {}).".format(exc))
        return report
    report.append(_show_shelf())
    return report


# ------------------------------------------------------------
def _show_shelf():
    try:
        shelf = hou.shelves.shelves().get(SHELF_NAME)
        if shelf is None:
            return "The shelf '{}' is in the list of shelves (the + at the right of the shelf tabs).".format(SHELF_LABEL)
        shelf_sets = []
        try:
            shelf_sets = list(hou.ui.curDesktop().shelfDock().shelfSets())
        except (hou.Error, AttributeError):
            pass
        if not shelf_sets:
            default = hou.shelves.shelfSets().get("shelf_set_1")
            shelf_sets = [default] if default is not None else []
        if not shelf_sets:
            return "Add the shelf '{}' with the + at the right of the shelf tabs.".format(SHELF_LABEL)
        shelf_set = shelf_sets[0]
        if shelf not in shelf_set.shelves():
            shelf_set.setShelves(tuple(shelf_set.shelves()) + (shelf,))
        return "The shelf '{}' is now in the shelf bar.".format(SHELF_LABEL)
    except (hou.Error, AttributeError, TypeError) as exc:
        _debug("shelf not shown: {}: {}".format(type(exc).__name__, exc))
        return "Add the shelf '{}' with the + at the right of the shelf tabs ({}).".format(SHELF_LABEL, exc)


# ------------------------------------------------------------
# From the package folder (a repository, or scripts/python): copy it if it is elsewhere, then the shelf.
def install(show_message=True):
    source = os.path.dirname(os.path.abspath(__file__))
    pref_dir = preferences_folder()
    report = [install_package(source, pref_dir)]
    report += install_shelf(asset=False, source=source, pref_dir=pref_dir)
    report.append("Build {} (the window title and the first line of the Log show it).".format(BUILD_ID))
    report.append("Press the 'Karma Builder' button to open the tool.")
    text = "\n".join(report)
    print(text)
    if show_message:
        try:
            hou.ui.displayMessage("BSM Karma Builder installed.", details=text)
        except (hou.Error, AttributeError):
            pass
    return report
