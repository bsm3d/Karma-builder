# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : GUI lifecycle test for bsm_karma, run by Houdini at startup through tests/run_tests.ps1.

# Checks camera choice, panels, Clear All, Esc, relaunch and module reload, and that nothing is left after a close.
# Results go to the file in BSM_RESULT: Houdini can segfault on hou.exit after a Karma viewport, so that file counts, not the exit code.
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


# --------------------------------------------------------------------------------
# Text that does not fit its widget, widgets that overlap and widgets pushed out of their tab, in the font and the
# style of this Houdini. Combo boxes elide their text, so they are left out.
def layout_problems(ui):
    tabs = ui.findChild(QtWidgets.QTabWidget)
    problems = []
    # every page, the ones of the Output tab included: a page that is not shown has no size to check
    pages = []
    for index in range(tabs.count()):
        inner = tabs.widget(index)
        if isinstance(inner, QtWidgets.QTabWidget) and inner is not getattr(ui, "_shader_tabs", None):
            pages.extend((tabs.tabText(index) + "/" + inner.tabText(sub), [(tabs, index), (inner, sub)]) for sub in range(inner.count()))
        else:
            pages.append((tabs.tabText(index), [(tabs, index)]))
    for name, steps in pages:
        for holder, position in steps:
            holder.setCurrentIndex(position)
        # folding groups nest three layouts: one pass of events is not enough for the sizes to settle
        for _ in range(12):
            QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 20)
        scroll = steps[-1][0].widget(steps[-1][1])
        if isinstance(scroll, QtWidgets.QScrollArea) and scroll.horizontalScrollBar().isVisible():
            problems.append("{}: horizontal scroll bar, the tab needs {} px".format(name, scroll.widget().minimumSizeHint().width()))
        shown = []
        for w in scroll.findChildren(QtWidgets.QWidget):
            chain, ok = w, True
            while chain is not None and chain is not ui:
                ok = ok and chain.isVisibleTo(ui)
                chain = chain.parentWidget()
            if ok and w.width() > 0:
                shown.append(w)
        for w in shown:
            if isinstance(w, QtWidgets.QLabel) and not w.wordWrap() and w.text() and not ('<' in w.text() and '>' in w.text()):
                if w.fontMetrics().horizontalAdvance(w.text()) > w.contentsRect().width() + 1:
                    problems.append("{}: label '{}' is cut".format(name, w.text()[:40]))
            # an icon-only tool button keeps its text for the tooltip: nothing of it is drawn (Houdini's gallery toolbar)
            elif isinstance(w, QtWidgets.QToolButton) and w.toolButtonStyle() == QtCore.Qt.ToolButtonIconOnly:
                continue
            elif isinstance(w, (QtWidgets.QPushButton, QtWidgets.QCheckBox, QtWidgets.QRadioButton, QtWidgets.QToolButton)) and w.text():
                spare = 22 if isinstance(w, (QtWidgets.QCheckBox, QtWidgets.QRadioButton)) else 12
                if w.fontMetrics().horizontalAdvance(w.text().replace("&", "")) > w.width() - spare:
                    problems.append("{}: button '{}' is cut".format(name, w.text()[:40]))
        parents = {}
        for w in shown:
            parents.setdefault(w.parentWidget(), []).append(w)
        for parent, kids in parents.items():
            if parent is None or isinstance(parent, (QtWidgets.QAbstractScrollArea, QtWidgets.QTabBar)):
                continue
            for i in range(len(kids)):
                for j in range(i + 1, len(kids)):
                    common = kids[i].geometry().intersected(kids[j].geometry())
                    if common.width() > 2 and common.height() > 2:
                        problems.append("{}: {} overlaps {}".format(name, kids[i].metaObject().className(), kids[j].metaObject().className()))
    return sorted(set(problems))


# ------------------------------------
def step_layout():
    ui = S["ui"]
    problems = layout_problems(ui)
    check("no text cut, no overlapping widgets, no horizontal scroll bar in any tab", not problems, problems[:6])
    ui.findChild(QtWidgets.QTabWidget).setCurrentIndex(0)


# --------------------------------------------------------------------------------
# The snapshot preview shows the whole frame at the ratio of the image, nothing cropped.
def step_preview():
    ui = S["ui"]
    tabs = ui.findChild(QtWidgets.QTabWidget)
    tabs.setCurrentIndex([tabs.tabText(i) for i in range(tabs.count())].index("Output"))
    ui.tabs_output.setCurrentIndex([ui.tabs_output.tabText(i) for i in range(ui.tabs_output.count())].index("Export"))
    pump()
    image = QtGui.QImage(1920, 1080, QtGui.QImage.Format_RGB32)
    painter = QtGui.QPainter(image)
    painter.fillRect(0, 0, 960, 1080, QtGui.QColor("#ff0000"))
    painter.fillRect(960, 0, 960, 1080, QtGui.QColor("#0000ff"))
    painter.end()
    ui._snapshot_source_image = image
    ui._update_snapshot_slots_ui()
    ui._update_snapshot_preview()
    pump()
    pump()
    label = ui.lbl_snapshot_preview
    width, height = label.width(), label.height()
    check("the preview of a 1080p snapshot is 16:9 (or at the height limit)", abs(height - min(label.MAX_HEIGHT, width * 9 / 16)) <= 2, (width, height))
    frame = label.pixmap().toImage()
    check("the preview holds the whole frame: both edges of the picture are there", frame.pixelColor(2, height // 2).red() > 200 and frame.pixelColor(width - 3, height // 2).blue() > 200)
    ui.on_clear_snapshot_slots()
    pump()
    check("clearing the slots gives the short strip back", label.height() == label.EMPTY_HEIGHT)
    ui.findChild(QtWidgets.QTabWidget).setCurrentIndex(0)


# --------------------------------------------------------------------------------
# The HDRI preview stays inside its tab whatever the size of the picture, and a format it cannot read gives a message.
def step_hdri_preview():
    ui = S["ui"]
    ui.combo_env_type.setCurrentText("HDRI Image")
    ui.findChild(QtWidgets.QTabWidget).setCurrentIndex(1)
    pump()
    big = os.path.join(tempfile.gettempdir(), "bsm_gui_hdri_test.png").replace("\\", "/")
    huge = QtGui.QImage(8000, 4000, QtGui.QImage.Format_RGB32)
    huge.fill(QtGui.QColor("#3366aa"))
    huge.save(big)
    ui.line_hdri_path.setText(big)
    ui._do_hdri_preview()
    pump()
    pump()
    label = ui.lbl_hdri_preview
    page = ui.findChild(QtWidgets.QTabWidget).widget(1)
    check("the HDRI preview shows a 8000 x 4000 picture", label.pixmap() is not None and not label.pixmap().isNull() and label.text() == "", label.text())
    check("the HDRI preview is 2:1 and stays inside the tab", abs(label.height() - min(label.MAX_HEIGHT, label.width() / 2)) <= 2 and not page.horizontalScrollBar().isVisible(), (label.width(), label.height()))
    ui.line_hdri_path.setText(os.path.join(tempfile.gettempdir(), "bsm_no_such_hdri.exr").replace("\\", "/"))
    ui._do_hdri_preview()
    pump()
    check("a missing HDRI gives a message and the short strip", label.text() == "HDRI file not found" and label.height() == label.EMPTY_HEIGHT, label.text())
    try:
        os.remove(big)
    except OSError:
        pass
    ui.combo_env_type.setCurrentText("Physical Sky")
    ui.findChild(QtWidgets.QTabWidget).setCurrentIndex(0)


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
    path = os.path.join(ROOT, "bsm_karma_builder.hda")
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
# bug trouvé et fixé: switching to the night preset left the moon and the stars out until the Build button was pressed
def step_live():
    ui = S["ui"]
    stage = hou.node("/stage")
    ui.combo_scene_mode.setCurrentText("Environment")
    ui.chk_live_update.setChecked(False)
    ui.combo_sky_preset.setCurrentText("Clear Sky (Midday)")
    ui.on_build()
    check("live: a day build has no moon and no stars", stage.node("sky_moon") is None and stage.node("sky_stars_ref") is None)
    ui.chk_live_update.blockSignals(True)
    ui.chk_live_update.setChecked(True)
    ui.chk_live_update.blockSignals(False)
    ui.combo_sky_preset.setCurrentText("Night / Moonlight")
    ui._live_build()
    check("live: the night preset brings the moon and the stars by itself, no pause", stage.node("sky_moon") is not None
          and (stage.node("sky_stars_ref") is not None or not S["k"].nightsky.night_sources()[1]))
    ui.combo_sky_preset.setCurrentText("Clear Sky (Midday)")
    ui._live_build()
    check("live: and takes them away with the day", stage.node("sky_moon") is None and stage.node("sky_stars_ref") is None)
    ui.chk_live_update.blockSignals(True)
    ui.chk_live_update.setChecked(False)
    ui.chk_live_update.blockSignals(False)


# ------------------------------------------------------------------------
# The Night Sky tab, the composite and the exact sky: a greyed control must mean "not used", and Live Update must watch every one
# of them (the controls moved out of the Lighting tab into folds and a tab of their own).
def step_nightsky():
    ui = S["ui"]
    ui.chk_live_update.blockSignals(True)
    ui.chk_live_update.setChecked(False)
    ui.chk_live_update.blockSignals(False)
    ui.combo_scene_mode.setCurrentText("Environment")
    ui.combo_env_type.setCurrentText("Physical Sky")
    ui.combo_sky_preset.setCurrentText("Clear Sky (Midday)")
    pump()
    index = ui.tabs_main.indexOf(ui.tab_night_scroll)
    check("night sky: the tab works with the physical sky", ui.tabs_main.isTabEnabled(index))

    # the phase of the moon is greyed while the exact sky decides, and while the moon is off
    ui.chk_exact.setChecked(False)
    ui.chk_moon.setChecked(False)
    ui.chk_exact.setChecked(True)
    ui.chk_exact.setChecked(False)
    check("night sky: the moon phase stays greyed after the exact sky when the moon is off", not ui.sld_moon_phase.isEnabled())
    ui.chk_moon.setChecked(True)
    check("night sky: the moon phase works with the moon on", ui.sld_moon_phase.isEnabled())
    ui.chk_exact.setChecked(True)
    ui.chk_moon.setChecked(False)
    ui.chk_moon.setChecked(True)
    check("night sky: switching the moon on does not wake the phase while the exact sky decides", not ui.sld_moon_phase.isEnabled())
    ui.chk_exact.setChecked(False)
    check("night sky: the phase is back without the exact sky", ui.sld_moon_phase.isEnabled())

    # Live Update watches every control of the folds and of the tab
    ui.chk_live_update.blockSignals(True)
    ui.chk_live_update.setChecked(True)
    ui.chk_live_update.blockSignals(False)
    quiet = []
    for name, value in (("chk_exact", True), ("chk_moon", False), ("sld_moon_phase", 0.3), ("sld_moon_halo", 2.0), ("sld_moon_int", 2.0), ("sld_moon_size", 4.0),
                        ("chk_stars", False), ("chk_milky", False), ("sld_stars_int", 2.0), ("sld_stars_size", 2.0), ("sld_stars_twinkle", 0.5),
                        ("sld_stars_glow", 2.0), ("sld_star_time", 5.0), ("chk_sky_plate", True), ("sld_star_lat", 10.0), ("sld_star_lon", 20.0),
                        ("spin_sky_year", 2030), ("spin_sky_month", 3), ("spin_sky_day", 17), ("sld_sky_hour", 3.0), ("sld_sun_int", 7.0),
                        ("sld_sun_size", 2.0), ("spin_sun_temp", 3000), ("sld_sky_azim", 100.0), ("sp_amb_r", 0.5), ("sld_turbidity", 5.0),
                        ("sld_atm_rayleigh", 2.0), ("sld_atm_mie", 2.0), ("sld_hz_blur", 9.0), ("chk_sky_follow_view", True)):
        ui._live_timer.stop()
        widget = getattr(ui, name)
        if hasattr(widget, "setChecked"):
            widget.setChecked(value)
        else:
            widget.setValue(value)
        if not ui._live_timer.isActive():
            quiet.append(name)
    ui._live_timer.stop()
    check("night sky: every control of the folds and of the tab starts a Live Update", not quiet, quiet)
    ui.chk_live_update.blockSignals(True)
    ui.chk_live_update.setChecked(False)
    ui.chk_live_update.blockSignals(False)
    ui.chk_exact.setChecked(False)
    ui.chk_moon.setChecked(True)
    ui.chk_stars.setChecked(True)
    ui.chk_milky.setChecked(True)
    ui.chk_sky_plate.setChecked(False)

    # the composite adds and removes nodes (and the AOVs): Live Update leaves it to the Build button
    ui.on_build()
    ui.chk_sky_plate.setChecked(True)
    check("night sky: the composite is a change of structure, Live Update waits for Build", "sky_plate" in ui._live_structure_changes(), ui._live_structure_changes())
    ui.chk_sky_plate.setChecked(False)

    # the composite renders an EXR: the format says so and cannot be changed meanwhile, then it comes back
    ui.combo_output_format.setCurrentText("PNG")
    ui.chk_sky_plate.setChecked(True)
    check("night sky: with the composite the format is EXR and locked", ui.combo_output_format.currentText() == "EXR" and not ui.combo_output_format.isEnabled(),
          (ui.combo_output_format.currentText(), ui.combo_output_format.isEnabled()))
    check("night sky: and the build asks for EXR", ui._collect_config()["output_format"] == "EXR")
    ui.chk_sky_plate.setChecked(False)
    check("night sky: without it the format is free again, as it was", ui.combo_output_format.currentText() == "PNG" and ui.combo_output_format.isEnabled(),
          (ui.combo_output_format.currentText(), ui.combo_output_format.isEnabled()))
    ui.combo_output_format.setCurrentText("EXR")

    # the note under the render buttons only when Render to Disk really composes
    ui.chk_sky_plate.setChecked(True)
    check("night sky: the note about the sky composite shows with the physical sky", (not ui.lbl_disk_sky.isHidden()))
    ui.chk_exact.setChecked(True)
    ui.chk_moon.setChecked(True)
    ui.combo_env_type.setCurrentText("HDRI Image")
    pump()
    config = ui._collect_config()
    check("night sky: the tab is greyed with an HDRI", not ui.tabs_main.isTabEnabled(index))
    check("night sky: and nothing of it reaches the build (moon, stars, composite, exact sky)",
          not (config["moon_enable"] or config["stars_enable"] or config["sky_plate"] or config["sky_exact"]),
          {key: config[key] for key in ("moon_enable", "stars_enable", "sky_plate", "sky_exact")})
    check("night sky: and the note about the composite is gone", ui.lbl_disk_sky.isHidden())
    ui.combo_env_type.setCurrentText("Physical Sky")
    ui.combo_scene_mode.setCurrentText("Studio")
    pump()
    check("night sky: no note in Studio either", ui.lbl_disk_sky.isHidden())
    ui.combo_scene_mode.setCurrentText("Environment")
    pump()
    check("night sky: the note is back with the physical sky", (not ui.lbl_disk_sky.isHidden()))
    ui.chk_sky_plate.setChecked(False)
    ui.chk_exact.setChecked(False)


# ------------------------------------------------------------------------
# The smallest window the dialog allows: no tab needs a horizontal scroll bar there
def step_small():
    ui = S["ui"]
    old = ui.size()
    ui.resize(ui.minimumWidth(), ui.minimumHeight())
    pump()
    problems = layout_problems(ui)
    check("small window: no text cut, no overlap, no horizontal scroll bar in any tab", not problems, problems[:6])
    ui.resize(old)
    ui.findChild(QtWidgets.QTabWidget).setCurrentIndex(0)
    pump()


# ------------------------------------------------------------------------
# a basic material takes a Normal and a Displacement map: it becomes a PBR material with its own values
def step_shader():
    ui, k = S["ui"], S["k"]
    stage = hou.node("/stage")
    ui.combo_scene_mode.setCurrentText("Environment")
    ui.combo_geo_source.setCurrentIndex(max(0, ui.combo_geo_source.findText(S["mrg"].path())))
    ui.on_build()
    from bsm_karma.basicmaterials import basic_material_file
    from bsm_karma.localmaterials import local_payload
    from bsm_karma.pbrmaterial import read_pbr_spec
    from bsm_karma.linker import _linker_references, _material_linker_node
    ui._assign_payload(local_payload([basic_material_file("Gold")]), ["/my_sphere"])
    ui.refresh_shader_tab()
    check("shader: a basic material is the one being edited", ui._shader_target is not None and not ui._shader_target.get("pbr"), ui._shader_target)
    check("shader: and it has the Texture Maps group (Normal, Displacement)", not ui.grp_pbr.isHidden())
    picture = os.path.join(tempfile.gettempdir(), "bsm_gui_normal.png").replace("\\", "/")
    QtGui.QImage(8, 8, QtGui.QImage.Format_RGB32).save(picture)
    ui._pbr_edits["normal"].setText(picture)
    ui._pbr_map_edited("normal")
    linker = _material_linker_node(stage)
    reference = [r for r in _linker_references(linker) if r[1].endswith("Gold") or "Gold" in r[1]]
    text = open(reference[0][2], encoding="utf-8").read() if reference else ""
    check("shader: the first map turns it into a PBR material with a normal map", ui._shader_target is not None and ui._shader_target.get("pbr") and "bsm_gui_normal" in text, reference)
    spec = read_pbr_spec(text) if text else None
    check("shader: it keeps the values of the basic material (Gold is metal)", spec is not None and float(spec["values"].get("metalness", 0.0)) > 0.9, spec and spec["values"])
    height = os.path.join(tempfile.gettempdir(), "bsm_gui_height.png").replace("\\", "/")
    QtGui.QImage(8, 8, QtGui.QImage.Format_RGB32).save(height)
    ui._pbr_edits["height"].setText(height)
    ui._pbr_map_edited("height")
    reference = [r for r in _linker_references(linker) if "Gold" in r[1]]
    text = open(reference[0][2], encoding="utf-8").read() if reference else ""
    check("shader: a displacement map goes with it", "bsm_gui_height" in text and "displacement" in text.lower(), reference)


# ------------------------------------------------------------------------
# Open Network goes inside the MaterialX network of the material being edited
def step_network():
    ui = S["ui"]
    editors = [p for p in hou.ui.paneTabs() if p.type() == hou.paneTabType.NetworkEditor]
    say("network editors:", [(e.name(), e.pwd().path()) for e in editors])
    ui.on_shader_open_network()
    editors = [p for p in hou.ui.paneTabs() if p.type() == hou.paneTabType.NetworkEditor]
    pwds = [e.pwd().path() for e in editors]
    say("network editors after:", pwds)
    edit = hou.node("/stage/material_edit")
    check("network: the Edit Material node holds the material", edit is not None and len(edit.children()) == 1, edit and [c.name() for c in edit.children()])
    inside = edit.children()[0].path() if edit is not None and edit.children() else ""
    check("network: a network editor is inside the material (its MaterialX nodes)", any(p == inside for p in pwds), (pwds, inside))


# ------------------------------------------------------------------------
def step_quit():
    say("FAILURES:", failures if failures else "none")
    say("DONE")
    hou.exit(suppress_save_prompt=True)


ALL = {
    "wait": (4000, lambda: say("waited")),
    "gallery": (1500, step_gallery), "gallery_close": (1500, step_gallery_close), "dlgclose": (1500, step_dlgclose),
    "setup": (2500, step_setup), "layout": (800, step_layout), "preview": (800, step_preview), "hdri": (800, step_hdri_preview), "cameras": (800, step_cameras), "panels": (800, step_panels),
    "live": (800, step_live), "nightsky": (800, step_nightsky), "small": (800, step_small), "shader": (800, step_shader), "network": (800, step_network), "catalog": (800, step_catalog_and_clear), "escape": (500, step_escape), "after": (1200, step_after_escape),
    "cycles": (500, step_cycles), "hda": (500, step_hda), "quit": (500, step_quit),
}
ORDER = os.environ.get("BSM_STEPS", "setup,layout,preview,hdri,cameras,panels,live,nightsky,small,shader,network,catalog,escape,after,cycles,hda,quit").split(",")
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
