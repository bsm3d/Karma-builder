# GUI lifecycle test for bsm_karma, run by Houdini at startup (scripts/123.py), see tests/run_tests.ps1.
#
# Camera choice, panels opened and closed, Clear All, Esc, relaunch and module reload, nothing left after a close.
# Results go to the file in BSM_RESULT. Houdini can segfault on hou.exit once a Karma viewport was used
# (reproduced
# without this tool), so the result file counts, not the exit code.
#
# Revision : 10-10-2026 | Auteur : BSM
import gc
import os
import sys
import tempfile
import traceback
import weakref

import hou
from hutil.Qt import QtCore, QtGui, QtWidgets

# Houdini runs this file without __file__: the runner (tests/run_tests.ps1) passes the project root.
ROOT = os.environ["BSM_ROOT"]
OUT = os.environ.get("BSM_RESULT") or os.path.join(tempfile.gettempdir(), "bsm_gui_result.txt")
MTLX = os.path.join(ROOT, "tests", "fixtures", "red.mtlx").replace("\\", "/")
lines = []
failures = []
S = {}


# ----------------------------------------
def say(*parts):
    lines.append(" ".join(str(p) for p in parts))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


#------------------------------------------------------------
def check(label, ok, detail=""):
    say(("PASS " if ok else "FAIL ") + label + ((" | " + str(detail)) if detail != "" else ""))
    if not ok:
        failures.append(label)


# --------------------------------------------------------------------------------
def pump():
    QtWidgets.QApplication.processEvents()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    gc.collect()
    QtWidgets.QApplication.processEvents()


# ------------------------------------------------------------
def live_dialogs():
    return [w for w in QtWidgets.QApplication.topLevelWidgets() if type(w).__name__ == "KarmaBuilderUI"]


# ------------------------------------------------------------
def dialog_objects():
    return [o for o in gc.get_objects() if type(o).__name__ == "KarmaBuilderUI"]


def panels():
    return len(hou.ui.floatingPanels())


# ----------------------------------------------------------------
def step_setup():
    sys.path.insert(0, ROOT)
    import bsm_karma
    S["k"] = bsm_karma
    stage = hou.node("/stage")
    S["sph"] = stage.createNode("sphere", "my_sphere")
    S["box"] = stage.createNode("cube", "my_cube")
    S["gcam"] = stage.createNode("camera", "geo_cam")
    S["gcam"].parm("tz").set(3)
    S["mrg"] = stage.createNode("merge", "user_geo")
    for i, n in enumerate((S["sph"], S["box"], S["gcam"])):
        S["mrg"].setInput(i, n)
    S["mycam"] = stage.createNode("camera", "my_cam")
    S["mycam"].parm("tz").set(9)
    S["base_panels"] = panels()
    say("baseline floating panels:", S["base_panels"])

    # catalog source set by someone else before the tool opens: must be back after it closes
    k = S["k"]
    wrapper = k._material_catalog_file(MTLX)
    S["wrapper"] = wrapper
    other = hou.AssetGalleryDataSource(wrapper, "%type:Material")
    check("a .mtlx wrapped in a USD layer is a valid gallery source", other.isValid(), wrapper)
    hou.ui.setSharedAssetGalleryDataSource(other, "material")
    S["other_source"] = other
    ids = [i for i in other.itemIds() if other.typeName(i) == "material"]
    asset_files = [other.filePath(i) for i in ids]
    check("wrapper source lists the material", len(ids) == 1 and other.label(ids[0]) == "M_red", [other.label(i) for i in ids])
    import json
    payload = json.dumps({"ids": ids, "types": ["x"], "assettypes": ["material"], "labels": ["M_red"], "filepaths": asset_files,
                          "asset_data": [other.blindData(ids[0]).decode("ascii")], "sources": [[wrapper, "%type:Material"]]})
    assets, failures_ = k._parse_catalog_drop(payload)
    real = os.path.normcase(os.path.normpath(MTLX))
    check("a drop from the wrapper references the real .mtlx", assets and os.path.normcase(os.path.normpath(hou.text.expandString(assets[0]["file_path"]))) == real, assets)
    k.main()
    S["ui"] = k.bsm_karma_ui_dialog
    if os.environ.get("BSM_ENGINE"):
        S["ui"].combo_engine.setCurrentText(os.environ["BSM_ENGINE"])
    S["ref1"] = weakref.ref(S["ui"])
    check("main() created a dialog", S["ui"] is not None and S["ui"].isVisible())
    check("one live dialog", len(live_dialogs()) == 1, len(live_dialogs()))
    check("delete-on-close set", S["ui"].testAttribute(QtCore.Qt.WA_DeleteOnClose))
    check("timer parented to the dialog", S["ui"]._hdri_preview_timer.parent() is S["ui"])


# ------------------------------------
def step_cameras():
    ui, k = S["ui"], S["k"]
    labels = [ui.combo_camera.itemText(i) for i in range(ui.combo_camera.count())]
    check("camera combo lists new + my_cam + geo_cam", labels[0] == "Create New Camera" and "/stage/my_cam" in labels and "/stage/geo_cam" in labels, labels)
    check("new-camera options enabled on 'Create New Camera'", ui.w_new_camera.isEnabled())

    # choose a geometry source: USD camera prims must show up
    ui.combo_geo_source.setCurrentIndex(ui.combo_geo_source.findText("/stage/user_geo"))
    labels = [ui.combo_camera.itemText(i) for i in range(ui.combo_camera.count())]
    check("USD camera prim offered after choosing the source", "USD: /cameras/geo_cam" in labels, labels)

    ui.combo_camera.setCurrentIndex(ui.combo_camera.findData("/stage/my_cam"))
    check("new-camera options disabled for an existing camera", not ui.w_new_camera.isEnabled())
    check("config carries the choice", ui._collect_config()["camera_choice"] == "/stage/my_cam")
    ui.combo_camera.setCurrentIndex(ui.combo_camera.findData("usd:/cameras/geo_cam"))
    check("config carries the USD choice", ui._collect_config()["camera_choice"] == "usd:/cameras/geo_cam")
    ui.combo_camera.setCurrentIndex(0)
    ui.spin_cam_focal.setValue(50.0)
    ui.on_build()
    rc = hou.node("/stage/render_cam")
    check("build created the camera with the UI focal", rc is not None and abs(rc.parm("focalLength").eval() - 50.0) < 1e-6)

    # a camera deleted behind the tool's back disappears from the list when it opens
    tmp = hou.node("/stage").createNode("camera", "tmp_cam")
    ui.combo_camera.popupAboutToShow.emit()
    check("popup refresh lists a camera created since", ui.combo_camera.findData(tmp.path()) >= 0)
    ui.combo_camera.setCurrentIndex(ui.combo_camera.findData(tmp.path()))
    tmp.destroy()
    ui.combo_camera.popupAboutToShow.emit()
    check("popup refresh drops the deleted camera and falls back", ui._current_camera_choice() == "Create New Camera", ui._current_camera_choice())

    # look through: the lock applies on the next event-loop pass, so the position is read in the next step
    ui.on_look_through_camera()
    check("look through opened the Karma viewport (no viewer on /stage yet)", ui._karma_scene_viewer is not None and panels() == S["base_panels"] + 1, panels())


# ------------------------------------------------------------
def step_panels():
    ui = S["ui"]
    viewer = ui._get_active_scene_viewer()
    check("active viewer is the tool's, on /stage", viewer is ui._karma_scene_viewer and ui._is_stage_viewer(viewer))
    pos = viewer.curViewport().viewTransform().extractTranslates()
    check("look through locked the viewport on render_cam", abs(pos[1] - 2.0) < 1e-3 and abs(pos[2] - 8.0) < 1e-3, tuple(round(v, 3) for v in pos))
    ui.on_open_viewport()
    after_viewport = panels()
    ui.on_open_karma_settings()
    ui.on_open_karma_settings()
    ui.on_open_karma_settings()
    after_settings = panels()
    check("opening the Karma viewport again reuses the panel", after_viewport == S["base_panels"] + 1, (S["base_panels"], after_viewport))
    ui.on_look_through_camera()
    check("look through on an existing /stage viewer locks it without a new panel", panels() == S["base_panels"] + 2 and "Viewport locked to /cameras/render_cam" in ui.txt_log.toPlainText(), panels())
    check("three clicks on Karma Settings reuse one parameter pane", after_settings == S["base_panels"] + 2, after_settings)
    check("tool tracks both panels", ui._karma_scene_viewer is not None and ui._parm_pane_tab is not None)
    vp = ui._karma_scene_viewer.curViewport()
    check("floating viewport locked to the render camera", abs(vp.viewTransform().extractTranslates()[2] - 8.0) < 1e-3, tuple(vp.viewTransform().extractTranslates()))


# --------------------------------------------------
def step_catalog_and_clear():
    ui, k = S["ui"], S["k"]
    ui.combo_mat_source.setCurrentIndex(1)
    ui.on_connect_material_library()
    check("previous catalog source remembered", ui._material_source_changed, ui._material_source_changed)

    if os.environ.get("BSM_SKIP_CLEAR") == "1":
        return
    # build with materials so the linker exists, then Clear All must take every tool node away
    ui.combo_geo_source.setCurrentIndex(ui.combo_geo_source.findText("/stage/user_geo"))
    ui.on_build()
    linker = k._get_or_create_material_linker(hou.node("/stage"))
    k._insert_material_linker_in_chain(hou.node("/stage"), linker, ui.log_message)
    nodes = ui._collect_tool_stage_nodes()
    names = sorted(n.name() for n in nodes.values())
    check("tool nodes found for Clear All", "material_linker" in names and "geo_merge" in names and "karma_settings" in names, names)
    deleted, skipped = ui._destroy_tool_stage_nodes(nodes)
    left = sorted(n.name() for n in hou.node("/stage").children() if k._is_tool_node_candidate(n, n.name()))
    check("Clear All removed every tool node", not left and not skipped, (left, skipped))
    user = [n.name() for n in hou.node("/stage").children()]
    check("user nodes untouched by Clear All", all(x in user for x in ("my_sphere", "my_cube", "geo_cam", "user_geo", "my_cam")), user)


def step_escape():
    ui = S["ui"]
    ev = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(ui, ev)
    S["release_errors"] = list(ui._release_errors)
    check("release ran without a single error", S["release_errors"] == [], S["release_errors"])
    S["ui"] = None
    del ui


# ------------------------------------
def step_after_escape():
    pump()
    k = S["k"]
    check("Esc closed the floating panels", panels() == S["base_panels"], (panels(), S["base_panels"]))
    check("dialog object collected", S["ref1"]() is None)
    check("no live KarmaBuilderUI top-level", not live_dialogs(), live_dialogs())
    check("module reference cleared", k.bsm_karma_ui_dialog is None)
    check("no KarmaBuilderUI python object left", not dialog_objects(), len(dialog_objects()))
    main_win = hou.qt.mainWindow()
    check("no leftover child of the main window", not [c for c in main_win.findChildren(QtWidgets.QDialog) if type(c).__name__ == "KarmaBuilderUI"])


# ----------------------------------------
def step_cycles():
    k = S["k"]
    refs = []
    for i in range(5):
        k.main()
        refs.append(weakref.ref(k.bsm_karma_ui_dialog))
        pump()
    # five launches in a row: each launch closes the previous one
    pump()
    alive = [r for r in refs if r() is not None]
    check("5 launches in a row leave exactly one dialog", len(alive) == 1 and len(live_dialogs()) == 1, (len(alive), len(live_dialogs())))
    check("module reference points at the newest dialog", k.bsm_karma_ui_dialog is refs[-1]())
    k.bsm_karma_ui_dialog.close()
    pump()
    pump()
    check("after close: module reference cleared", k.bsm_karma_ui_dialog is None)
    check("after close: all five collected", all(r() is None for r in refs), [r() is not None for r in refs])
    check("after close: no dialog object left", not dialog_objects(), len(dialog_objects()))
    check("floating panels at baseline", panels() == S["base_panels"], panels())

    # reload keeps the reference so the next launch can still close the old dialog
    import importlib
    k.main()
    first = k.bsm_karma_ui_dialog
    ref_first = weakref.ref(first)
    del first
    importlib.reload(k)
    check("reload keeps the dialog reference", k.bsm_karma_ui_dialog is not None)
    k.main()
    pump()
    pump()
    check("launch after reload closes the previous dialog", ref_first() is None and len(live_dialogs()) == 1, (ref_first() is None, len(live_dialogs())))
    k.bsm_karma_ui_dialog.close()
    pump()
    pump()
    check("final state clean", not live_dialogs() and not dialog_objects())


# ----------------------------------------------------------------------
def step_gallery():
    d = QtWidgets.QDialog(hou.qt.mainWindow())
    lay = QtWidgets.QVBoxLayout(d)
    g = hou.qt._createAssetGallery("material")
    lay.addWidget(g)
    d.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
    d.show()
    S["gal_dialog"] = d
    say("gallery dialog shown")


# ------------------------------------
def step_gallery_close():
    d = S.pop("gal_dialog")
    d.close()
    pump()
    say("gallery dialog closed")


# --------------------------------------------------------------------------------
def step_dlgclose():
    k = S["k"]
    S["ui"].close()
    S["ui"] = None
    pump()
    say("tool dialog closed, left:", len(live_dialogs()))


# ------------------------------------------------------------
# The HDA: pressing its button opens the same dialog, a second press replaces it, closing leaves nothing.
def step_hda():
    path = os.path.join(ROOT, "hda", "bsm_karma_builder.hda")
    hou.hda.installFile(path)
    node = hou.node("/stage").createNode("bsm::karma_builder::1.0")
    node.parm("open_builder").pressButton()
    module = sys.modules.get("bsm_karma_hda")
    dialog = module.bsm_karma_ui_dialog if module else None
    check("the button opens the dialog", dialog is not None and dialog.isVisible() and len(live_dialogs()) == 1)
    check("presets come from the asset", dialog is not None and dialog.combo_time_preset.findText("Golden Hour") >= 0)
    first = weakref.ref(dialog)
    del dialog
    node.parm("open_builder").pressButton()
    pump()
    pump()
    check("a second press replaces the first dialog", first() is None and len(live_dialogs()) == 1, len(live_dialogs()))
    module.bsm_karma_ui_dialog.close()
    pump()
    pump()
    check("closing it leaves nothing behind", not live_dialogs() and not dialog_objects() and module.bsm_karma_ui_dialog is None)
    tools = [tool for tool in hou.shelves.tools().values() if "karma_builder" in tool.name().lower()]
    check("the node has a Tab menu tool", bool(tools), [tool.name() for tool in tools])
    if tools:
        check("the tool is in the BSM submenu", "BSM" in (tools[0].toolMenuLocations() if hasattr(tools[0], "toolMenuLocations") else ["BSM"]),
              [getattr(tools[0], "toolMenuLocations", lambda: [])()])


# ------------------------------------------------------------------------
def step_quit():
    say("FAILURES:", failures if failures else "none")
    say("DONE")
    hou.exit(suppress_save_prompt=True)


ALL = {
    "wait": (4000, lambda: say("waited")),
    "gallery": (1500, step_gallery), "gallery_close": (1500, step_gallery_close), "dlgclose": (1500, step_dlgclose),
    "setup": (2500, step_setup), "cameras": (800, step_cameras), "panels": (800, step_panels),
    "catalog": (800, step_catalog_and_clear), "escape": (500, step_escape), "after": (1200, step_after_escape),
    "cycles": (500, step_cycles), "hda": (500, step_hda), "quit": (500, step_quit),
}
ORDER = os.environ.get("BSM_STEPS", "setup,cameras,panels,catalog,escape,after,cycles,hda,quit").split(",")
STEPS = [ALL[name] for name in ORDER]



# --------------------------------------------------
def run(remaining):
    if not remaining:
        return
    delay, fn = remaining[0]

    def go():
        try:
            fn()
        except Exception:
            say("EXCEPTION in", fn.__name__, traceback.format_exc())
            failures.append("exception in " + fn.__name__)
            hou.exit(suppress_save_prompt=True)
            return
        run(remaining[1:])

    QtCore.QTimer.singleShot(delay, go)


run(STEPS)
