# tab_passes.py - BSM Karma Builder - Passes tab: AOVs
# Version : 1.0.0 | Revision : 15-10-2026 | Auteur : BSM

from hutil.Qt import QtWidgets
from .widgets import wrap_tab

# ------------------------------------------------------------
class PassesTab:

    def _build_passes_tab(self, tabs):
        tab_aov = QtWidgets.QWidget()
        layout_aov = QtWidgets.QVBoxLayout(tab_aov)

        grp_aov_main = QtWidgets.QGroupBox("AOV Setup")
        grp_aov_main.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        form_aov_main = QtWidgets.QFormLayout(grp_aov_main)

        self.chk_aovs = QtWidgets.QCheckBox("Generate Standard Render Vars")
        self.chk_aovs.setChecked(True)
        self.chk_aovs.stateChanged.connect(self.update_aov_ui)
        form_aov_main.addRow("Enable AOVs:", self.chk_aovs)

        self.combo_aov_preset = QtWidgets.QComboBox()
        self.combo_aov_preset.addItems(["Custom", "Utility", "Lighting", "Full"])
        self.combo_aov_preset.currentIndexChanged.connect(self.apply_aov_preset)
        form_aov_main.addRow("AOV Preset:", self.combo_aov_preset)

        layout_aov.addWidget(grp_aov_main)

        self.grp_aov_passes = QtWidgets.QGroupBox("AOV Passes")
        self.grp_aov_passes.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        form_aov_passes = QtWidgets.QFormLayout(self.grp_aov_passes)

        self.chk_ao = QtWidgets.QCheckBox("Ambient Occlusion")
        self.chk_ao.setChecked(False)
        form_aov_passes.addRow("AO:", self.chk_ao)

        self.chk_aov_depth = QtWidgets.QCheckBox("Depth (Z)")
        self.chk_aov_depth.setChecked(True)
        form_aov_passes.addRow("Depth:", self.chk_aov_depth)

        self.chk_aov_normal = QtWidgets.QCheckBox("Normal")
        self.chk_aov_normal.setChecked(True)
        form_aov_passes.addRow("Normal:", self.chk_aov_normal)

        self.chk_aov_position = QtWidgets.QCheckBox("Position")
        self.chk_aov_position.setChecked(False)
        form_aov_passes.addRow("Position:", self.chk_aov_position)

        self.chk_aov_albedo = QtWidgets.QCheckBox("Albedo / Base Color")
        self.chk_aov_albedo.setChecked(False)
        form_aov_passes.addRow("Albedo:", self.chk_aov_albedo)

        self.chk_aov_emission = QtWidgets.QCheckBox("Emission")
        self.chk_aov_emission.setChecked(False)
        form_aov_passes.addRow("Emission:", self.chk_aov_emission)

        self.chk_aov_diffuse = QtWidgets.QCheckBox("Diffuse")
        self.chk_aov_diffuse.setChecked(False)
        form_aov_passes.addRow("Diffuse:", self.chk_aov_diffuse)

        self.chk_aov_specular = QtWidgets.QCheckBox("Specular")
        self.chk_aov_specular.setChecked(False)
        form_aov_passes.addRow("Specular:", self.chk_aov_specular)

        self.chk_aov_motion = QtWidgets.QCheckBox("Motion Vectors")
        self.chk_aov_motion.setChecked(False)
        form_aov_passes.addRow("Motion:", self.chk_aov_motion)

        self.chk_aov_shadow = QtWidgets.QCheckBox("Shadow")
        self.chk_aov_shadow.setChecked(False)
        form_aov_passes.addRow("Shadow:", self.chk_aov_shadow)

        self.chk_aov_id = QtWidgets.QCheckBox("ID / Crypto")
        self.chk_aov_id.setChecked(False)
        form_aov_passes.addRow("ID:", self.chk_aov_id)

        layout_aov.addWidget(self.grp_aov_passes)

        self.grp_aov_output = QtWidgets.QGroupBox("AOV Output")
        self.grp_aov_output.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        self.form_aov_output = QtWidgets.QFormLayout(self.grp_aov_output)

        self.chk_aov_multilayer = QtWidgets.QCheckBox("One multilayer EXR")
        self.chk_aov_multilayer.setChecked(True)
        self.chk_aov_multilayer.setToolTip("Store all the AOVs in one multilayer EXR when possible; unticked, one file per pass.")
        self.form_aov_output.addRow("Combine:", self.chk_aov_multilayer)

        self.chk_aov_half_precision = QtWidgets.QCheckBox("16-bit (half) passes")
        self.chk_aov_half_precision.setChecked(False)
        self.chk_aov_half_precision.setToolTip("Use 16-bit (half) floats for the passes other than the beauty, when supported.")
        self.form_aov_output.addRow("Precision:", self.chk_aov_half_precision)

        layout_aov.addWidget(self.grp_aov_output)
        layout_aov.addStretch(1)

        tabs.addTab(wrap_tab(tab_aov), "Passes")
        self._config_tabs.append(tab_aov)

    def apply_aov_preset(self):
        preset = self.combo_aov_preset.currentText()
        pass_widgets = [
            self.chk_ao,
            self.chk_aov_depth,
            self.chk_aov_normal,
            self.chk_aov_position,
            self.chk_aov_albedo,
            self.chk_aov_emission,
            self.chk_aov_diffuse,
            self.chk_aov_specular,
            self.chk_aov_motion,
            self.chk_aov_shadow,
            self.chk_aov_id,
        ]

        for w in pass_widgets:
            w.blockSignals(True)

        if preset == "Utility":
            self.chk_ao.setChecked(True)
            self.chk_aov_depth.setChecked(True)
            self.chk_aov_normal.setChecked(True)
            self.chk_aov_position.setChecked(True)
            self.chk_aov_albedo.setChecked(False)
            self.chk_aov_emission.setChecked(False)
            self.chk_aov_diffuse.setChecked(False)
            self.chk_aov_specular.setChecked(False)
            self.chk_aov_motion.setChecked(True)
            self.chk_aov_shadow.setChecked(False)
            self.chk_aov_id.setChecked(True)
        elif preset == "Lighting":
            self.chk_ao.setChecked(True)
            self.chk_aov_depth.setChecked(False)
            self.chk_aov_normal.setChecked(False)
            self.chk_aov_position.setChecked(False)
            self.chk_aov_albedo.setChecked(True)
            self.chk_aov_emission.setChecked(True)
            self.chk_aov_diffuse.setChecked(True)
            self.chk_aov_specular.setChecked(True)
            self.chk_aov_motion.setChecked(False)
            self.chk_aov_shadow.setChecked(True)
            self.chk_aov_id.setChecked(False)
        elif preset == "Full":
            for w in pass_widgets:
                w.setChecked(True)

        for w in pass_widgets:
            w.blockSignals(False)

    # ------------------------------------------------------------
    def update_aov_ui(self):
        enabled = self.chk_aovs.isChecked()
        self.grp_aov_passes.setEnabled(enabled)
        self.grp_aov_output.setEnabled(enabled)
