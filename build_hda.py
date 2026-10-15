# Builds the BSM Karma Builder HDA from the project files: hython build_hda.py [output.hda]
#
# The asset is a LOP node that passes its input through and carries the tool as sections (bsm_karma.py, presets,
# loader, license, icon). It is rebuilt from the sources each time, bsm_karma.py stays the single source of truth.
#
# Revision : 10-10-2026 | Auteur : BSM
import os
import re
import sys

import hou

HERE = os.path.dirname(os.path.abspath(__file__))
# the project root holds bsm_karma.py: the script's own folder when the files sit side by side, else its parent (tools/)
ROOT = HERE if os.path.isfile(os.path.join(HERE, "bsm_karma.py")) else os.path.dirname(HERE)
DEFAULT_OUTPUT = os.path.join(ROOT, "bsm_karma_builder.hda" if ROOT == HERE else os.path.join("hda", "bsm_karma_builder.hda"))

OP_NAME = "bsm::karma_builder::1.0"
OP_LABEL = "BSM Karma Builder"

# ------------------------------------------------------------
# First existing candidate, each one a path relative to ROOT: the project is laid out either flat or with tools/.
def find_file(*candidates):
    for rel in candidates:
        if os.path.isfile(os.path.join(ROOT, rel)):
            return os.path.join(ROOT, rel)
    raise FileNotFoundError("none of {} under {}".format(", ".join(candidates), ROOT))


# ------------------------------------------------------------
def read_text(*candidates):
    with open(find_file(*candidates), encoding="utf-8", newline="") as handle:
        return handle.read().replace("\r\n", "\n")


# ----------------------------------------
def read_bytes(*candidates):
    with open(find_file(*candidates), "rb") as handle:
        return handle.read()

#------------------------------------------------------------
def script_version():
    match = re.search(r'^SCRIPT_VERSION = "([^"]+)"', read_text("bsm_karma.py"), re.MULTILINE)
    if not match:
        raise RuntimeError("SCRIPT_VERSION not found in bsm_karma.py")
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

@related

- [Node:lop/karmarendersettings]
- [Node:lop/materiallinker]
'''

TOOLS_SHELF = """<?xml version="1.0" encoding="UTF-8"?>
<shelfDocument>
  <tool name="$HDA_DEFAULT_TOOL" label="$HDA_LABEL" icon="$HDA_ICON">
    <toolMenuContext name="neteditor">
      <contextNetType>LOP</contextNetType>
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
    ptg.append(hou.LabelParmTemplate("tool_version", "Version", column_labels=(version,)))
    ptg.append(hou.LabelParmTemplate("requirements", "Requires", column_labels=("Houdini 21 or 22, Solaris and Karma",)))
    definition.setParmTemplateGroup(ptg)

    definition.addSection("bsm_karma_py", read_text("bsm_karma.py"))
    definition.addSection("bsm_karma_presets_json", read_text("bsm_karma_presets.json"))
    definition.addSection("PythonModule", read_text("hda_python_module.py", os.path.join("tools", "hda_python_module.py")))
    definition.addSection("LICENSE.txt", read_text("LICENSE.txt", "LICENSE", os.path.join("Informations", "LICENSE.txt")))
    definition.addSection("Help", HELP)
    definition.addSection("Tools.shelf", TOOLS_SHELF)
    icon_path = os.path.join("Karma builder", "icone_Bsm_Karma.png")
    if os.path.isfile(os.path.join(ROOT, icon_path)):
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
