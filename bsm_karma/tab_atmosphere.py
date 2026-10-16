# tab_atmosphere.py - BSM Karma Builder - Atmosphere tab: fog and clouds
# Version : 2026.10.15.1 | Revision : 15-10-2026 | Auteur : BSM

import hou
from hutil.Qt import QtWidgets
from .config import CLOUD2D_BRIGHTNESS, CLOUD_TYPES
from .debuglog import _guarded_slot
from .gauges import FloatSlider, IntSlider
from .previews import AtmosphereVisualWidget
from .widgets import wrap_tab

CLOUD_LABEL_WIDTH = 146


# ------------------------------------------------------------
class AtmosphereTab:

    def _build_atmosphere_tab(self, tabs):
        tab_volumetrics = QtWidgets.QWidget()
        layout_vol_main = QtWidgets.QVBoxLayout(tab_volumetrics)

        self.chk_enable_fog = QtWidgets.QGroupBox("Fog")
        self.chk_enable_fog.setCheckable(True)
        self.chk_enable_fog.setChecked(False)
        self.chk_enable_fog.toggled.connect(self.update_environment_tab)
        
        form_fog = QtWidgets.QFormLayout(self.chk_enable_fog)
        self.combo_fog_preset = QtWidgets.QComboBox()
        self.combo_fog_preset.addItems(["-- Custom --"] + list(self.fog_presets.keys()))
        self.combo_fog_preset.currentIndexChanged.connect(self.apply_fog_preset)
        form_fog.addRow("Fog Preset:", self.combo_fog_preset)
        self.sld_fog_density = FloatSlider(0.0, 5.0, 0.25)
        self.sld_fog_density.valueChanged.connect(
            lambda val: self.atm_widget.update_fog(self.atm_widget.fog_height, val)
        )
        form_fog.addRow("Fog Density:", self.sld_fog_density)
        self.sld_fog_height = FloatSlider(0.0, 500.0, 30.0)
        self.sld_fog_height.valueChanged.connect(
            lambda val: self.atm_widget.update_fog(val, self.atm_widget.fog_density)
        )
        form_fog.addRow("Fog Height:", self.sld_fog_height)
        self.sld_fog_radius = FloatSlider(10.0, 1000.0, 120.0)
        form_fog.addRow("Fog Radius:", self.sld_fog_radius)
        self.sld_fog_phase = FloatSlider(-1.0, 1.0, 0.4)
        form_fog.addRow("Fog Phase:", self.sld_fog_phase)
        self.sld_fog_noise_scale = FloatSlider(0.01, 2.0, 0.1)
        form_fog.addRow("Fog Noise Freq:", self.sld_fog_noise_scale)
        self.sld_fog_noise_amp = FloatSlider(0.0, 2.0, 0.5)
        form_fog.addRow("Fog Noise Amp:", self.sld_fog_noise_amp)
        layout_vol_main.addWidget(self.chk_enable_fog)

        self.chk_enable_clouds = QtWidgets.QGroupBox("Clouds")
        self.chk_enable_clouds.setCheckable(True)
        self.chk_enable_clouds.setChecked(False)
        self.chk_enable_clouds.toggled.connect(self.update_environment_tab)
        
        form_cloud = QtWidgets.QFormLayout(self.chk_enable_clouds)
        self.combo_cloud_type = QtWidgets.QComboBox()
        self.combo_cloud_type.addItems(CLOUD_TYPES)
        self.combo_cloud_type.setToolTip(
            "3D Volume: real clouds, lit by the sun, with parallax. Heavy to render.\n"
            "2D Layer: a cloud picture on a second dome light, added to the sky. Fast, for a distant background.")
        self.combo_cloud_type.currentIndexChanged.connect(self.update_cloud_type_ui)
        form_cloud.addRow("Cloud Type:", self.combo_cloud_type)

        self.w_cloud_3d = QtWidgets.QWidget()
        form_cloud3d = QtWidgets.QFormLayout(self.w_cloud_3d)
        form_cloud3d.setContentsMargins(0, 0, 0, 0)
        self.combo_cloud_preset = QtWidgets.QComboBox()
        self.combo_cloud_preset.addItems(["-- Custom --"] + list(self.cloud_presets.keys()))
        self.combo_cloud_preset.currentIndexChanged.connect(self.apply_cloud_preset)
        form_cloud3d.addRow("Cloud Preset:", self.combo_cloud_preset)
        self.sld_cloud_density = FloatSlider(0.0, 10.0, 0.20)
        self.sld_cloud_density.valueChanged.connect(
            lambda val: self.atm_widget.update_cloud(self.atm_widget.cloud_alt, val)
        )
        form_cloud3d.addRow("Cloud Base Density:", self.sld_cloud_density)
        self.sld_cloud_altitude = FloatSlider(10.0, 13000.0, 140.0)
        self.sld_cloud_altitude.valueChanged.connect(
            lambda val: self.atm_widget.update_cloud(val, self.atm_widget.cloud_density)
        )
        form_cloud3d.addRow("Cloud Altitude:", self.sld_cloud_altitude)
        self.sld_cloud_scale = FloatSlider(10.0, 1000.0, 180.0)
        form_cloud3d.addRow("Cloud Scale:", self.sld_cloud_scale)
        self.sld_cloud_precision = IntSlider(2, 20, 5)
        form_cloud3d.addRow("Cloud Voxel Size (Prec):", self.sld_cloud_precision)
        self.sld_cloud_clip = FloatSlider(0.0, 1.0, 0.35)
        form_cloud3d.addRow("Cloud Edge Clip:", self.sld_cloud_clip)
        self.w_cloud_mat_path = QtWidgets.QWidget()
        layout_cloud_mat = QtWidgets.QHBoxLayout(self.w_cloud_mat_path)
        layout_cloud_mat.setContentsMargins(0, 0, 0, 0)
        self.line_cloud_mat = QtWidgets.QLineEdit()
        self.line_cloud_mat.setPlaceholderText("Automatic: Quick Cloud Material")
        self.line_cloud_mat.setToolTip("Leave empty to use SideFX's Quick Cloud Material, or give the USD path of your own material.")
        btn_browse_cloud_mat = QtWidgets.QPushButton("...")
        btn_browse_cloud_mat.setMaximumWidth(40)
        btn_browse_cloud_mat.clicked.connect(self.browse_cloud_mat)
        layout_cloud_mat.addWidget(self.line_cloud_mat)
        layout_cloud_mat.addWidget(btn_browse_cloud_mat)
        form_cloud3d.addRow("Cloud Material Path:", self.w_cloud_mat_path)
        
        form_cloud.addRow(self.w_cloud_3d)

        self.w_cloud_2d = QtWidgets.QWidget()
        form_cloud2d = QtWidgets.QFormLayout(self.w_cloud_2d)
        form_cloud2d.setContentsMargins(0, 0, 0, 0)
        self.sld_cloud2d_coverage = FloatSlider(0.0, 1.0, 0.45)
        self.sld_cloud2d_coverage.setToolTip("Share of the sky covered by clouds.")
        form_cloud2d.addRow("Coverage:", self.sld_cloud2d_coverage)
        self.sld_cloud2d_softness = FloatSlider(0.0, 1.0, 0.40)
        self.sld_cloud2d_softness.setToolTip("Soft edges and haze (high) or crisp cumulus edges (low).")
        form_cloud2d.addRow("Softness:", self.sld_cloud2d_softness)
        self.sld_cloud2d_scale = FloatSlider(1.0, 12.0, 3.0)
        self.sld_cloud2d_scale.setToolTip("Number of large cloud masses around the horizon.")
        form_cloud2d.addRow("Cloud Size:", self.sld_cloud2d_scale)
        self.sld_cloud2d_brightness = FloatSlider(0.0, 8.0, CLOUD2D_BRIGHTNESS)
        self.sld_cloud2d_brightness.setToolTip("Brightness of the clouds relative to the sky (1 = as bright as the sky). "
                                               "They also light the scene a little, like sky bounce.")
        form_cloud2d.addRow("Brightness:", self.sld_cloud2d_brightness)
        self.sld_cloud2d_seed = IntSlider(0, 999, 7)
        self.sld_cloud2d_seed.setToolTip("Another number, another cloud pattern.")
        form_cloud2d.addRow("Seed:", self.sld_cloud2d_seed)
        form_cloud.addRow(self.w_cloud_2d)
        # the three forms line their sliders up on the same column
        for form in (form_cloud, form_cloud3d, form_cloud2d):
            for row in range(form.rowCount()):
                item = form.itemAt(row, QtWidgets.QFormLayout.LabelRole)
                if item is not None and item.widget() is not None:
                    item.widget().setMinimumWidth(CLOUD_LABEL_WIDTH)
        self.update_cloud_type_ui()

        layout_vol_main.addWidget(self.chk_enable_clouds)
        
        self.atm_widget = AtmosphereVisualWidget()
        lay_atm_vis = QtWidgets.QHBoxLayout()
        lay_atm_vis.addWidget(self.atm_widget)
        layout_vol_main.addLayout(lay_atm_vis, 1)

        tabs.addTab(wrap_tab(tab_volumetrics), "Atmosphere")
        self._config_tabs.append(tab_volumetrics)

    # ------------------------------------------------------------
    def update_cloud_type_ui(self, *_):
        is_2d = self.combo_cloud_type.currentIndex() == 1
        self.w_cloud_3d.setVisible(not is_2d)
        self.w_cloud_2d.setVisible(is_2d)

    # ------------------------------------------------------------
    def apply_fog_preset(self):
        preset_name = self.combo_fog_preset.currentText()
        p = self.fog_presets.get(preset_name)
        if p:
            self.sld_fog_density.setValue(p["dens"])
            self.sld_fog_height.setValue(p["h"])
            self.sld_fog_radius.setValue(p["rad"])
            self.sld_fog_phase.setValue(p["phase"])
            if "ns" in p: self.sld_fog_noise_scale.setValue(p["ns"])
            if "na" in p: self.sld_fog_noise_amp.setValue(p["na"])
            self.atm_widget.update_fog(
                self.sld_fog_height.value(),
                self.sld_fog_density.value()
            )

    # ------------------------------------------------------------
    def apply_cloud_preset(self):
        preset_name = self.combo_cloud_preset.currentText()
        p = self.cloud_presets.get(preset_name)
        if p:
            self.sld_cloud_density.setValue(p["dens"])
            self.sld_cloud_altitude.setValue(p["alt"])
            self.sld_cloud_scale.setValue(p["scale"])
            if "div" in p: self.sld_cloud_precision.setValue(p["div"])
            if "clip" in p: self.sld_cloud_clip.setValue(p["clip"])
            self.atm_widget.update_cloud(
                self.sld_cloud_altitude.value(),
                self.sld_cloud_density.value()
            )

    # ------------------------------------------------------------
    @_guarded_slot
    def browse_cloud_mat(self):
        path = hou.ui.selectNode(initial_node=hou.node("/stage"), title="Select Cloud Material Node or Library")
        if not path:
            return
            
        node = hou.node(path)
        if not node:
            return
            
        prim_path = ""
        
        if isinstance(node, hou.VopNode):
            parent = node.parent()
            while parent and not isinstance(parent, hou.LopNode):
                parent = parent.parent()
                
            if parent and parent.type().name() == "materiallibrary":
                prefix = parent.evalParm("matpathprefix")
                if prefix:
                    if prefix.endswith("/"):
                        prefix = prefix[:-1]
                    prim_path = f"{prefix}/{node.name()}"
        
        elif isinstance(node, hou.LopNode) and node.type().name() == "materiallibrary":
            prefix = node.evalParm("matpathprefix")
            if prefix:
                if prefix.endswith("/"):
                    prefix = prefix[:-1]
                mats = [n for n in node.children() if "surface" in n.type().name() or "volume" in n.type().name() or "cloud" in n.type().name()]
                if mats:
                    prim_path = f"{prefix}/{mats[0].name()}"
                    
        if not prim_path:
            idx, p = hou.ui.readInput(
                "Enter USD Material Primitive Path:",
                buttons=("OK", "Cancel"),
                initial_contents="/World/Materials/" + node.name()
            )
            if idx == 0 and p.strip():
                prim_path = p.strip()
                
        if prim_path:
            self.line_cloud_mat.setText(prim_path)
            self._schedule_live_update()
