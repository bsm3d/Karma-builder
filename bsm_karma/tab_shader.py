# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Shader tab: basic materials and a simple editor for the material of a prim
# Houdini : 21 and 22
# Version : 1.0.0

import hou
import os
from hutil.Qt import QtWidgets, QtCore, QtGui
from .basicmaterials import BASIC_MATERIALS, INPUT_DEFAULTS, basic_material_file, data_folder, safe_name
from .debuglog import _debug, _guarded_slot
from .gauges import FloatSlider, IntSlider
from .linker import _linker_references, _linker_rules, _material_linker_node
from .localmaterials import local_payload
from .pbrmaterial import (DEFAULT_OPTIONS as PBR_OPTIONS, DISP_SCALE_DEFAULT, IMAGE_SUFFIXES, NORMAL_FORMATS, SLOTS as PBR_SLOTS, default_spec,
                          guess_maps, normalize_spec, read_pbr_spec, write_pbr_file)
from .randommaterials import DEFAULT_RANGES, KINDS, MAX_PER_DROP, random_color, random_material_file
from .mtlxedit import DEFAULT_MODS, MtlxError, _prune, describe, original_and_settings, read_text, write_named, write_variant
from .util import _expand_plain_path
from .styles import _C
from .widgets import LOCAL_MATERIAL_MIME, ColorButton, FlowLayout, _drop_event_pos, linear_to_display, wrap_tab
import random

EDIT_DELAY_MS = 250
MY_MATERIALS_SHOWN = 24

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
TEXTURE_CONTROLS = (("tint", "color", "Tint", 0, 1), ("brightness", "float", "Brightness", 0, 3), ("rough_scale", "float", "Roughness x", 0, 3),
                    ("normal", "float", "Normal Strength", 0, 3), ("disp", "float", "Displacement", 0, 3), ("tiling", "float", "Tiling", 0.1, 10))


# ------------------------------------------------------------
class LibraryButton(QtWidgets.QToolButton):
    dragStarted = QtCore.Signal()
    activated = QtCore.Signal(str)

    # ------------------------------------------------------------
    def __init__(self, label, color, path_provider, parent=None):
        super().__init__(parent)
        self._path_provider = path_provider
        self._press = None
        self.setText(label)
        if color is not None:
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
def rainbow_pixmap(size=44):
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    gradient = QtGui.QConicalGradient(size / 2.0, size / 2.0, 0)
    for step in range(7):
        gradient.setColorAt(step / 6.0, QtGui.QColor.fromHsv(int(360 * step / 6.0) % 360, 190, 235))
    painter.setBrush(gradient)
    painter.setPen(QtGui.QPen(QtGui.QColor("#2a2a2a"), 1))
    painter.drawEllipse(2, 2, size - 4, size - 4)
    shade = QtGui.QRadialGradient(size * 0.38, size * 0.32, size * 0.62)
    shade.setColorAt(0.0, QtGui.QColor(255, 255, 255, 110))
    shade.setColorAt(1.0, QtGui.QColor(0, 0, 0, 90))
    painter.setBrush(shade)
    painter.setPen(QtCore.Qt.NoPen)
    painter.drawEllipse(2, 2, size - 4, size - 4)
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
PBR_DRIVEN = {"base_color": "base_color", "specular_roughness": "roughness", "metalness": "metalness", "emission_color": "emission", "opacity": "opacity"}


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
        button = LibraryButton("PBR", (0.8, 0.8, 0.8), self._pbr_base_file)
        button.setToolTip("The general purpose material, a Principled-like MaterialX material with texture slots. Click to assign it, "
                          "then load a texture set in the PBR Texture Set group.")
        self._connect_library_button(button)
        self._shader_grid.addWidget(button)
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

        layout.addWidget(self._build_random_group())
        self.grp_pbr = self._build_pbr_group()
        layout.addWidget(self.grp_pbr)
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
    def _build_random_group(self):
        group = QtWidgets.QGroupBox("Random Material")
        layout = QtWidgets.QVBoxLayout(group)
        hint = QtWidgets.QLabel("A new color and finish from the ranges below. Click or drag the ball; with several prims selected each one gets its own.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: {};".format(_C["text_muted"]))
        layout.addWidget(hint)
        top = QtWidgets.QHBoxLayout()
        self.btn_random = LibraryButton("Random", None, self._next_random_file)
        self.btn_random.setIcon(QtGui.QIcon(rainbow_pixmap()))
        self.btn_random.setToolTip("Click: a random material for each selected prim. Drag: onto a prim or the viewport.")
        self._connect_library_button(self.btn_random)
        top.addWidget(self.btn_random)
        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(14)
        self.combo_random_kind = QtWidgets.QComboBox()
        self.combo_random_kind.addItems(KINDS)
        self.combo_random_kind.setToolTip("Any draws the finish too: plastic, matte, metal or paint.")
        form.addRow("Kind:", self.combo_random_kind)
        self.sld_random_seed = IntSlider(0, 9999, 1)
        self.sld_random_seed.setToolTip("The same seed and ranges give the same colors again. Each use moves it on.")
        form.addRow("Seed:", self.sld_random_seed)
        top.addLayout(form, 1)
        layout.addLayout(top)
        form_ranges = QtWidgets.QFormLayout()
        form_ranges.setHorizontalSpacing(14)
        self._random_sliders = {}
        for key, label, low, high in (("hue_from", "Hue From:", 0.0, 360.0), ("hue_to", "Hue To:", 0.0, 360.0), ("sat_min", "Saturation Min:", 0.0, 1.0),
                                      ("sat_max", "Saturation Max:", 0.0, 1.0), ("val_min", "Brightness Min:", 0.0, 1.0), ("val_max", "Brightness Max:", 0.0, 1.0)):
            slider = FloatSlider(low, high, DEFAULT_RANGES[key], decimals=0 if high == 360.0 else 2)
            slider.setToolTip("Hue in degrees, 0 red, 120 green, 240 blue. From 300 to 60 goes through red. 0 to 360 is every color." if high == 360.0
                              else "As a screen shows it.")
            self._random_sliders[key] = slider
            form_ranges.addRow(label, slider)
        layout.addLayout(form_ranges)
        row = QtWidgets.QHBoxLayout()
        btn_assign = QtWidgets.QPushButton("Assign to Selection")
        btn_assign.setToolTip("A random material for each prim selected in the Materials tab list or in the viewport.")
        btn_assign.clicked.connect(self.on_random_assign)
        self.btn_random_edit = QtWidgets.QPushButton("Randomize Material Being Edited")
        self.btn_random_edit.setToolTip("A new random color for the material of the Material group (a texture is tinted).")
        self.btn_random_edit.clicked.connect(self.on_random_edit)
        row.addWidget(btn_assign)
        row.addWidget(self.btn_random_edit)
        layout.addLayout(row)
        return group

    # ------------------------------------------------------------
    def _pbr_base_file(self):
        return write_pbr_file(default_spec("PBR"), data_folder("materials_basic"), base=True)

    # ------------------------------------------------------------
    def _build_pbr_group(self):
        group = QtWidgets.QGroupBox("PBR Texture Set")
        layout = QtWidgets.QVBoxLayout(group)
        row = QtWidgets.QHBoxLayout()
        btn_load = QtWidgets.QPushButton("Load Texture Set...")
        btn_load.setToolTip("Pick the folder of a texture set: the maps are found by their names (color, albedo, roughness, normal, ao, height...).")
        btn_load.clicked.connect(self.on_pbr_load_set)
        btn_clear = QtWidgets.QPushButton("Clear Maps")
        btn_clear.clicked.connect(self.on_pbr_clear_maps)
        row.addWidget(btn_load)
        row.addWidget(btn_clear)
        layout.addLayout(row)
        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(14)
        self._pbr_edits = {}
        for slot, label, _kind in PBR_SLOTS:
            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText("none")
            edit.editingFinished.connect(lambda s=slot: self._pbr_map_edited(s))
            browse = QtWidgets.QPushButton("...")
            browse.setMaximumWidth(32)
            browse.clicked.connect(lambda _checked=False, s=slot: self._pbr_browse(s))
            line = QtWidgets.QHBoxLayout()
            line.addWidget(edit, 1)
            line.addWidget(browse)
            self._pbr_edits[slot] = edit
            form.addRow(label + ":", line)
        self.combo_pbr_normal = QtWidgets.QComboBox()
        self.combo_pbr_normal.addItems(["OpenGL (Y up)", "DirectX (Y down)"])
        self.combo_pbr_normal.setToolTip("How the normal map was made. Blender, Houdini and ambientCG (NormalGL) are OpenGL; 3ds Max and Unreal are DirectX.")
        self.combo_pbr_normal.currentIndexChanged.connect(self._pbr_option_edited)
        form.addRow("Normal Format:", self.combo_pbr_normal)
        self.chk_pbr_gloss = QtWidgets.QCheckBox("The roughness map is a glossiness map")
        self.chk_pbr_gloss.toggled.connect(self._pbr_option_edited)
        form.addRow("", self.chk_pbr_gloss)
        self.sld_pbr_ao = FloatSlider(0.0, 1.0, PBR_OPTIONS["ao_strength"])
        self.sld_pbr_ao.setToolTip("How much the ambient occlusion map darkens the base color.")
        self.sld_pbr_ao.valueChanged.connect(self._pbr_option_edited)
        form.addRow("AO Strength:", self.sld_pbr_ao)
        self.sld_pbr_off_x = FloatSlider(-1.0, 1.0, 0.0)
        self.sld_pbr_off_x.valueChanged.connect(self._pbr_option_edited)
        form.addRow("Offset U:", self.sld_pbr_off_x)
        self.sld_pbr_off_y = FloatSlider(-1.0, 1.0, 0.0)
        self.sld_pbr_off_y.valueChanged.connect(self._pbr_option_edited)
        form.addRow("Offset V:", self.sld_pbr_off_y)
        self.sld_pbr_rot = FloatSlider(-180.0, 180.0, 0.0, decimals=0)
        self.sld_pbr_rot.setToolTip("Rotation of the textures, in degrees.")
        self.sld_pbr_rot.valueChanged.connect(self._pbr_option_edited)
        form.addRow("Rotation:", self.sld_pbr_rot)
        layout.addLayout(form)
        note = QtWidgets.QLabel("Tint, brightness, roughness, normal strength, displacement and tiling are in the Textures group below.")
        note.setWordWrap(True)
        note.setStyleSheet("color: {};".format(_C["text_muted"]))
        layout.addWidget(note)
        group.setVisible(False)
        self._pbr_state = {"name": "PBR", "maps": {}, "options": {}}
        return group

    # ------------------------------------------------------------
    def _set_pbr_widgets(self, state):
        self._shader_loading = True
        try:
            for slot, edit in self._pbr_edits.items():
                edit.setText(state["maps"].get(slot, ""))
            options = state["options"]
            self.combo_pbr_normal.setCurrentIndex(1 if options.get("normal_format") == "DirectX" else 0)
            self.chk_pbr_gloss.setChecked(bool(options.get("gloss")))
            self.sld_pbr_ao.setValue(float(options.get("ao_strength", 1.0)))
            offset = options.get("offset", (0.0, 0.0))
            self.sld_pbr_off_x.setValue(float(offset[0]))
            self.sld_pbr_off_y.setValue(float(offset[1]))
            self.sld_pbr_rot.setValue(float(options.get("rotation", 0.0)))
        finally:
            self._shader_loading = False

    # ------------------------------------------------------------
    @_guarded_slot
    def _pbr_option_edited(self, *_):
        if self._shader_loading or self._shader_target is None or not self._shader_target.get("pbr"):
            return
        options = self._pbr_state["options"]
        options["normal_format"] = NORMAL_FORMATS[1 if self.combo_pbr_normal.currentIndex() == 1 else 0]
        options["gloss"] = self.chk_pbr_gloss.isChecked()
        options["ao_strength"] = float(self.sld_pbr_ao.value())
        options["offset"] = (float(self.sld_pbr_off_x.value()), float(self.sld_pbr_off_y.value()))
        options["rotation"] = float(self.sld_pbr_rot.value())
        self._shader_timer.start()

    # ------------------------------------------------------------
    @_guarded_slot
    def _pbr_map_edited(self, slot):
        if self._shader_loading or self._shader_target is None or not self._shader_target.get("pbr"):
            return
        text = self._pbr_edits[slot].text().strip()
        if text == self._pbr_state["maps"].get(slot, ""):
            return   # editingFinished also fires when the field only lost the focus
        if text:
            try:
                text = _expand_plain_path(text).replace("\\", "/")
            except ValueError as exc:
                self.log_message("[WARN] Texture not taken: {}".format(exc))
                self._pbr_edits[slot].setText(self._pbr_state["maps"].get(slot, ""))
                return
            checked = normalize_spec({"maps": {slot: text}})["maps"]
            if slot not in checked:
                self.log_message("[WARN] {}: not a map the editor takes (a full path to {}).".format(text, ", ".join(IMAGE_SUFFIXES)))
                self._pbr_edits[slot].setText(self._pbr_state["maps"].get(slot, ""))
                return
            self._pbr_state["maps"][slot] = checked[slot]
        else:
            self._pbr_state["maps"].pop(slot, None)
        self._after_pbr_maps_changed()

    # ------------------------------------------------------------
    @_guarded_slot
    def _pbr_browse(self, slot):
        path = hou.ui.selectFile(start_directory=self._pbr_edits[slot].text() or "$HIP", title="Texture", file_type=hou.fileType.Image,
                                 pattern=" ".join("*" + s for s in IMAGE_SUFFIXES), chooser_mode=hou.fileChooserMode.Read)
        if path:
            try:
                self._pbr_edits[slot].setText(_expand_plain_path(path))
            except ValueError as exc:
                self.log_message("[WARN] Texture not taken: {}".format(exc))
                return
            self._pbr_map_edited(slot)

    # ------------------------------------------------------------
    @_guarded_slot
    def on_pbr_load_set(self, *_):
        if self._shader_target is None or not self._shader_target.get("pbr"):
            return
        folder = hou.ui.selectFile(start_directory="$HIP", title="Texture Set Folder", file_type=hou.fileType.Directory,
                                   chooser_mode=hou.fileChooserMode.Read)
        if not folder:
            return
        try:
            folder = _expand_plain_path(folder).rstrip("/\\")
        except ValueError as exc:
            self.log_message("[WARN] Folder not taken: {}".format(exc))
            return
        found = normalize_spec({"maps": guess_maps(folder)})["maps"]
        if not found:
            self.log_message("[INFO] No texture found in {} (png, jpg, tif, exr, tga).".format(folder))
            return
        self._pbr_state["maps"] = dict(found)
        self._set_pbr_widgets(self._pbr_state)
        self.log_message("[OK] {} map(s) found: {}.".format(len(found), ", ".join(sorted(found))))
        self._after_pbr_maps_changed()

    # ------------------------------------------------------------
    @_guarded_slot
    def on_pbr_clear_maps(self, *_):
        if self._shader_target is None or not self._shader_target.get("pbr"):
            return
        self._pbr_state["maps"] = {}
        self._set_pbr_widgets(self._pbr_state)
        self._after_pbr_maps_changed()

    # ------------------------------------------------------------
    def _after_pbr_maps_changed(self):
        self._shader_timer.stop()
        self.apply_shader_edit()
        self._reload_current_shader()

    # ------------------------------------------------------------
    def _reload_current_shader(self):
        self._shader_timer.stop()
        self._fill_shader_materials()

    # ------------------------------------------------------------
    def _compose_pbr_spec(self):
        settings, state = self._shader_settings, self._pbr_state
        mods = dict(DEFAULT_MODS)
        mods.update(settings["mods"])
        options = dict(state["options"])
        options.update({"tint": tuple(mods["tint"]), "brightness": float(mods["brightness"]), "rough_scale": float(mods["rough_scale"]),
                        "normal_strength": float(mods["normal"]), "disp_scale": DISP_SCALE_DEFAULT * float(mods["disp"]), "tiling": float(mods["tiling"])})
        return {"name": state["name"], "values": dict(settings["values"]), "maps": dict(state["maps"]), "options": options}

    # ------------------------------------------------------------
    def _random_ranges(self):
        return {key: float(slider.value()) for key, slider in self._random_sliders.items()}

    # ------------------------------------------------------------
    def _next_random_file(self):
        seed = int(self.sld_random_seed.value())
        path = random_material_file(seed, self.combo_random_kind.currentText(), self._random_ranges())
        self.sld_random_seed.setValue(seed + 1)
        return path

    # ------------------------------------------------------------
    @_guarded_slot
    def on_random_assign(self, *_):
        paths, origin = self._assignment_targets()
        if not paths:
            self.log_message("[INFO] Select prims in the Materials tab list, or in the Solaris viewport, then use Random.")
            return
        if len(paths) > MAX_PER_DROP:
            self.log_message("[INFO] {} prims selected: the first {} get a random material.".format(len(paths), MAX_PER_DROP))
            paths = paths[:MAX_PER_DROP]
        seed, kind, ranges = int(self.sld_random_seed.value()), self.combo_random_kind.currentText(), self._random_ranges()
        pairs = []
        for number, prim in enumerate(paths):
            try:
                path = random_material_file(seed + number, kind, ranges)
            except OSError as exc:
                self.log_message("[WARN] Random material not written: {}".format(exc))
                return
            assets = self._local_assets_from_payload(local_payload([path]))
            if assets:
                pairs.append((assets[0], [prim]))
        self.sld_random_seed.setValue(seed + len(paths))
        self.log_message("[INFO] Random {}: {} prim(s) of {}.".format(kind, len(pairs), origin))
        self._assign_material_pairs(pairs)
        self._fill_shader_materials()

    # ------------------------------------------------------------
    @_guarded_slot
    def on_random_edit(self, *_):
        target = self._shader_target
        if target is None:
            self.log_message("[INFO] Assign a material first, then pick it in the Material group.")
            return
        seed = int(self.sld_random_seed.value())
        ranges = self._random_ranges()
        rng = random.Random("edit|{}|{}".format(seed, sorted(ranges.items())))
        self.sld_random_seed.setValue(seed + 1)
        if target.get("pbr"):
            textured = "base_color" in self._pbr_state["maps"]
        else:
            textured = target["info"]["inputs"]["base_color"]["kind"] == "connected" and "base_color" not in self._shader_settings["values"]
        if textured:
            soft = dict(ranges, sat_min=min(ranges["sat_min"], 0.6), sat_max=min(ranges["sat_max"], 0.6), val_min=1.0, val_max=1.0)
            self._shader_settings["mods"]["tint"] = random_color(rng, soft)
        else:
            self._shader_settings["values"]["base_color"] = random_color(rng, ranges)
        self._load_shader_controls()
        self.apply_shader_edit()

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
            self._sync_pbr_group()
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
        file_path = self._current_file_path(index, prim, file_path)
        spec = None
        try:
            spec = read_pbr_spec(read_text(file_path))
        except (OSError, UnicodeDecodeError):
            pass
        if spec is not None:
            original, saved = file_path, {}
        else:
            original, saved = original_and_settings(file_path)
        try:
            info = describe(read_text(original))
        except (OSError, MtlxError, UnicodeDecodeError) as exc:
            self._shader_target = None
            self._shader_enable(False)
            self._sync_pbr_group()
            self.lbl_shader_status.setText("This material cannot be edited here ({}). Use Open Network.".format(exc))
            return
        self._shader_target = {"index": index, "prim": prim, "original": original, "info": info, "pbr": spec is not None}
        # a file keeps its tuples as lists
        tupled = lambda items: {k: tuple(v) if isinstance(v, list) else v for k, v in items.items()}
        if spec is not None:
            self._adopt_pbr_spec(spec, info)
        else:
            self._shader_settings = {"values": tupled(saved.get("values", {})), "mods": tupled(saved.get("mods", {}))}
        self._shader_enable(True)
        self._sync_pbr_group()
        self._load_shader_controls()
        self.lbl_shader_status.setText("{} is assigned to {}. {}".format(info["material"] or prim.rsplit("/", 1)[-1], prim,
                                       "A copy is saved next to the file at every change; the original is never modified."))

    # ------------------------------------------------------------
    # The file the Material Linker has now for that slot: an edit made since the list was filled changed it.
    def _current_file_path(self, index, prim, fallback):
        stage = hou.node("/stage")
        linker = _material_linker_node(stage) if stage is not None else None
        if linker is not None:
            for slot, linked_prim, file_path, _ in _linker_references(linker):
                if slot == index and linked_prim == prim:
                    return file_path
        return fallback

    # ------------------------------------------------------------
    def _sync_pbr_group(self):
        self.grp_pbr.setVisible(self._shader_target is not None and bool(self._shader_target.get("pbr")))

    # ------------------------------------------------------------
    # The settings of the editor and the texture set from the spec in a PBR file. The controls show the constants of the
    # spec, not the file's (tint and brightness are already in those).
    def _adopt_pbr_spec(self, spec, info):
        options = spec["options"]
        self._pbr_state = {"name": spec["name"], "maps": dict(spec["maps"]), "options": {k: options[k] for k in
                           ("normal_format", "gloss", "ao_strength", "offset", "rotation", "disp_mid")}}
        mods = {"tint": tuple(options["tint"]), "brightness": options["brightness"], "rough_scale": options["rough_scale"],
                "normal": options["normal_strength"], "disp": options["disp_scale"] / DISP_SCALE_DEFAULT, "tiling": options["tiling"]}
        self._shader_settings = {"values": dict(spec["values"]), "mods": mods}
        for key, entry in info["inputs"].items():
            if entry["kind"] != "connected":
                entry["value"] = spec["values"].get(key, INPUT_DEFAULTS[key])
        self._set_pbr_widgets(self._pbr_state)

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
                if target.get("pbr"):
                    driven = PBR_DRIVEN.get(key) in self._pbr_state["maps"]
                    tip = "A map drives this input: clear it in the PBR Texture Set group to use a value."
                else:
                    driven = entry["kind"] == "connected" and key not in settings["values"]
                    tip = "A texture drives this input: use the Textures group below, or change the value to replace the texture."
                widget.setEnabled(not driven)
                widget.setToolTip(tip if driven else "")
                self._set_widget(widget, value)
            for weight_key, group in self._shader_groups.items():
                value = settings["values"].get(weight_key, info["inputs"][weight_key]["value"])
                group.blockSignals(True)
                group.setChecked(float(value) > 0.0)
                group.blockSignals(False)
            pbr = bool(target.get("pbr"))
            self.grp_shader_textures.setVisible(bool(info["textured"]) or pbr)
            maps = self._pbr_state["maps"] if pbr else {}
            for name, present in (("normal", info["has_normal"]), ("disp", info["has_displacement"]), ("tiling", info["has_tiling"])):
                self._shader_controls["mod:" + name].setEnabled(present)
            if pbr:
                # the tint, brightness and roughness scale also work on constants
                self._shader_controls["mod:tiling"].setEnabled(bool(maps))
                self._shader_controls["mod:normal"].setEnabled("normal" in maps)
                self._shader_controls["mod:disp"].setEnabled("height" in maps)
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
            if target.get("pbr"):
                spec = self._compose_pbr_spec()
                folder = os.path.dirname(target["original"])
                path = write_pbr_file(spec, folder)
                _prune(folder, spec["name"], keep=path)
            else:
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
        self._shader_remembered = {}
        if self._shader_target.get("pbr"):
            fresh = default_spec(self._pbr_state["name"])
            fresh["maps"] = dict(self._pbr_state["maps"])
            self._adopt_pbr_spec(fresh, self._shader_target["info"])
            self._load_shader_controls()
            self.apply_shader_edit()
            self._reload_current_shader()
            self.log_message("[OK] {}: values and options are back to the defaults, the maps are kept.".format(self._shader_target["prim"]))
            return
        self._shader_settings = {"values": {}, "mods": {}}
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
        pbr = bool(target.get("pbr"))
        folder = data_folder("my_materials") if pbr or not target["info"]["has_files"] else os.path.dirname(target["original"])
        wanted = "{}/{}.mtlx".format(folder, safe_name(name))
        if os.path.exists(wanted) and QtWidgets.QMessageBox.question(
                self, "Save as My Material", "{} exists. Replace it?".format(os.path.basename(wanted))) != QtWidgets.QMessageBox.Yes:
            return
        clean = {"values": self._shader_settings["values"], "mods": {k: v for k, v in self._shader_settings["mods"].items() if v != DEFAULT_MODS.get(k)}}
        try:
            if pbr:
                spec = self._compose_pbr_spec()
                spec["name"] = safe_name(name)
                path = write_pbr_file(spec, folder, base=True)
            else:
                path = write_named(target["original"], clean, name, folder)
        except (OSError, MtlxError, UnicodeDecodeError) as exc:
            self.log_message("[WARN] Material not saved: {}".format(exc))
            return
        self.log_message("[OK] Saved {}.".format(path))
        self._fill_my_materials()

    # ------------------------------------------------------------
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
