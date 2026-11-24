# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Checks the shelf button and the package install: the shelf file, the copy of the package and the preferences folder checks.

# Revision : 16-10-2026 | Auteur : BSM
import os
import shutil
import tempfile
import xml.dom.minidom
from _common import ROOT, Checker, load_tool

hou, k = load_tool()
import bsm_karma.shelf as shelf

t = Checker("shelf")
work = tempfile.mkdtemp(prefix="bsm_shelf_")

xml_text = shelf.build_shelf_xml(shelf.tool_script(False))
document = xml.dom.minidom.parseString(xml_text.encode("utf-8"))
tools = document.getElementsByTagName("tool")
t.check("the shelf file is valid XML with one tool and one shelf", len(tools) == 1 and len(document.getElementsByTagName("toolshelf")) == 1)
script = tools[0].getElementsByTagName("script")[0].firstChild.data
t.check("the script reloads the package and opens the tool", "importlib.reload(bsm_karma)" in script and script.rstrip().endswith("bsm_karma.main()"), script)
asset_script = shelf.tool_script(True, "bsm::karma_builder::1.0")
t.check("the asset script finds the type by name and says so when it is missing", 'hou.nodeType(hou.lopNodeTypeCategory(), "bsm::karma_builder::1.0")' in asset_script and "displayMessage" in asset_script)
compile(script, "<shelf>", "exec")
compile(asset_script, "<shelf asset>", "exec")
t.check("both scripts are valid Python", True)
t.check("the icon is escaped", '&quot;' in shelf.build_shelf_xml("x", 'a"b') and 'icon="a&quot;b"' in shelf.build_shelf_xml("x", 'a"b'))
try:
    shelf.build_shelf_xml("a]]>b")
    refused = False
except ValueError:
    refused = True
t.check("a script that would close the CDATA block is refused", refused)
shipped = open(os.path.join(ROOT, "toolbar", "bsm_karma.shelf"), encoding="utf-8").read().replace("\r\n", "\n")
t.check("toolbar/bsm_karma.shelf is what install writes (default icon)", shipped == shelf.build_shelf_xml(shelf.tool_script(False)))

# the menu entry shipped at the repository root, picked up through the package
menu = xml.dom.minidom.parse(os.path.join(ROOT, "MainMenuCommon.xml"))
items = menu.getElementsByTagName("scriptItem")
t.check("MainMenuCommon.xml is valid XML with one BSM menu and one item", len(menu.getElementsByTagName("subMenu")) == 1 and len(items) == 1)
menu_script = items[0].getElementsByTagName("scriptCode")[0].firstChild.data
t.check("the menu script reloads the package and opens the tool", "importlib.reload(bsm_karma)" in menu_script and menu_script.rstrip().endswith("bsm_karma.main()"), menu_script)
compile(menu_script, "<menu>", "exec")

# the package copy
source = os.path.join(ROOT, "bsm_karma")
pref = os.path.join(work, "pref")
os.makedirs(pref)
line = shelf.install_package(source, pref)
target = os.path.join(pref, "scripts", "python", "bsm_karma")
t.check("the package is copied with its presets", os.path.isfile(os.path.join(target, "__init__.py")) and os.path.isfile(os.path.join(target, "presets.json")), line)
t.check("no cache or log is copied", not [n for n in os.listdir(target) if n == "__pycache__" or n.startswith("bsm_karma_debug.log")])
open(os.path.join(target, "marker.txt"), "w").write("old")
shelf.install_package(source, pref)
t.check("a second install keeps the previous folder as bsm_karma.bak", os.path.isfile(os.path.join(target + ".bak", "marker.txt")) and not os.path.exists(os.path.join(target, "marker.txt")))
shelf.install_package(source, pref)
t.check("only one backup is kept", not os.path.exists(os.path.join(target + ".bak", "marker.txt")))
t.check("installing from the target itself does nothing", "already" in shelf.install_package(target, pref))

# the shelf file
class Pref:
    pass
report = shelf.install_shelf(asset=False, source=source, pref_dir=pref)
path = os.path.join(pref, "toolbar", "bsm_karma.shelf")
t.check("the shelf file is written in toolbar", os.path.isfile(path) and report[0].startswith("Shelf file written"), report[:2])
xml.dom.minidom.parse(path)
t.check("the written file is valid XML", True)
icon_dir = os.path.join(pref, "bsm_karma")
has_icon = os.path.isfile(os.path.join(ROOT, shelf.ICON_FILE))
t.check("the icon is copied to the preferences when the repository has it", (not has_icon) or os.path.isfile(os.path.join(icon_dir, shelf.ICON_FILE)))
report2 = shelf.install_shelf(asset=True, type_name="bsm::karma_builder::1.0", pref_dir=pref)
t.check("the asset variant overwrites the file with the asset script", "hdaModule" in open(path, encoding="utf-8").read(), report2[:1])

# the preferences folder
real_expand = hou.text.expandString
for label, value in (("an unknown variable", "$HOUDINI_USER_PREF_DIR"), ("a backtick", "C:/x/`id`"), ("a relative path", "relative/dir"), ("an empty answer", ""), ("a folder that does not exist", os.path.join(work, "nope"))):
    hou.text.expandString = lambda text, value=value: value
    try:
        shelf.preferences_folder()
        refused = False
    except OSError:
        refused = True
    hou.text.expandString = real_expand
    t.check("preferences folder refused: {}".format(label), refused)

shutil.rmtree(work, ignore_errors=True)
t.done()
