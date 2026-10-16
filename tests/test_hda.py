# The BSM Karma Builder HDA: built from the sources, installable, passes its input through, and its
# embedded loader runs the tool. Also fails when the committed bsm_karma_builder.hda is out of date.
#
# Revision : 10-10-2026 | Auteur : BSM
import json
import os
import sys
import types

from _common import ROOT, Checker, load_tool, scratch_dir

hou, k = load_tool()
sys.path.insert(0, ROOT)
import build_hda

t = Checker("hda")
out_dir = scratch_dir("hda")
hda_path = os.path.join(out_dir, "bsm_karma_builder.hda").replace("\\", "/")


# ----------------------------------------------------------------------
def source(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8", newline="") as handle:
        return handle.read().replace("\r\n", "\n")


# one section per module of the package
MODULES = sorted(name[:-3] for name in os.listdir(os.path.join(ROOT, "bsm_karma")) if name.endswith(".py"))


built, version = build_hda.build(hda_path)
t.check("the HDA file is built", os.path.isfile(built) and os.path.getsize(built) > 50000, os.path.getsize(built))
t.check("tool version read from bsm_karma/config.py", version == k.SCRIPT_VERSION, version)
hou.hda.installFile(built)
node_type = hou.nodeType(hou.lopNodeTypeCategory(), build_hda.OP_NAME)
t.check("installed as a LOP node type", node_type is not None, build_hda.OP_NAME)
definition = node_type.definition()

# --- sections carry the tool ---
sections = definition.sections()
t.check("every module of the package is embedded verbatim",
        all(sections["bsm_karma_src_" + name].contents() == source("bsm_karma", name + ".py") for name in MODULES),
        [name for name in MODULES if "bsm_karma_src_" + name not in sections])
t.check("presets and loader are embedded verbatim",
        sections["bsm_karma_presets_json"].contents() == source("bsm_karma", "presets.json")
        and sections["PythonModule"].contents() == source("tools", "hda_python_module.py"))
t.check("license is embedded", "PolyForm Noncommercial License 1.0.0" in sections["LICENSE.txt"].contents())
t.check("help and tab menu sections present", "Help" in sections and "Tools.shelf" in sections)
t.check("the tab menu entry is tied to the asset itself", "$HDA_TABLE_AND_NAME" in sections["Tools.shelf"].contents(), sections["Tools.shelf"].contents()[:200])
t.check("icon embedded and resolved", "icon.png" in sections and "icon.png" in node_type.resolvedIcon(), node_type.resolvedIcon())
t.check("definition version", definition.version() == version, definition.version())

stage = hou.node("/stage")
sphere = stage.createNode("sphere", "ball")
asset = stage.createNode(build_hda.OP_NAME, "builder")
asset.setInput(0, sphere)
button = asset.parm("open_builder")
t.check("button parameter with a Python callback", button is not None
        and "open_builder" in button.parmTemplate().scriptCallback()
        and button.parmTemplate().scriptCallbackLanguage() == hou.scriptLanguage.Python)
t.check("version label shows the tool version", version in asset.parmTemplateGroup().find("tool_version").columnLabels())
t.check("the node passes its input through", asset.stage().GetPrimAtPath("/ball").IsValid())
t.check("it also cooks with nothing connected", (asset.setInput(0, None) or True) and asset.stage() is not None)

# --- the embedded loader ---
module = hou.node("/stage/builder").hdaModule()
t.check("PythonModule exposes the loader", hasattr(module, "load_tool") and hasattr(module, "open_builder"))
tool = module.load_tool(definition)
t.check("the embedded tool runs", tool.SCRIPT_VERSION == version and callable(tool.main), tool.SCRIPT_VERSION)
t.check("the asset carries the same build as the folder (same build id)", tool.BUILD_ID == k.BUILD_ID, (tool.BUILD_ID, k.BUILD_ID))
t.check("it lives in its own module name", tool.__name__ == "bsm_karma_hda" and sys.modules.get("bsm_karma") is k)
t.check("a second load reuses the module", module.load_tool(definition) is tool)

stub = types.SimpleNamespace(_pending_logs=[])
tool.KarmaBuilderUI._load_presets(stub)  # plain function call: no dialog needed
expected = json.loads(source("bsm_karma", "presets.json"))
t.check("presets come from the embedded text", stub.sky_presets == expected["sky_presets"] and stub.presets == expected["render_qualities"]
        and not stub._pending_logs, stub._pending_logs)

# a different source replaces the module and closes the old dialog; a failing source leaves nothing loaded
closed = []
tool.bsm_karma_ui_dialog = types.SimpleNamespace(close=lambda: closed.append(True))


# ------------------------------------------------------------------------
class FakeSection:
    def __init__(self, text):
        self._text = text

    # --------------------------------------------------------------------------------
    def contents(self):
        return self._text



# ----------------------------------------
def fake_definition(code):
    return types.SimpleNamespace(sections=lambda: {"bsm_karma_src___init__": FakeSection(code), "bsm_karma_presets_json": FakeSection("{}")})


newer = module.load_tool(fake_definition("MARKER = 2\n"))
t.check("a changed source replaces the module", newer is not tool and newer.MARKER == 2 and sys.modules["bsm_karma_hda"] is newer)
t.check("the previous dialog was closed first", closed == [True])
try:
    module.load_tool(fake_definition("raise RuntimeError('broken')\n"))
    raised = False
except RuntimeError:
    raised = True
t.check("a source that fails to run is not left half loaded", raised and "bsm_karma_hda" not in sys.modules)

# --- the committed asset is current ---
committed = os.path.join(ROOT, "bsm_karma_builder.hda")
if os.path.isfile(committed):
    committed_defs = hou.hda.definitionsInFile(committed)
    stale = []
    if not committed_defs:
        stale.append("no definition")
    else:
        committed_sections = committed_defs[0].sections()
        expected_sections = [("bsm_karma_src_" + name, source("bsm_karma", name + ".py")) for name in MODULES]
        expected_sections += [("bsm_karma_presets_json", source("bsm_karma", "presets.json")),
                              ("PythonModule", source("tools", "hda_python_module.py"))]
        for name, text in expected_sections:
            if name not in committed_sections or committed_sections[name].contents() != text:
                stale.append(name)
    t.check("bsm_karma_builder.hda is up to date (rebuild with: hython build_hda.py)", not stale, stale)
else:
    t.check("bsm_karma_builder.hda exists (build it with: hython build_hda.py)", False)

# la version du header est écrite à la main, elle doit suivre SCRIPT_VERSION
header = source("bsm_karma", "config.py").split('\n')[:8]
t.check("file header carries the current version", any("Version : " + k.SCRIPT_VERSION in line for line in header), header[1])

t.done()
