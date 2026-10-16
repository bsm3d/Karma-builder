# tab_scene.py - BSM Karma Builder - Scene tab: mode, quality, camera and the tool's own nodes
# Version : 1.0.0 | Revision : 15-10-2026 | Auteur : BSM

import hou
from hutil.Qt import QtWidgets, QtCore
from .config import CAMERA_CREATE_LABEL, TOOL_STAGE_DELETE_ORDER, TOOL_STAGE_NODE_TYPES, USD_CAMERA_PREFIX
from .debuglog import _guarded_slot
from .environment import _lop_camera_nodes, _stage_camera_prims
from .gauges import IntSlider
from .nodeutil import _is_tool_node_candidate, _paused_cooking
from .styles import _C, _btn_style
from .widgets import PopupRefreshComboBox, fit_button, fit_spin, wrap_tab

# ------------------------------------------------------------
class SceneTab:

    def _build_scene_tab(self, tabs):
        tab_main = QtWidgets.QWidget()
        form_main = self.form_main = QtWidgets.QFormLayout(tab_main)

        self.combo_scene_mode = QtWidgets.QComboBox()
        self.combo_scene_mode.addItems(["Environment", "Studio", "3 Points", "Interior"])
        self.combo_scene_mode.setCurrentText("Environment")
        self.combo_scene_mode.currentIndexChanged.connect(self.update_environment_tab)
        form_main.addRow("Scene Mode:", self.combo_scene_mode)

        self.combo_env_type = QtWidgets.QComboBox()
        self.combo_env_type.addItems(["Physical Sky", "HDRI Image"])
        self.combo_env_type.setCurrentText("Physical Sky")
        self.combo_env_type.currentIndexChanged.connect(self.update_environment_tab)
        form_main.addRow("Environment Type:", self.combo_env_type)

        self.combo_time_preset = QtWidgets.QComboBox()
        self.combo_time_preset.addItems(self._sky_preset_names)
        self.combo_time_preset.currentIndexChanged.connect(self.sync_from_main_tab)
        form_main.addRow("Sky Preset:", self.combo_time_preset)
        
        self.combo_preset = QtWidgets.QComboBox()
        self.combo_preset.addItems(list(self.presets.keys()))
        self.combo_preset.currentIndexChanged.connect(self.apply_preset)
        form_main.addRow("Quality Preset:", self.combo_preset)
        
        res_layout = QtWidgets.QHBoxLayout()
        res_layout.setContentsMargins(0, 0, 0, 0)
        self.spin_resX = QtWidgets.QSpinBox(); self.spin_resX.setRange(1, 8192)
        self.spin_resY = QtWidgets.QSpinBox(); self.spin_resY.setRange(1, 8192)
        self.spin_resX.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.spin_resY.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.spin_resX.setAlignment(QtCore.Qt.AlignCenter)
        self.spin_resY.setAlignment(QtCore.Qt.AlignCenter)
        fit_spin(self.spin_resX, "8192", 55)
        fit_spin(self.spin_resY, "8192", 55)
        res_layout.addWidget(self.spin_resX); res_layout.addWidget(QtWidgets.QLabel("x")); res_layout.addWidget(self.spin_resY); res_layout.addWidget(QtWidgets.QLabel("y")); res_layout.addStretch()
        form_main.addRow("Resolution:", res_layout)
        
        self.sld_samples = IntSlider(1, 4096, 256)
        form_main.addRow("Samples:", self.sld_samples)
        
        self.combo_engine = QtWidgets.QComboBox()
        self.combo_engine.addItems(["xpu", "cpu"])
        form_main.addRow("Engine:", self.combo_engine)

        self.w_camera_select = QtWidgets.QWidget()
        lay_camera_select = QtWidgets.QHBoxLayout(self.w_camera_select)
        lay_camera_select.setContentsMargins(0, 0, 0, 0)
        lay_camera_select.setSpacing(6)
        # rebuilt each time it opens, so new or deleted cameras show up
        self.combo_camera = PopupRefreshComboBox()
        self.combo_camera.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.combo_camera.setToolTip("Create New Camera, a camera LOP of /stage, or a camera prim of the Geometry Source.")
        self.combo_camera.popupAboutToShow.connect(self.refresh_stage_cameras)
        self.combo_camera.currentIndexChanged.connect(self.update_camera_ui)
        self.btn_refresh_cameras = QtWidgets.QPushButton("Refresh")
        fit_button(self.btn_refresh_cameras, 64)
        self.btn_refresh_cameras.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.btn_refresh_cameras.clicked.connect(self.refresh_stage_cameras)
        self.btn_look_through = QtWidgets.QPushButton("Look Through")
        fit_button(self.btn_look_through, 92)
        self.btn_look_through.setToolTip("Lock a viewport to the render camera (builds first if needed).")
        self.btn_look_through.clicked.connect(self.on_look_through_camera)
        lay_camera_select.addWidget(self.combo_camera)
        lay_camera_select.addWidget(self.btn_refresh_cameras)
        lay_camera_select.addWidget(self.btn_look_through)
        lay_camera_select.setStretch(0, 1)
        form_main.addRow("Camera:", self.w_camera_select)

        self.w_new_camera = QtWidgets.QWidget()
        lay_new_camera = QtWidgets.QHBoxLayout(self.w_new_camera)
        lay_new_camera.setContentsMargins(0, 0, 0, 0)
        lay_new_camera.setSpacing(6)
        self.spin_cam_focal = QtWidgets.QDoubleSpinBox()
        self.spin_cam_focal.setRange(5.0, 400.0)
        self.spin_cam_focal.setDecimals(1)
        self.spin_cam_focal.setSingleStep(1.0)
        self.spin_cam_focal.setValue(35.0)
        self.spin_cam_focal.setSuffix(" mm")
        self.chk_cam_from_viewport = QtWidgets.QCheckBox("Match viewport")
        self.chk_cam_from_viewport.setToolTip(
            "Copy the position and rotation of the active viewport onto the new camera at each build.\n"
            "Left off, the camera keeps the position it was given the first time.")
        lay_new_camera.addWidget(self.spin_cam_focal)
        lay_new_camera.addWidget(self.chk_cam_from_viewport)
        lay_new_camera.addStretch(1)
        form_main.addRow("New Camera:", self.w_new_camera)

        self.btn_clear_all_main = QtWidgets.QPushButton("Clear All Tool Nodes")
        self.btn_clear_all_main.setStyleSheet(_btn_style(_C["amber"]))
        self.btn_clear_all_main.clicked.connect(self.on_clear_all)
        form_main.addRow("", self.btn_clear_all_main)

        self.chk_live_update = QtWidgets.QCheckBox("Rebuild on change")
        self.chk_live_update.setToolTip(
            "On: a change of a value updates the nodes after a short pause, no need to press Build.\n"
            "A change that adds or removes nodes (scene mode, sky rendering, fog, clouds, AOVs, engine, camera,\n"
            "geometry source) waits for Build: it can freeze a running Karma viewport.\n"
            "Off: the network only changes when you press Build (better on a slower machine).")
        form_main.addRow("Live Update:", self.chk_live_update)

        tabs.addTab(wrap_tab(tab_main), "Scene")
        self._config_tabs.append(tab_main)

    # ----------------------------------------------------------------------
    def apply_preset(self):
        p = self.presets.get(self.combo_preset.currentText())
        if p:
            self.spin_resX.setValue(p["rx"])
            self.spin_resY.setValue(p["ry"])
            self.sld_samples.setValue(p["spl"])

    # ------------------------------------------------------------
    def _camera_choices(self):
        choices = [(self.CAMERA_CREATE_LABEL, CAMERA_CREATE_LABEL)]
        stage = hou.node("/stage")
        for node in sorted(_lop_camera_nodes(stage), key=lambda n: n.path()):
            choices.append((node.path(), node.path()))

        geo_path = self._current_geo_source()
        geo_node = hou.node(geo_path) if geo_path else None
        if geo_node is not None:
            try:
                for prim_path in _stage_camera_prims(geo_node.stage()):
                    choices.append(("USD: {}".format(prim_path), USD_CAMERA_PREFIX + prim_path))
            except hou.Error as exc:
                self.log_message("[WARN] Could not list the camera prims of {}: {}".format(geo_path, exc))
        return choices

    # --------------------------------------------------
    def _current_camera_choice(self):
        data = self.combo_camera.currentData()
        return data if data else CAMERA_CREATE_LABEL

    # --------------------------------------------------------------------------------
    @_guarded_slot
    def refresh_stage_cameras(self, *_):
        current = self._current_camera_choice() if self.combo_camera.count() else CAMERA_CREATE_LABEL
        self.combo_camera.blockSignals(True)
        self.combo_camera.clear()
        for label, choice in self._camera_choices():
            self.combo_camera.addItem(label, choice)
        index = self.combo_camera.findData(current)
        if index < 0 and current != CAMERA_CREATE_LABEL:
            self.log_message("[INFO] Camera {} no longer exists: back to a new camera.".format(current))
        self.combo_camera.setCurrentIndex(max(0, index))
        self.combo_camera.blockSignals(False)
        self.update_camera_ui()

    # --------------------------------------------------------
    def update_camera_ui(self, *_):
        creating = (self._current_camera_choice() == CAMERA_CREATE_LABEL)
        self.w_new_camera.setEnabled(creating)

    # ------------------------------------------------------------
    def _viewport_matrix(self):
        try:
            viewer = self._get_active_scene_viewer()
            if viewer is None:
                return None
            return tuple(viewer.curViewport().viewTransform().asTuple())
        except (hou.Error, AttributeError):
            return None

    # ------------------------------------------------------------
    def _collect_tool_stage_nodes(self):
        stage = hou.node("/stage")
        if stage is None:
            return {}

        nodes_by_path = {}

        for node_name in TOOL_STAGE_NODE_TYPES:
            node = stage.node(node_name)
            if node is None:
                continue
            if _is_tool_node_candidate(node, node_name):
                nodes_by_path[node.path()] = node

        for node in stage.children():
            if node.path() in nodes_by_path:
                continue
            if _is_tool_node_candidate(node):
                nodes_by_path[node.path()] = node

        return nodes_by_path

    # --------------------------------------------------
    def _destroy_tool_stage_nodes(self, nodes_by_path):
        deleted = []
        skipped = []

        # ATTENTION -> supprimer les nodes affichés sous un viewport Karma actif peut planter Houdini (reproduit sans cet outil),
        # donc on pointe d'abord le viewport de l'outil sur /obj
        if self._karma_scene_viewer is not None:
            try:
                self._karma_scene_viewer.setPwd(hou.node("/obj"))
            except hou.Error:
                pass

        paths_by_name = {}
        for path, node in nodes_by_path.items():
            paths_by_name[node.name()] = path

        ordered_paths = []
        seen_paths = set()

        for node_name in TOOL_STAGE_DELETE_ORDER:
            path = paths_by_name.get(node_name)
            if path and path not in seen_paths:
                ordered_paths.append(path)
                seen_paths.add(path)

        for path in sorted(nodes_by_path.keys()):
            if path not in seen_paths:
                ordered_paths.append(path)
                seen_paths.add(path)

        candidate_paths = set(nodes_by_path.keys())

        def _delete_impl():
            for path in ordered_paths:
                node = hou.node(path)
                if node is None:
                    continue

                external_outputs = []
                for out in node.outputs():
                    if out is None:
                        continue
                    out_path = out.path()
                    if out_path not in candidate_paths:
                        external_outputs.append(out_path)

                if external_outputs:
                    self.log_message(
                        "[WARN] Skip {} (connected to external nodes: {}).".format(
                            path,
                            ", ".join(external_outputs[:3]),
                        )
                    )
                    skipped.append(path)
                    continue

                try:
                    node.destroy()
                    deleted.append(path)
                except hou.Error as exc:
                    self.log_message("[WARN] Could not remove {}: {}".format(path, exc))
                    skipped.append(path)

        with _paused_cooking():
            try:
                with hou.undos.group("BSM Karma - Clear Tool Nodes"):
                    _delete_impl()
            except hou.Error:
                _delete_impl()

        return deleted, skipped

    # ----------------------------------------------------------------------
    @_guarded_slot
    def on_clear_all(self):
        nodes_by_path = self._collect_tool_stage_nodes()
        if not nodes_by_path:
            self.log_message("[INFO] No tool nodes found in /stage.")
            return

        lines = sorted(nodes_by_path.keys())
        preview = "\n".join(lines[:12])
        if len(lines) > 12:
            preview += "\n..."

        msg = (
            "Delete {} tool node(s) in /stage?\n\n{}\n\n"
            "Only nodes created/managed by this tool will be targeted."
        ).format(len(lines), preview)

        reply = QtWidgets.QMessageBox.warning(
            self,
            "Clear All Tool Nodes",
            msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            self.log_message("[INFO] Clear All cancelled.")
            return

        deleted, skipped = self._destroy_tool_stage_nodes(nodes_by_path)
        self.refresh_stage_cameras()
        self.refresh_geo_sources()
        self.log_message(
            "[OK] Clear All done: deleted {} node(s), skipped {} node(s).".format(
                len(deleted),
                len(skipped),
            )
        )

    CAMERA_CREATE_LABEL = "Create New Camera"
