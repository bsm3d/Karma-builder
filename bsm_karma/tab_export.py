# tab_export.py - BSM Karma Builder - Export tab: output, render buttons and viewport tools
# Version : 2026.10.15.1 | Revision : 15-10-2026 | Auteur : BSM

import hou
import os
from hutil.Qt import QtWidgets, QtCore
from .debuglog import _guarded_slot
from .gauges import ClickSlider
from .styles import _C, _btn_style, _slider_stylesheet
from .util import _normalize_output_path_extension
from .widgets import wrap_tab

# ------------------------------------------------------------
class ExportTab:

    def _build_export_tab(self, tabs):
        # Compact: related controls share a row so the tab stays narrow (about 340 px).
        tab_out = QtWidgets.QWidget()
        self.form_out = QtWidgets.QFormLayout(tab_out)
        self.form_out.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        # format and, for EXR, precision
        self.combo_output_format = QtWidgets.QComboBox()
        self.combo_output_format.addItems(["EXR", "PNG"])
        self.combo_output_format.currentIndexChanged.connect(self.update_output_format_ui)
        self.lbl_exr_precision = QtWidgets.QLabel("Precision")
        self.combo_exr_precision = QtWidgets.QComboBox()
        self.combo_exr_precision.addItems(["16-bit float", "32-bit float"])
        row_format = QtWidgets.QHBoxLayout()
        row_format.setContentsMargins(0, 0, 0, 0)
        row_format.addWidget(self.combo_output_format, 1)
        row_format.addWidget(self.lbl_exr_precision)
        row_format.addWidget(self.combo_exr_precision, 1)
        self.form_out.addRow("Format:", row_format)

        # single frame or range
        self.combo_trange = QtWidgets.QComboBox()
        self.combo_trange.addItems(["Single Frame", "Frame Range"])
        self.combo_trange.setCurrentText("Single Frame")
        self.combo_trange.currentIndexChanged.connect(self.toggle_frame_range)

        self.spin_fStart = QtWidgets.QSpinBox()
        self.spin_fStart.setRange(-1000, 10000)
        self.spin_fStart.setValue(1)
        self.spin_fStart.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.spin_fStart.setAlignment(QtCore.Qt.AlignCenter)
        self.spin_fStart.setFixedWidth(52)

        self.spin_fEnd = QtWidgets.QSpinBox()
        self.spin_fEnd.setRange(-1000, 10000)
        self.spin_fEnd.setValue(100)
        self.spin_fEnd.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.spin_fEnd.setAlignment(QtCore.Qt.AlignCenter)
        self.spin_fEnd.setFixedWidth(52)

        self.lbl_to = QtWidgets.QLabel("to")
        self.lbl_to.setAlignment(QtCore.Qt.AlignCenter)

        row_frames = QtWidgets.QHBoxLayout()
        row_frames.setContentsMargins(0, 0, 0, 0)
        row_frames.addWidget(self.combo_trange, 1)
        row_frames.addWidget(self.spin_fStart)
        row_frames.addWidget(self.lbl_to)
        row_frames.addWidget(self.spin_fEnd)
        self.form_out.addRow("Frames:", row_frames)

        layout_out = QtWidgets.QHBoxLayout()
        layout_out.setContentsMargins(0, 0, 0, 0)
        self.line_out = QtWidgets.QLineEdit("$HIP/render/beauty/frame_$F4.exr")
        self.line_out.setMinimumWidth(60)
        btn_browse_out = QtWidgets.QPushButton("...")
        btn_browse_out.setMaximumWidth(32)
        btn_browse_out.clicked.connect(self.browse_output)
        layout_out.addWidget(self.line_out)
        layout_out.addWidget(btn_browse_out)
        self.form_out.addRow("Output:", layout_out)

        # the four actions in a 2 x 2 grid
        self.btn_render_mplay = QtWidgets.QPushButton("Render to MPlay")
        self.btn_render_mplay.setStyleSheet(_btn_style(_C["amber"]))
        self.btn_render_mplay.clicked.connect(self.on_render_mplay)

        self.btn_render_disk = QtWidgets.QPushButton("Render to Disk")
        self.btn_render_disk.setStyleSheet(_btn_style(_C["amber"]))
        self.btn_render_disk.clicked.connect(self.on_render_disk)

        self.btn_open_karma_settings = QtWidgets.QPushButton("Karma Settings")
        self.btn_open_karma_settings.setStyleSheet(_btn_style(_C["amber"]))
        self.btn_open_karma_settings.clicked.connect(self.on_open_karma_settings)

        self.btn_open_viewport = QtWidgets.QPushButton("Karma Viewport")
        self.btn_open_viewport.setStyleSheet(_btn_style(_C["amber"]))
        self.btn_open_viewport.clicked.connect(self.on_open_viewport)

        grid_render = QtWidgets.QGridLayout()
        grid_render.setContentsMargins(0, 4, 0, 4)
        grid_render.addWidget(self.btn_render_mplay, 0, 0)
        grid_render.addWidget(self.btn_render_disk, 0, 1)
        grid_render.addWidget(self.btn_open_karma_settings, 1, 0)
        grid_render.addWidget(self.btn_open_viewport, 1, 1)
        self.form_out.addRow(grid_render)

        grp_viewport_tools = QtWidgets.QGroupBox("Viewport Tools")
        lay_viewport_tools = QtWidgets.QVBoxLayout(grp_viewport_tools)

        row_engine = QtWidgets.QHBoxLayout()
        row_engine.addWidget(QtWidgets.QLabel("Engine:"))
        self.combo_viewport_engine = QtWidgets.QComboBox()
        self.combo_viewport_engine.addItems(["xpu", "cpu"])
        self.combo_viewport_engine.setCurrentText(self.combo_engine.currentText())
        row_engine.addWidget(self.combo_viewport_engine, 1)
        self.btn_apply_viewport_engine = QtWidgets.QPushButton("Apply")
        self.btn_apply_viewport_engine.setToolTip("Switch the viewport and the build to this renderer.")
        self.btn_apply_viewport_engine.clicked.connect(self.on_apply_viewport_engine)
        row_engine.addWidget(self.btn_apply_viewport_engine)
        lay_viewport_tools.addLayout(row_engine)

        row_snapshot = QtWidgets.QHBoxLayout()
        self.btn_capture_snapshot = QtWidgets.QPushButton("Snapshot")
        self.btn_capture_snapshot.setToolTip("Capture the viewport into the target slot (A, then B).")
        self.btn_capture_snapshot.clicked.connect(self.on_capture_viewport_snapshot)
        self.btn_save_snapshot = QtWidgets.QPushButton("Save")
        self.btn_save_snapshot.setToolTip("Save the snapshot as a PNG or JPEG.")
        self.btn_save_snapshot.clicked.connect(self.on_save_viewport_snapshot)
        self.btn_save_snapshot.setEnabled(False)
        self.btn_clear_snapshot_slots = QtWidgets.QPushButton("Clear")
        self.btn_clear_snapshot_slots.setToolTip("Empty both snapshot slots.")
        self.btn_clear_snapshot_slots.clicked.connect(self.on_clear_snapshot_slots)
        row_snapshot.addWidget(self.btn_capture_snapshot)
        row_snapshot.addWidget(self.btn_save_snapshot)
        row_snapshot.addWidget(self.btn_clear_snapshot_slots)
        lay_viewport_tools.addLayout(row_snapshot)

        # the two slots on the left, the safe frame and compare options on their right
        self.btn_snapshot_slot_a = QtWidgets.QToolButton()
        self.btn_snapshot_slot_a.setCheckable(True)
        self.btn_snapshot_slot_a.clicked.connect(lambda *_: self._set_snapshot_slot_target("A"))
        self.btn_snapshot_slot_a.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
        self.btn_snapshot_slot_a.setFixedSize(96, 70)
        self.btn_snapshot_slot_a.setIconSize(QtCore.QSize(88, 46))

        self.btn_snapshot_slot_b = QtWidgets.QToolButton()
        self.btn_snapshot_slot_b.setCheckable(True)
        self.btn_snapshot_slot_b.clicked.connect(lambda *_: self._set_snapshot_slot_target("B"))
        self.btn_snapshot_slot_b.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
        self.btn_snapshot_slot_b.setFixedSize(96, 70)
        self.btn_snapshot_slot_b.setIconSize(QtCore.QSize(88, 46))

        self.chk_snapshot_safe = QtWidgets.QCheckBox("Safe Frame")
        self.chk_snapshot_safe.stateChanged.connect(lambda *_: self._update_snapshot_preview())
        self.combo_snapshot_safe_type = QtWidgets.QComboBox()
        self.combo_snapshot_safe_type.addItems(["Action Safe", "Text Safe", "Both"])
        self.combo_snapshot_safe_type.currentIndexChanged.connect(lambda *_: self._update_snapshot_preview())
        self.chk_snapshot_compare = QtWidgets.QCheckBox("Compare A/B")
        self.chk_snapshot_compare.setEnabled(False)
        self.chk_snapshot_compare.stateChanged.connect(lambda *_: self._update_snapshot_preview())

        col_options = QtWidgets.QVBoxLayout()
        col_options.setSpacing(2)
        col_options.addWidget(self.chk_snapshot_safe)
        col_options.addWidget(self.combo_snapshot_safe_type)
        col_options.addWidget(self.chk_snapshot_compare)

        row_slots = QtWidgets.QHBoxLayout()
        row_slots.addWidget(self.btn_snapshot_slot_a)
        row_slots.addWidget(self.btn_snapshot_slot_b)
        row_slots.addSpacing(6)
        row_slots.addLayout(col_options, 1)
        lay_viewport_tools.addLayout(row_slots)

        row_compare = QtWidgets.QHBoxLayout()
        row_compare.addWidget(QtWidgets.QLabel("A"))
        self.sld_snapshot_compare = ClickSlider(QtCore.Qt.Horizontal)
        self.sld_snapshot_compare.setRange(1, 99)
        self.sld_snapshot_compare.setValue(50)
        self.sld_snapshot_compare.setMinimumHeight(20)
        self.sld_snapshot_compare.setStyleSheet(_slider_stylesheet())
        self.sld_snapshot_compare.setEnabled(False)
        self.sld_snapshot_compare.valueChanged.connect(lambda *_: self._update_snapshot_preview())
        row_compare.addWidget(self.sld_snapshot_compare, 1)
        row_compare.addWidget(QtWidgets.QLabel("B"))
        lay_viewport_tools.addLayout(row_compare)

        self.w_snapshot_preview = QtWidgets.QWidget()
        self.w_snapshot_preview.setMinimumHeight(110)
        self.w_snapshot_preview.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        lay_snapshot_stack = QtWidgets.QVBoxLayout(self.w_snapshot_preview)
        lay_snapshot_stack.setContentsMargins(0, 0, 0, 0)

        self.lbl_snapshot_preview = QtWidgets.QLabel("No snapshot yet.")
        self.lbl_snapshot_preview.setMinimumHeight(110)
        self.lbl_snapshot_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_snapshot_preview.setScaledContents(False)
        self.lbl_snapshot_preview.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.lbl_snapshot_preview.setObjectName("snapshotPreview")
        lay_snapshot_stack.addWidget(self.lbl_snapshot_preview)
        lay_viewport_tools.addWidget(self.w_snapshot_preview)

        self.form_out.addRow(grp_viewport_tools)

        tabs.addTab(wrap_tab(tab_out), "Export")
        self._config_tabs.append(tab_out)

    # ------------------------------------------------------------
    def browse_output(self):
        pattern = "*.exr" if self.combo_output_format.currentText() == "EXR" else "*.png"
        path = hou.ui.selectFile(start_directory="$HIP", title="Output Path", pattern=pattern, chooser_mode=hou.fileChooserMode.Write)
        if path:
            self.line_out.setText(hou.text.expandString(path))
            self.sync_output_extension()
            self._schedule_live_update()

    # ------------------------------------------------------------
    def sync_output_extension(self):
        raw = self.line_out.text().strip()
        if not raw:
            return
        out_path = _normalize_output_path_extension(raw, self.combo_output_format.currentText())
        if out_path != raw:
            self.line_out.blockSignals(True)
            self.line_out.setText(out_path)
            self.line_out.blockSignals(False)

    # ----------------------------------------
    def update_output_format_ui(self):
        is_exr = (self.combo_output_format.currentText() == "EXR")
        self.lbl_exr_precision.setVisible(is_exr)
        self.combo_exr_precision.setVisible(is_exr)
        self.sync_output_extension()

    # --------------------------------------------------------
    def toggle_frame_range(self):
        is_range = (self.combo_trange.currentText() == "Frame Range")
        self.spin_fStart.setEnabled(is_range)
        self.spin_fEnd.setEnabled(is_range)
        self.lbl_to.setEnabled(is_range)

    # ------------------------------------
    @_guarded_slot
    def on_render_disk(self):
        if not self.on_build():
            return
        rp = hou.node("/stage/render_to_disk")
        if rp:
            out_dir = os.path.dirname(hou.text.expandString(self.line_out.text()))
            if out_dir: os.makedirs(out_dir, exist_ok=True)
            self.log_message("Launching Render to Disk...")
            rp.parm("execute").pressButton()

    # ------------------------------------------------------------
    @_guarded_slot
    def on_render_mplay(self):
        if not self.on_build():
            return
        rp = hou.node("/stage/render_to_disk")
        if rp:
            self.log_message("Launching Render to MPlay...")
            old_path = rp.parm("outputimage").unexpandedString()
            rp.parm("outputimage").set("ip")
            try:
                rp.parm("execute").pressButton()
            finally:
                rp.parm("outputimage").set(old_path)
