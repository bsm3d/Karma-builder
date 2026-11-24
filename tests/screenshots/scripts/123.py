# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Takes the documentation screenshots into the BSM_SHOT_DIR folder, launched by tests/run_tests.ps1 with its screenshot switch.

# Takes the documentation screenshots into BSM_SHOT_DIR (default docs/screenshots): a sphere and a cube, MaterialX on the sphere, offline sources only.
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

# (tab, file name, what to set before the picture). The names are the ones docs/index.html uses.
def _cloud_type(index):
    return lambda ui: ui.combo_cloud_type.setCurrentIndex(index)


def _catalog_view(index):
    return lambda ui: ui.mat_browser.combo_view.setCurrentIndex(index) if ui.mat_browser is not None else None


TABS = [("Scene", "scene", None), ("Lighting", "lighting", None), ("Night Sky", "night_sky", None),
        ("Atmosphere", "atmosphere_3d_clouds", _cloud_type(0)), ("Atmosphere", "atmosphere_2d_clouds", _cloud_type(1)),
        ("Materials", "materials", _catalog_view(0)), ("Materials", "materials_list", _catalog_view(1)),
        ("Materials", "materials_categories", _catalog_view(2)),
        ("Render", "render", None), ("Passes", "passes", None), ("Export", "export", None),
        ("Log", "log", None), ("About", "about", None)]


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
    label, filename, prepare = TABS[index]
    if label in ("Render", "Passes", "Export"):
        tabs.setCurrentIndex([tabs.tabText(i) for i in range(tabs.count())].index("Output"))
        ui.tabs_output.setCurrentIndex([ui.tabs_output.tabText(i) for i in range(ui.tabs_output.count())].index(label))
    else:
        tabs.setCurrentIndex([tabs.tabText(i) for i in range(tabs.count())].index(label))
    if prepare is not None:
        prepare(ui)
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
