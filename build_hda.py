# Builds the BSM Karma Builder HDA from the project files: hython build_hda.py [output.hda]
#
# The asset is a LOP node that passes its input through and carries the tool as sections (one per module of the
# bsm_karma package, presets, loader, license, icon). It is rebuilt from the sources each time, the package stays
# the single source of truth.
#
# Revision : 10-10-2026 | Auteur : BSM
import os
import re
import sys

import hou

ROOT = os.path.dirname(os.path.abspath(__file__))
PACKAGE = "bsm_karma"
DEFAULT_OUTPUT = os.path.join(ROOT, "bsm_karma_builder.hda")

OP_NAME = "bsm::karma_builder::1.0"
OP_LABEL = "BSM Karma Builder"
SOURCE_PREFIX = "bsm_karma_src_"

# ------------------------------------------------------------
def read_text(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8", newline="") as handle:
        return handle.read().replace("\r\n", "\n")


# ----------------------------------------
def read_bytes(*parts):
    with open(os.path.join(ROOT, *parts), "rb") as handle:
        return handle.read()


# ------------------------------------------------------------
# One section per module of the package: bsm_karma_src_<name>, the package file itself being "__init__".
def package_sources():
    folder = os.path.join(ROOT, PACKAGE)
    return {name[:-3]: read_text(PACKAGE, name) for name in sorted(os.listdir(folder)) if name.endswith(".py")}


#------------------------------------------------------------
def script_version():
    match = re.search(r'^SCRIPT_VERSION = "([^"]+)"', read_text(PACKAGE, "config.py"), re.MULTILINE)
    if not match:
        raise RuntimeError("SCRIPT_VERSION not found in {}/config.py".format(PACKAGE))
    return match.group(1)


HELP = '''= BSM Karma Builder =

#type: node
#context: lop
#icon: LOP/subnet

"""Opens BSM Karma Builder, the tool that builds Karma lighting, sky, atmosphere, materials and render
settings in /stage."""

This node carries the whole tool. It passes its input through unchanged, so it can sit anywhere in a
network; its only job is to open the builder.

@parameters

Open Karma Builder:
    #id: open_builder

    Opens the builder window. The window builds and updates its nodes in /stage; this node is not part of
    that network.

Create Shelf Button:
    #id: create_shelf

    Creates a shelf called BSM Karma with a Karma Builder button that opens the window, so the node is not
    needed again.

@related

- [Node:lop/karmarendersettings]
- [Node:lop/materiallinker]
'''

TOOLS_SHELF = """<?xml version="1.0" encoding="UTF-8"?>
<shelfDocument>
  <tool name="$HDA_DEFAULT_TOOL" label="$HDA_LABEL" icon="$HDA_ICON">
    <toolMenuContext name="neteditor">
      <contextOpType>$HDA_TABLE_AND_NAME</contextOpType>
    </toolMenuContext>
    <toolSubmenu>BSM</toolSubmenu>
    <script scriptType="python"><![CDATA[import loptoolutils

loptoolutils.genericTool(kwargs, '$HDA_NAME')]]></script>
  </tool>
</shelfDocument>
"""


# --------------------------------------------------
def build(output):
    output = os.path.abspath(output).replace("\\", "/")
    os.makedirs(os.path.dirname(output), exist_ok=True)
    if os.path.exists(output):
        os.remove(output)
    hou.hipFile.clear(suppress_save_prompt=True)

    version = script_version()
    stage = hou.node("/stage")
    subnet = stage.createNode("subnet", "bsm_karma_builder")
    asset = subnet.createDigitalAsset(
        name=OP_NAME, hda_file_name=output, description=OP_LABEL,
        min_num_inputs=0, max_num_inputs=1, ignore_external_references=True,
    )
    definition = asset.type().definition()

    # the subnet output reads the first indirect input
    output_node = asset.node("output0")
    inputs = asset.indirectInputs()
    if inputs:
        output_node.setInput(0, inputs[0])

    ptg = hou.ParmTemplateGroup()
    button = hou.ButtonParmTemplate(
        "open_builder", "Open Karma Builder",
        script_callback="hou.phm().open_builder(kwargs['node'])",
        script_callback_language=hou.scriptLanguage.Python,
    )
    button.setHelp("Opens the BSM Karma Builder window.")
    ptg.append(button)
    shelf_button = hou.ButtonParmTemplate(
        "create_shelf", "Create Shelf Button",
        script_callback="hou.phm().install_shelf(kwargs['node'])",
        script_callback_language=hou.scriptLanguage.Python,
    )
    shelf_button.setHelp("Creates a shelf with a Karma Builder button that opens the window without needing this node.")
    ptg.append(shelf_button)
    ptg.append(hou.LabelParmTemplate("tool_version", "Version", column_labels=(version,)))
    ptg.append(hou.LabelParmTemplate("requirements", "Requires", column_labels=("Houdini 21 or 22, Solaris and Karma",)))
    definition.setParmTemplateGroup(ptg)

    for name, code in package_sources().items():
        definition.addSection(SOURCE_PREFIX + name, code)
    definition.addSection("bsm_karma_presets_json", read_text(PACKAGE, "presets.json"))
    definition.addSection("PythonModule", read_text("tools", "hda_python_module.py"))
    definition.addSection("LICENSE.txt", read_text("LICENSE"))
    definition.addSection("Help", HELP)
    definition.addSection("Tools.shelf", TOOLS_SHELF)
    # the icon sits at the root of the repository; the old "Karma builder" folder is still looked at
    icon_path = next((p for p in ("icone_Bsm_Karma.png", os.path.join("Karma builder", "icone_Bsm_Karma.png"))
                      if os.path.isfile(os.path.join(ROOT, p))), "")
    if icon_path:
        definition.addSection("icon.png", read_bytes(icon_path))
        definition.setIcon("opdef:/{}?icon.png".format(asset.type().nameWithCategory()))
    definition.setVersion(version)
    definition.setComment("BSM Karma Builder {}. Licensed under PolyForm Noncommercial 1.0.0 (see the LICENSE.txt section).".format(version))

    definition.save(output, template_node=asset)
    hou.hipFile.clear(suppress_save_prompt=True)
    remove_houdini_backups(output)
    return output, version


# ------------------------------------------------------------
# Houdini keeps a backup copy of every overwritten library next to it, drop this asset's copies.
def remove_houdini_backups(output):
    backup_dir = os.path.join(os.path.dirname(output), "backup")
    stem = os.path.splitext(os.path.basename(output))[0]
    if not os.path.isdir(backup_dir):
        return
    for name in os.listdir(backup_dir):
        if name.startswith(stem):
            os.remove(os.path.join(backup_dir, name))
    if not os.listdir(backup_dir):
        os.rmdir(backup_dir)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUTPUT
    path, version = build(target)
    print("built {} (tool version {}, {} KB)".format(path, version, os.path.getsize(path) // 1024))
