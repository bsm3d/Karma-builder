# Takes the documentation screenshots (tests/run_tests.ps1 -Screenshots) into BSM_SHOT_DIR, default
# docs/screenshots.
#
# Scene: a sphere and a cube, MaterialX on the sphere. Offline sources only, so the pictures do not need the
# network.
#
# Revision : 10-10-2026 | Auteur : BSM
import os
import sys
import tempfile
import traceback

import hou
from hutil.Qt import QtCore, QtWidgets

ROOT = os.environ["BSM_ROOT"]
OUT = os.environ.get("BSM_RESULT") or os.path.join(tempfile.gettempdir(), "bsm_gui_result.txt")
SHOT_DIR = os.environ.get("BSM_SHOT_DIR") or os.path.join(ROOT, "docs", "screenshots")
MTLX = os.path.join(ROOT, "tests", "fixtures", "red.mtlx").replace("\\", "/")
lines = []
S = {}

TABS = [("Scene", "scene"), ("Lighting", "lighting"), ("Atmosphere", "atmosphere"), ("Materials", "materials"),
        ("Render", "render"), ("Passes", "passes"), ("Export", "export")]


# ------------------------------------------------------------
def say(*parts):
    lines.append(" ".join(str(p) for p in parts))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

# ------------------------------------------------------------
def setup():
    sys.path.insert(0, ROOT)
    import bsm_karma as k
    S["k"] = k
    os.makedirs(SHOT_DIR, exist_ok=True)
    stage = hou.node("/stage")
    sphere = stage.createNode("sphere", "ball")
    cube = stage.createNode("cube", "box")
    cube.parm("tx").set(2.5)
    geo = stage.createNode("merge", "geometry")
    geo.setInput(0, sphere)
    geo.setInput(1, cube)

    k.main()
    ui = k.bsm_karma_ui_dialog
    S["ui"] = ui
    ui.resize(720, 860)
    ui.combo_geo_source.setCurrentIndex(ui.combo_geo_source.findText(geo.path()))
    ui.chk_enable_fog.setChecked(True)
    ui.combo_fog_preset.setCurrentIndex(ui.combo_fog_preset.findText("Light Mist"))
    ui.chk_enable_clouds.setChecked(True)
    ui.combo_cloud_preset.setCurrentIndex(ui.combo_cloud_preset.findText("Low Cumulus"))
    ui.combo_time_preset.setCurrentIndex(ui.combo_time_preset.findText("Golden Hour"))
    ui.on_build()

    linker = k._get_or_create_material_linker(stage)
    k._insert_material_linker_in_chain(stage, linker, ui.log_message)
    name, prim = k._list_materials_in_file(MTLX)[0]
    k._linker_assign(linker, k._linker_add_reference(linker, MTLX, prim, name), ["/ball"])
    ui.refresh_material_targets()
    say("PASS scene ready")


# ------------------------------------------------------------
def shoot(index):
    ui = S["ui"]
    tabs = ui.findChild(QtWidgets.QTabWidget)
    label, filename = TABS[index]
    tabs.setCurrentIndex([tabs.tabText(i) for i in range(tabs.count())].index(label))
    QtWidgets.QApplication.processEvents()

    def save():
        path = os.path.join(SHOT_DIR, filename + ".png")
        ok = ui.grab().save(path)
        say(("PASS" if ok else "FAIL"), "saved", path)
        run(S["rest"])
    QtCore.QTimer.singleShot(900, save)


#----------------------------------------
def finish():
    say("DONE")
    S["ui"].close()
    hou.exit(suppress_save_prompt=True)


def run(remaining):
    S["rest"] = remaining
    if not remaining:
        QtCore.QTimer.singleShot(300, finish)
        return
    index, rest = remaining[0], remaining[1:]
    S["rest"] = rest
    try:
        shoot(index)
    except Exception:
        say("EXCEPTION", traceback.format_exc())
        hou.exit(suppress_save_prompt=True)

# ------------------------------------------------------------
def start():
    try:
        setup()
    except Exception:
        say("EXCEPTION", traceback.format_exc())
        hou.exit(suppress_save_prompt=True)
        return
    QtCore.QTimer.singleShot(1500, lambda: run(list(range(len(TABS)))))


QtCore.QTimer.singleShot(2500, start)
