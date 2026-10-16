# tab_shader.py - BSM Karma Builder - Shader tab: basic materials and a simple editor for the material of a prim
# Version : 2026.10.15.1 | Revision : 16-10-2026 | Auteur : BSM

import hou
import os
from hutil.Qt import QtWidgets, QtCore, QtGui
from .basicmaterials import BASIC_MATERIALS, INPUT_DEFAULTS, basic_material_file, data_folder, safe_name
from .debuglog import _debug, _guarded_slot
from .gauges import FloatSlider
from .linker import _linker_references, _linker_rules
from .localmaterials import local_payload
from .mtlxedit import DEFAULT_MODS, MtlxError, describe, original_and_settings, read_text, write_named, write_variant
from .styles import _C
from .widgets import LOCAL_MATERIAL_MIME, ColorButton, FlowLayout, _drop_event_pos, linear_to_display, wrap_tab
from .linker import _material_linker_node

EDIT_DELAY_MS = 250
MY_MATERIALS_SHOWN = 24

# the controls of the editor, one group each: (input, kind, label, minimum, maximum)
GROUPS = (
    ("Base", None, (("base_color", "color", "Color", 0, 1), ("specular_roughness", "float", "Roughness", 0, 1), ("metalness", "float", "Metalness", 0, 1))),
    ("Subsurface (skin, wax, marble, leaves)", "subsurface", (("subsurface", "float", "Amount", 0, 1), ("subsurface_color", "color", "Color", 0, 1),
                                                                ("subsurface_radius", "color", "Radius (per channel)", 0, 1), ("subsurface_scale", "float", "Scale", 0, 5))),
    ("Specular / Coat", None, (("specular", "float", "Specular", 0, 1), ("specular_IOR", "float", "IOR", 1, 3), ("coat", "float", "Coat", 0, 1),
                               ("coat_roughness", "float", "Coat Roughness", 0, 1))),
    ("Transmission (glass, liquids)", "transmission", (("transmission", "float", "Amount", 0, 1), ("transmission_color", "color", "Tint", 0, 1),
                                                        ("transmission_depth", "float", "Absorption Depth", 0, 10), ("thin_walled", "bool", "Thin Walled", 0, 1))),
    ("Sheen (fabric)", "sheen", (("sheen", "float", "Amount", 0, 1), ("sheen_color", "color", "Color", 0, 1), ("sheen_roughness", "float", "Roughness", 0, 1))),
    ("Emission", "emission", (("emission", "float", "Strength", 0, 20), ("emission_color", "color", "Color", 0, 1))),
    ("Opacity", None, (("opacity", "grey", "Opacity", 0, 1),)),
)
# the multipliers for what is a texture: (setting, kind, label, minimum, maximum)
TEXTURE_CONTROLS = (("tint", "color", "Tint", 0, 1), ("brightness", "float", "Brightness", 0, 3), ("rough_scale", "float", "Roughness x", 0, 3),
                    ("normal", "float", "Normal Strength", 0, 3), ("disp", "float", "Displacement", 0, 3), ("tiling", "float", "Tiling", 0.1, 10))


# ------------------------------------------------------------
# A basic material of the library: a click assigns it, a drag carries its file to a prim or the viewport.
class LibraryButton(QtWidgets.QToolButton):
    dragStarted = QtCore.Signal()
    activated = QtCore.Signal(str)

    # ------------------------------------------------------------
    def __init__(self, label, color, path_provider, parent=None):
        super().__init__(parent)
        self._path_provider = path_provider
        self._press = None
        self.setText(label)
        self.setIcon(QtGui.QIcon(ball_pixmap(color)))
        self.setIconSize(QtCore.QSize(44, 44))
        self.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
        self.setAutoRaise(True)
        self.setFixedWidth(max(76, self.fontMetrics().horizontalAdvance(label) + 16))
        self.setToolTip("Click: assign to the selected prims. Drag: onto a prim of the list or an object of the viewport.")

    # ------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._press = _drop_event_pos(event)
        super().mousePressEvent(event)

    # ------------------------------------------------------------
    def mouseMoveEvent(self, event):
        if self._press is not None and event.buttons() & QtCore.Qt.LeftButton \
                and (_drop_event_pos(event) - self._press).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
            self._press = None
            self.setDown(False)
            self._drag()
            return
        super().mouseMoveEvent(event)

    # ------------------------------------------------------------
    def _drag(self):
        try:
            path = self._path_provider()
        except (OSError, KeyError) as exc:
            _debug("basic material not written: {}".format(exc))
            return
        data = QtCore.QMimeData()
        data.setData(LOCAL_MATERIAL_MIME, local_payload([path]).encode("utf-8"))
        drag = QtGui.QDrag(self)
        drag.setMimeData(data)
        drag.setPixmap(self.icon().pixmap(32, 32))
        self.dragStarted.emit()
        drag.exec_(QtCore.Qt.CopyAction) if hasattr(drag, "exec_") else drag.exec(QtCore.Qt.CopyAction)

    # ------------------------------------------------------------
    def mouseReleaseEvent(self, event):
        was_click = self._press is not None and event.button() == QtCore.Qt.LeftButton and self.rect().contains(_drop_event_pos(event))
        self._press = None
        super().mouseReleaseEvent(event)
        if was_click:
            try:
                self.activated.emit(self._path_provider())
            except (OSError, KeyError) as exc:
                _debug("basic material not written: {}".format(exc))


# ------------------------------------------------------------
# A ball for a button: the base color (a linear color) lit from the top left.
def ball_pixmap(rgb, size=44):
    color = QtGui.QColor(*[int(round(linear_to_display(c) * 255)) for c in rgb])
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    gradient = QtGui.QRadialGradient(size * 0.38, size * 0.32, size * 0.62)
    gradient.setColorAt(0.0, color.lighter(165))
    gradient.setColorAt(0.55, color)
    gradient.setColorAt(1.0, color.darker(190))
    painter.setBrush(gradient)
    painter.setPen(QtGui.QPen(QtGui.QColor("#2a2a2a"), 1))
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QColor(255, 255, 255, 120))
    painter.drawEllipse(int(size * 0.3), int(size * 0.22), int(size * 0.2), int(size * 0.12))
    painter.end()
    return pixmap


# ------------------------------------------------------------
def _preset_color(values):
    color = values.get("base_color", INPUT_DEFAULTS["base_color"])
    if values.get("transmission", 0.0) > 0.5:
        return (0.55, 0.72, 0.8)
    if values.get("emission", 0.0) > 0.0 and max(color) < 0.1:
        return values.get("emission_color", (1.0, 1.0, 1.0))
    return color


# ------------------------------------------------------------
class ShaderTab:

    # ------------------------------------------------------------
    def _build_shader_tab(self, tabs):
        self._shader_target = None
        self._shader_settings = {"values": {}, "mods": {}}
        self._shader_loading = False
        self._shader_controls = {}
        self._shader_groups = {}
        self._shader_remembered = {}

        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)

        group_pick = QtWidgets.QGroupBox("Material")
        form_pick = QtWidgets.QFormLayout(group_pick)
        self.combo_shader_material = QtWidgets.QComboBox()
        self.combo_shader_material.setToolTip("The materials that the Material Linker holds: assign one first (below, or in the Materials tab).")
        self.combo_shader_material.currentIndexChanged.connect(self.on_shader_pick)
        form_pick.addRow("Editing:", self.combo_shader_material)
        row_buttons = QtWidgets.QHBoxLayout()
        btn_from_prim = QtWidgets.QPushButton("From Prim Selection")
        btn_from_prim.setToolTip("Pick the material of the first prim selected in the Materials tab list or in the viewport.")
        btn_from_prim.clicked.connect(self.on_shader_from_prim)
        btn_network = QtWidgets.QPushButton("Open Network")
        btn_network.setToolTip("Show the Material Linker for the full MaterialX network.")
        btn_network.clicked.connect(self.on_open_material_linker)
        row_buttons.addWidget(btn_from_prim)
        row_buttons.addWidget(btn_network)
        form_pick.addRow("", row_buttons)
        self.lbl_shader_status = QtWidgets.QLabel("")
        self.lbl_shader_status.setWordWrap(True)
        self.lbl_shader_status.setTextFormat(QtCore.Qt.PlainText)
        self.lbl_shader_status.setStyleSheet("color: {};".format(_C["text_muted"]))
        form_pick.addRow(self.lbl_shader_status)
        layout.addWidget(group_pick)

        group_library = QtWidgets.QGroupBox("Basic Materials")
        lay_library = QtWidgets.QVBoxLayout(group_library)
        hint = QtWidgets.QLabel("Click to assign to the selected prims, or drag onto a prim of the list or an object of the viewport.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: {};".format(_C["text_muted"]))
        lay_library.addWidget(hint)
        self._shader_grid = FlowLayout()
        for name, values in BASIC_MATERIALS.items():
            button = LibraryButton(name, _preset_color(values), lambda n=name: basic_material_file(n))
            self._connect_library_button(button)
            self._shader_grid.addWidget(button)
        lay_library.addLayout(self._shader_grid)
        self.lbl_my_materials = QtWidgets.QLabel("My Materials")
        self.lbl_my_materials.setStyleSheet("font-weight: bold;")
        lay_library.addWidget(self.lbl_my_materials)
        self._my_grid = FlowLayout()
        lay_library.addLayout(self._my_grid)
        row_library = QtWidgets.QHBoxLayout()
        btn_folder = QtWidgets.QPushButton("My Materials Folder")
        btn_folder.clicked.connect(self.on_open_my_materials_folder)
        btn_refresh = QtWidgets.QPushButton("Refresh")
        btn_refresh.clicked.connect(self.refresh_shader_tab)
        row_library.addWidget(btn_folder)
        row_library.addWidget(btn_refresh)
        lay_library.addLayout(row_library)
        layout.addWidget(group_library)

        for title, weight, controls in GROUPS:
            layout.addWidget(self._build_shader_group(title, weight, controls))
        self.grp_shader_textures = self._build_shader_group("Textures of this material", None, TEXTURE_CONTROLS, mods=True)
        layout.addWidget(self.grp_shader_textures)
        layout.addStretch(1)

        row_end = QtWidgets.QHBoxLayout()
        self.btn_shader_reset = QtWidgets.QPushButton("Reset to Original")
        self.btn_shader_reset.setToolTip("Point the material back at its original file. The edited copies are kept next to it.")
        self.btn_shader_reset.clicked.connect(self.on_shader_reset)
        self.btn_shader_save = QtWidgets.QPushButton("Save as My Material...")
        self.btn_shader_save.setToolTip("Keep what you see as a material of its own, in My Materials (next to its textures when it has some).")
        self.btn_shader_save.clicked.connect(self.on_shader_save)
        row_end.addWidget(self.btn_shader_reset)
        row_end.addWidget(self.btn_shader_save)
        layout.addLayout(row_end)

        self._shader_timer = QtCore.QTimer(self)
        self._shader_timer.setSingleShot(True)
        self._shader_timer.setInterval(EDIT_DELAY_MS)
        self._shader_timer.timeout.connect(self.apply_shader_edit)

        self._shader_page = tab
        tabs.addTab(wrap_tab(tab), "Shader")
        tabs.currentChanged.connect(self._shader_tab_changed)
        self._shader_tabs = tabs
        self._shader_enable(False)

    # ------------------------------------------------------------
    def _connect_library_button(self, button):
        button.activated.connect(self.on_library_assign)
        button.dragStarted.connect(self._arm_viewport_drop)

    # ------------------------------------------------------------
    def _build_shader_group(self, title, weight_key, controls, mods=False):
        group = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(group)
        form.setHorizontalSpacing(14)
        if weight_key is not None:
            group.setCheckable(True)
            group.toggled.connect(lambda on, key=weight_key: self._shader_weight_toggled(key, on))
            self._shader_groups[weight_key] = group
        for key, kind, label, low, high in controls:
            if kind == "color":
                widget = ColorButton()
                widget.valueChanged.connect(lambda r, g, b, k=key, m=mods: self._shader_edited(k, (r, g, b), m))
            elif kind == "float":
                default = DEFAULT_MODS[key] if mods else INPUT_DEFAULTS.get(key, 0.0)
                widget = FloatSlider(low, high, default)
                widget.valueChanged.connect(lambda v, k=key, m=mods: self._shader_edited(k, float(v), m))
            elif kind == "grey":
                widget = FloatSlider(low, high, 1.0)
                widget.valueChanged.connect(lambda v, k=key: self._shader_edited(k, (float(v),) * 3, False))
            else:
                widget = QtWidgets.QCheckBox("Windows, soap bubbles")
                widget.toggled.connect(lambda on, k=key: self._shader_edited(k, bool(on), False))
            self._shader_controls[("mod:" if mods else "") + key] = widget
            form.addRow(label + ":", widget)
        return group

    # ------------------------------------------------------------
    def _shader_enable(self, enabled):
        for widget in self._shader_controls.values():
            widget.setEnabled(enabled)
        for group in self._shader_groups.values():
            group.setEnabled(enabled)
        self.btn_shader_reset.setEnabled(enabled)
        self.btn_shader_save.setEnabled(enabled)
        self.grp_shader_textures.setEnabled(enabled)

    # ------------------------------------------------------------
    def _shader_tab_changed(self, index):
        if self._shader_tabs.widget(index) is not None and self._shader_tabs.tabText(index) == "Shader":
            self.refresh_shader_tab()

    # ------------------------------------------------------------
    @_guarded_slot
    def refresh_shader_tab(self, *_):
        self._fill_my_materials()
        self._fill_shader_materials()

    # ------------------------------------------------------------
    def _fill_my_materials(self):
        while self._my_grid.count():
            item = self._my_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        try:
            folder = data_folder("my_materials")
            names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".mtlx"))[:MY_MATERIALS_SHOWN]
        except OSError:
            names = []
            folder = ""
        for name in names:
            path = "{}/{}".format(folder, name)
            color = (0.6, 0.6, 0.6)
            try:
                color = describe(read_text(path))["inputs"]["base_color"]["value"] or color
            except (OSError, MtlxError, UnicodeDecodeError):
                pass
            if not isinstance(color, tuple):
                color = (0.6, 0.6, 0.6)
            button = LibraryButton(os.path.splitext(name)[0], color, lambda p=path: p)
            self._connect_library_button(button)
            self._my_grid.addWidget(button)
        self.lbl_my_materials.setVisible(bool(names))

    # ------------------------------------------------------------
    @_guarded_slot
    def on_open_my_materials_folder(self):
        try:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(data_folder("my_materials")))
        except OSError as exc:
            self.log_message("[WARN] Folder not opened: {}".format(exc))

    # ------------------------------------------------------------
    # A basic or saved material, assigned to the prims selected in the list or in the viewport.
    @_guarded_slot
    def on_library_assign(self, path):
        paths, origin = self._assignment_targets()
        if not paths:
            self.log_message("[INFO] Select prims in the Materials tab list, or in the Solaris viewport, then click the material (or drag it onto a prim).")
            return
        self.log_message("[INFO] Assigning {} to {} prim(s) of {}.".format(os.path.splitext(os.path.basename(path))[0], len(paths), origin))
        self._assign_payload(local_payload([path]), paths)
        self._fill_shader_materials(select_file=path)

    # ------------------------------------------------------------
    def _source_label(self, path):
        folder = os.path.dirname(path).replace("\\", "/")
        try:
            if folder == data_folder("materials_basic"):
                return "basic"
            if folder == data_folder("my_materials"):
                return "my material"
        except OSError:
            pass
        return "file"

    # ------------------------------------------------------------
    # The materials of the Material Linker, one entry each.
    def _fill_shader_materials(self, select_file=None):
        stage = hou.node("/stage")
        linker = _material_linker_node(stage) if stage is not None else None
        references = _linker_references(linker) if linker is not None else []
        wanted = None
        if self._shader_target is not None:
            wanted = self._shader_target["prim"]
        self.combo_shader_material.blockSignals(True)
        self.combo_shader_material.clear()
        for index, prim, file_path, ref_prim in references:
            original, _ = original_and_settings(file_path)
            self.combo_shader_material.addItem("{}  ({})".format(prim.rsplit("/", 1)[-1], self._source_label(original)), (index, prim, file_path, ref_prim))
            if select_file is not None and os.path.normcase(original) == os.path.normcase(select_file) or (select_file is None and prim == wanted):
                self.combo_shader_material.setCurrentIndex(self.combo_shader_material.count() - 1)
        self.combo_shader_material.blockSignals(False)
        if not references:
            self._shader_target = None
            self._shader_enable(False)
            self.lbl_shader_status.setText("No material assigned yet. Click a basic material (with prims selected), or drag one onto a prim.")
            return
        self.on_shader_pick(self.combo_shader_material.currentIndex())

    # ------------------------------------------------------------
    # An edit that is still waiting for its pause is applied before anything else changes: to the material it was made on.
    def _flush_shader_edit(self):
        if self._shader_timer.isActive():
            self._shader_timer.stop()
            self.apply_shader_edit()

    # ------------------------------------------------------------
    @_guarded_slot
    def on_shader_pick(self, *_):
        data = self.combo_shader_material.currentData()
        self._flush_shader_edit()
        if data is None:
            self._shader_target = None
            self._shader_enable(False)
            return
        index, prim, file_path, ref_prim = data
        original, saved = original_and_settings(file_path)
        try:
            info = describe(read_text(original))
        except (OSError, MtlxError, UnicodeDecodeError) as exc:
            self._shader_target = None
            self._shader_enable(False)
            self.lbl_shader_status.setText("This material cannot be edited here ({}). Use Open Network.".format(exc))
            return
        self._shader_target = {"index": index, "prim": prim, "original": original, "info": info}
        # a file keeps its tuples as lists
        tupled = lambda items: {k: tuple(v) if isinstance(v, list) else v for k, v in items.items()}
        self._shader_settings = {"values": tupled(saved.get("values", {})), "mods": tupled(saved.get("mods", {}))}
        self._shader_enable(True)
        self._load_shader_controls()
        self.lbl_shader_status.setText("{} is assigned to {}. {}".format(info["material"] or prim.rsplit("/", 1)[-1], prim,
                                       "A copy is saved next to the file at every change; the original is never modified."))

    # ------------------------------------------------------------
    def _load_shader_controls(self):
        target = self._shader_target
        info, settings = target["info"], self._shader_settings
        self._shader_loading = True
        try:
            for key, widget in self._shader_controls.items():
                if key.startswith("mod:"):
                    name = key[4:]
                    value = settings["mods"].get(name, DEFAULT_MODS[name])
                    widget.setEnabled(True)
                    self._set_widget(widget, value)
                    continue
                entry = info["inputs"][key]
                value = settings["values"].get(key, entry["value"])
                driven = entry["kind"] == "connected" and key not in settings["values"]
                widget.setEnabled(not driven)
                widget.setToolTip("A texture drives this input: use the Textures group below, or change the value to replace the texture." if driven else "")
                self._set_widget(widget, value)
            for weight_key, group in self._shader_groups.items():
                value = settings["values"].get(weight_key, info["inputs"][weight_key]["value"])
                group.blockSignals(True)
                group.setChecked(float(value) > 0.0)
                group.blockSignals(False)
            self.grp_shader_textures.setVisible(bool(info["textured"]))
            for name, present in (("normal", info["has_normal"]), ("disp", info["has_displacement"]), ("tiling", info["has_tiling"])):
                self._shader_controls["mod:" + name].setEnabled(present)
        finally:
            self._shader_loading = False

    # ------------------------------------------------------------
    @staticmethod
    def _set_widget(widget, value):
        if isinstance(widget, ColorButton):
            widget.set_rgb(*value)
        elif isinstance(widget, FloatSlider):
            widget.setValue(float(value[0] if isinstance(value, (tuple, list)) else value))
        elif isinstance(widget, QtWidgets.QCheckBox):
            widget.setChecked(bool(value))

    # ------------------------------------------------------------
    def _shader_edited(self, key, value, mods):
        if self._shader_loading or self._shader_target is None:
            return
        (self._shader_settings["mods"] if mods else self._shader_settings["values"])[key] = value
        if not mods and key in self._shader_groups:
            self._shader_remembered[key] = value
        self._shader_timer.start()

    # ------------------------------------------------------------
    def _shader_weight_toggled(self, key, on):
        if self._shader_loading or self._shader_target is None:
            return
        widget = self._shader_controls[key]
        if on:
            value = self._shader_remembered.get(key) or float(widget.value()) or 1.0
            self._shader_loading = True
            widget.setValue(value)
            self._shader_loading = False
        else:
            self._shader_remembered[key] = float(widget.value()) or self._shader_remembered.get(key, 1.0)
            value = 0.0
        self._shader_settings["values"][key] = float(value)
        self._shader_timer.start()

    # ------------------------------------------------------------
    # The edited file replaces the original in the Material Linker; with nothing changed the original comes back.
    @_guarded_slot
    def apply_shader_edit(self):
        target = self._shader_target
        if target is None:
            return
        stage = hou.node("/stage")
        linker = _material_linker_node(stage) if stage is not None else None
        if linker is None:
            return
        slot = next((index for index, prim, _, _ in _linker_references(linker) if prim == target["prim"]), None)
        parm = linker.parm("filepath_{}".format(slot)) if slot is not None else None
        if parm is None:
            self.log_message("[WARN] The material {} is not in the Material Linker any more.".format(target["prim"]))
            return
        clean = {"values": self._shader_settings["values"], "mods": {k: v for k, v in self._shader_settings["mods"].items()
                                                                    if v != DEFAULT_MODS.get(k)}}
        try:
            path = write_variant(target["original"], clean) if (clean["values"] or clean["mods"]) else target["original"]
        except (OSError, MtlxError, UnicodeDecodeError) as exc:
            self.log_message("[WARN] Material not changed: {}".format(exc))
            return
        with hou.undos.group("BSM Karma - Edit Material"):
            parm.set(path)
        _debug("material editor: {} -> {}".format(target["prim"], path))

    # ------------------------------------------------------------
    @_guarded_slot
    def on_shader_reset(self):
        if self._shader_target is None:
            return
        self._shader_settings = {"values": {}, "mods": {}}
        self._shader_remembered = {}
        self._load_shader_controls()
        self.apply_shader_edit()
        self.log_message("[OK] {} is back to its original file.".format(self._shader_target["prim"]))

    # ------------------------------------------------------------
    @_guarded_slot
    def on_shader_save(self):
        target = self._shader_target
        if target is None:
            return
        name, accepted = QtWidgets.QInputDialog.getText(self, "Save as My Material", "Name of the material:",
                                                        text=safe_name(target["info"]["material"] or "My_Material"))
        if not accepted or not name.strip():
            return
        folder = os.path.dirname(target["original"]) if target["info"]["has_files"] else data_folder("my_materials")
        wanted = "{}/{}.mtlx".format(folder, safe_name(name))
        if os.path.exists(wanted) and QtWidgets.QMessageBox.question(
                self, "Save as My Material", "{} exists. Replace it?".format(os.path.basename(wanted))) != QtWidgets.QMessageBox.Yes:
            return
        clean = {"values": self._shader_settings["values"], "mods": {k: v for k, v in self._shader_settings["mods"].items() if v != DEFAULT_MODS.get(k)}}
        try:
            path = write_named(target["original"], clean, name, folder)
        except (OSError, MtlxError, UnicodeDecodeError) as exc:
            self.log_message("[WARN] Material not saved: {}".format(exc))
            return
        self.log_message("[OK] Saved {}.".format(path))
        self._fill_my_materials()

    # ------------------------------------------------------------
    # The material bound to the first selected prim.
    @_guarded_slot
    def on_shader_from_prim(self):
        paths, _origin = self._assignment_targets()
        stage = hou.node("/stage")
        linker = _material_linker_node(stage) if stage is not None else None
        if not paths or linker is None:
            self.log_message("[INFO] Select a prim that has a material, in the Materials tab list or in the viewport.")
            return
        for _index, material_path, includes in _linker_rules(linker):
            if paths[0] in includes:
                for row in range(self.combo_shader_material.count()):
                    if self.combo_shader_material.itemData(row)[1] == material_path:
                        self.combo_shader_material.setCurrentIndex(row)
                        return
        self.log_message("[INFO] {} has no material from the Material Linker.".format(paths[0]))
