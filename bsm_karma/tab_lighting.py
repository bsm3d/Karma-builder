# tab_lighting.py - BSM Karma Builder - Lighting tab: HDRI and physical sky
# Version : 2026.10.15.1 | Revision : 15-10-2026 | Auteur : BSM

import hashlib
import hou
import os
import shutil
import subprocess
from hutil.Qt import QtWidgets, QtCore, QtGui
from .debuglog import _guarded_slot
from .gauges import FloatSlider, IntSlider
from .previews import SunAltitudeWidget, SunCompassWidget
from .util import _expand_plain_path, _private_temp_dir
from .widgets import wrap_tab

HDRI_PREVIEW_MAX_BYTES = 400 * 1024 * 1024


# ------------------------------------------------------------
class LightingTab:

    def _build_lighting_tab(self, tabs):
        tab_lights = QtWidgets.QWidget()
        layout_lights = QtWidgets.QVBoxLayout(tab_lights)
        
        grp_base = QtWidgets.QGroupBox("General Lights / HDRI")
        grp_base.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        self.form_base = QtWidgets.QFormLayout(grp_base)
        self.sld_hdri_int = FloatSlider(0.0, 20.0, 1.0)
        self.sld_area_int = FloatSlider(0.0, 100.0, 10.0)
        self.form_base.addRow("Dome Intensity:", self.sld_hdri_int)
        self.form_base.addRow("Main Area Intensity:", self.sld_area_int)

        self.w_hdri_path = QtWidgets.QWidget()
        layout_hdri = QtWidgets.QHBoxLayout(self.w_hdri_path)
        layout_hdri.setContentsMargins(0, 0, 0, 0)
        self.line_hdri_path = QtWidgets.QLineEdit("$HIP/hdri/overcast_sky.exr")
        
        self._hdri_preview_timer = QtCore.QTimer(self)
        self._hdri_preview_timer.setSingleShot(True)
        self._hdri_preview_timer.timeout.connect(self._do_hdri_preview)
        
        self.line_hdri_path.textChanged.connect(lambda: self._hdri_preview_timer.start(400))
        btn_browse_hdri = QtWidgets.QPushButton("...")
        btn_browse_hdri.setMaximumWidth(40)
        btn_browse_hdri.clicked.connect(self.browse_hdri)
        layout_hdri.addWidget(self.line_hdri_path)
        layout_hdri.addWidget(btn_browse_hdri)
        self.form_base.addRow("HDRI Path:", self.w_hdri_path)

        self.sld_hdri_ev = FloatSlider(-8.0, 8.0, 0.0)
        self.sld_hdri_ev.setToolTip("Exposure in stops (EV).")
        self.form_base.addRow("HDRI Exposure:", self.sld_hdri_ev)

        self.sld_hdri_rot = FloatSlider(-180.0, 180.0, 0.0)
        self.form_base.addRow("HDRI Rotation Y:", self.sld_hdri_rot)

        self.sld_hdri_sat = FloatSlider(0.0, 2.0, 1.0)
        self.form_base.addRow("HDRI Saturation:", self.sld_hdri_sat)

        self.spin_hdri_temp = IntSlider(2500, 12000, 6500)
        self.spin_hdri_temp.setToolTip("Color temperature in kelvin.")
        self.form_base.addRow("HDRI Temp. (K):", self.spin_hdri_temp)

        self.sld_hdri_tint = FloatSlider(-1.0, 1.0, 0.0)
        self.form_base.addRow("HDRI Tint:", self.sld_hdri_tint)

        self.lbl_hdri_preview = QtWidgets.QLabel("HDRI preview")
        self.lbl_hdri_preview.setMinimumHeight(110)
        self.lbl_hdri_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_hdri_preview.setScaledContents(True)
        self.lbl_hdri_preview.setTextFormat(QtCore.Qt.PlainText)
        self.lbl_hdri_preview.setObjectName("hdriPreview")
        self.form_base.addRow("HDRI Preview:", self.lbl_hdri_preview)

        layout_lights.addWidget(grp_base)
        
        self.grp_sky = QtWidgets.QGroupBox("Karma Physical Sky")
        self.grp_sky.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        form_sky = QtWidgets.QFormLayout(self.grp_sky)
        self.form_sky = form_sky
        
        self.combo_sky_preset = QtWidgets.QComboBox()
        self.combo_sky_preset.addItems(self._sky_preset_names)
        self.combo_sky_preset.currentIndexChanged.connect(self.sync_from_lights_tab)
        form_sky.addRow("Atmosphere Preset:", self.combo_sky_preset)

        self.combo_sky_mode = QtWidgets.QComboBox()
        self.combo_sky_mode.addItems(["Basic Projection (Fast)", "Volumetric Atmosphere (Realistic)"])
        self.combo_sky_mode.currentIndexChanged.connect(self.sync_from_lights_tab)
        form_sky.addRow("Sky Rendering:", self.combo_sky_mode)

        self.sld_sky_elev = FloatSlider(-20.0, 90.0, 30.0, decimals=1,
            snap_points=[-20, 0, 15, 30, 75, 90],
            tick_points=[(-20, "-20"), (0, "0"), (15, "15"), (30, "30"), (75, "75"), (90, "90")])
        
        self.sld_sky_azim = FloatSlider(0.0, 360.0, 0.0, decimals=1,
            snap_points=[0, 45, 90, 135, 180, 225, 270, 315, 360],
            tick_points=[(0, "0"), (90, "90"), (180, "180"), (270, "270"), (360, "360")])
        
        self.compass_widget = SunCompassWidget()
        self.compass_widget.set_azimuth(0.0)
        self.compass_widget.set_elevation(30.0)
        
        self.altitude_widget = SunAltitudeWidget()
        self.altitude_widget.set_elevation(30.0)
        
        # valueChanged carries the real value and also fires for presets and typed values
        self.sld_sky_azim.valueChanged.connect(self.compass_widget.set_azimuth)
        self.sld_sky_elev.valueChanged.connect(
            lambda val: (
                self.compass_widget.set_elevation(val),
                self.altitude_widget.set_elevation(val)
            )
        )
        
        lay_azim_compass = QtWidgets.QHBoxLayout()
        lay_azim_compass.addStretch(1)
        lay_azim_compass.addWidget(self.compass_widget)
        lay_azim_compass.addWidget(self.altitude_widget)
        lay_azim_compass.addStretch(1)
        
        form_sky.addRow("Solar Altitude:", self.sld_sky_elev)
        form_sky.addRow("Solar Direction:", self.sld_sky_azim)
        self.chk_sky_follow_view = QtWidgets.QCheckBox("Follow the viewport heading")
        self.chk_sky_follow_view.setToolTip(
            "Off: the sun sits at the Solar Direction shown by the compass.\n"
            "On: the Y rotation of the active Scene Viewer is added, so the sun turns with the view.")
        form_sky.addRow("Align to View:", self.chk_sky_follow_view)
        form_sky.addRow(lay_azim_compass)   # spans both columns: it must not add to the width of the labels

        self.sld_sun_int = FloatSlider(0.0, 50.0, 1.0)
        self.sld_sun_size = FloatSlider(0.01, 10.0, 0.53)
        form_sky.addRow("Sun Intensity:", self.sld_sun_int)
        form_sky.addRow("Angular Size:", self.sld_sun_size)
        
        self.spin_sun_temp = IntSlider(1500, 20000, 5500)
        
        self.combo_sun_temp_preset = QtWidgets.QComboBox()
        self.combo_sun_temp_preset.addItems([
            "-- Custom --",
            "Candle (1900K)",
            "Tungsten (2850K)",
            "Halogen (3200K)",
            "Moonlight (4100K)",
            "Daylight (5500K)",
            "Overcast (6500K)",
            "Blue Sky (10000K)"
        ])
        
        def _on_sun_temp_preset(idx):
            presets = {
                1: 1900, 2: 2850, 3: 3200, 4: 4100, 
                5: 5500, 6: 6500, 7: 10000
            }
            if idx in presets:
                self.spin_sun_temp.blockSignals(True)
                self.spin_sun_temp.setValue(presets[idx])
                self.spin_sun_temp.blockSignals(False)
                
        self.combo_sun_temp_preset.currentIndexChanged.connect(_on_sun_temp_preset)
        self.spin_sun_temp.valueChanged.connect(lambda v: self.combo_sun_temp_preset.setCurrentIndex(0))
        
        lay_sun_temp = QtWidgets.QHBoxLayout()
        lay_sun_temp.setContentsMargins(0, 0, 0, 0)
        lay_sun_temp.addWidget(self.combo_sun_temp_preset)
        lay_sun_temp.addWidget(self.spin_sun_temp)
        
        form_sky.addRow("Sun Temp. (K):", lay_sun_temp)

        lay_rgb_amb = QtWidgets.QVBoxLayout()
        lay_amb_r = QtWidgets.QHBoxLayout(); lay_amb_r.addWidget(QtWidgets.QLabel("R:")); self.sp_amb_r = FloatSlider(0.0, 2.0, 1.0); lay_amb_r.addWidget(self.sp_amb_r)
        lay_amb_g = QtWidgets.QHBoxLayout(); lay_amb_g.addWidget(QtWidgets.QLabel("G:")); self.sp_amb_g = FloatSlider(0.0, 2.0, 1.0); lay_amb_g.addWidget(self.sp_amb_g)
        lay_amb_b = QtWidgets.QHBoxLayout(); lay_amb_b.addWidget(QtWidgets.QLabel("B:")); self.sp_amb_b = FloatSlider(0.0, 2.0, 1.0); lay_amb_b.addWidget(self.sp_amb_b)
        lay_rgb_amb.addLayout(lay_amb_r)
        lay_rgb_amb.addLayout(lay_amb_g)
        lay_rgb_amb.addLayout(lay_amb_b)
        form_sky.addRow("Ambient Tint:", lay_rgb_amb)

        self.sld_turbidity = FloatSlider(1.0, 10.0, 3.0)
        self.sld_sky_int = FloatSlider(0.0, 30.0, 1.0)
        self.sld_turbidity.setToolTip("Haze of the Basic Projection (classic) sky.")
        form_sky.addRow("Turbidity:", self.sld_turbidity)
        form_sky.addRow("Sky Intensity:", self.sld_sky_int)
        self.sld_hz_blur = FloatSlider(0.0, 45.0, 5.0)
        self.sld_hz_blur.setToolTip("Horizon blur of the Basic Projection (classic) sky.")
        form_sky.addRow("Horizon Blur:", self.sld_hz_blur)
        
        self.sld_atm_rayleigh = FloatSlider(0.0, 5.0, 1.0)
        self.sld_atm_mie = FloatSlider(0.0, 5.0, 1.0)
        self.sld_atm_rayleigh.setToolTip("Rayleigh scattering: the blue of the volumetric atmosphere.")
        form_sky.addRow("Rayleigh (blue):", self.sld_atm_rayleigh)
        self.sld_atm_mie.setToolTip("Mie scattering: the haze of the volumetric atmosphere.")
        form_sky.addRow("Mie (haze):", self.sld_atm_mie)

        layout_lights.addWidget(self.grp_sky)
        layout_lights.addStretch(1)
        tabs.addTab(wrap_tab(tab_lights), "Lighting")
        self._config_tabs.append(tab_lights)

    # ----------------------------------------
    def sync_from_main_tab(self, idx):
        self.combo_sky_preset.blockSignals(True)
        self.combo_sky_preset.setCurrentIndex(idx)
        self.combo_sky_preset.blockSignals(False)
        self.apply_sky_preset_data(self.combo_time_preset.currentText())

    # ----------------------------------------
    def sync_from_lights_tab(self, idx):
        self.combo_time_preset.blockSignals(True)
        self.combo_time_preset.setCurrentIndex(idx)
        self.combo_time_preset.blockSignals(False)
        self.apply_sky_preset_data(self.combo_sky_preset.currentText())

    # ------------------------------------------------------------
    def apply_sky_preset_data(self, preset_name):
        p = self.sky_presets.get(preset_name)
        if p:
            self.sld_sky_elev.setValue(p["elv"])
            self.sld_sun_int.setValue(p["s_int"])
            self.sld_turbidity.setValue(p["turb"])
            self.sld_sky_int.setValue(p["sk_int"])
            self.sld_hz_blur.setValue(p["hz"])
            
            if "atm_r" in p: self.sld_atm_rayleigh.setValue(p["atm_r"])
            if "atm_m" in p: self.sld_atm_mie.setValue(p["atm_m"])
            if "sun_t" in p: self.spin_sun_temp.setValue(p["sun_t"])
            if "amb_r" in p: self.sp_amb_r.setValue(p["amb_r"])
            if "amb_g" in p: self.sp_amb_g.setValue(p["amb_g"])
            if "amb_b" in p: self.sp_amb_b.setValue(p["amb_b"])

    # ------------------------------------------------------------------------
    @_guarded_slot
    def browse_hdri(self):
        path = hou.ui.selectFile(start_directory="$HIP", title="Select HDRI", pattern="*.exr *.hdr *.rat", chooser_mode=hou.fileChooserMode.Read)
        if path:
            try:
                self.line_hdri_path.setText(_expand_plain_path(path))
            except ValueError as exc:
                self.log_message("[WARN] HDRI path not changed: {}".format(exc))
                return
            self._do_hdri_preview()
            self._schedule_live_update()

    # ------------------------------------------------------------
    def update_environment_tab(self):
        mode = self.combo_scene_mode.currentText()
        is_env_mode = (mode == "Environment")
        env_type = self.combo_env_type.currentText()

        self.combo_env_type.setEnabled(mode in ["Environment", "Interior"])

        is_hdri = (mode in ["Studio", "3 Points"]) or (mode in ["Environment", "Interior"] and env_type == "HDRI Image")
        is_physical = (mode in ["Environment", "Interior"] and env_type == "Physical Sky")
        
        self.lbl_hdri_preview.setMinimumHeight(110 if is_hdri else 0)

        hdri_rows = [
            self.sld_hdri_int,
            self.w_hdri_path,
            self.sld_hdri_ev,
            self.sld_hdri_rot,
            self.sld_hdri_sat,
            self.spin_hdri_temp,
            self.sld_hdri_tint,
            self.lbl_hdri_preview,
        ]
        for field in hdri_rows:
            self._set_form_field_visible(self.form_base, field, is_hdri)

        self.chk_enable_fog.setEnabled(is_env_mode)
        self.chk_enable_clouds.setEnabled(is_env_mode)

        # the preset is applied when it is picked (sync_from_*), not at every refresh: that wiped the sliders
        self.grp_sky.setVisible(is_physical)

    # ----------------------------------------------------------------------
    def _set_hdri_preview_message(self, message):
        self.lbl_hdri_preview.setPixmap(QtGui.QPixmap())
        self.lbl_hdri_preview.setText(message)

    # ------------------------------------------------------------------------
    def _load_hdri_preview_pixmap(self, source_path):
        pixmap = QtGui.QPixmap(source_path)
        if not pixmap.isNull():
            return pixmap

        key = hashlib.md5(source_path.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
        preview_path = os.path.join(_private_temp_dir(), f"hdri_preview_{key}.jpg")
        if preview_path not in getattr(self, "_hdri_temp_files", []):
            self._hdri_temp_files.append(preview_path)

        try:
            src_mtime = os.path.getmtime(source_path)
        except OSError:
            return None

        need_convert = True
        if os.path.isfile(preview_path):
            try:
                need_convert = os.path.getmtime(preview_path) < src_mtime
            except OSError:
                need_convert = True

        if need_convert:
            # petite optimisation: seulement les exécutables qui existent, un chemin absent coûte un lancement bloquant
            candidates = []
            for folder in (os.environ.get("HB"), os.path.join(os.environ.get("HFS", ""), "bin") if os.environ.get("HFS") else None):
                if not folder:
                    continue
                for name in ("iconvert.exe", "iconvert"):
                    path = os.path.join(folder, name)
                    if os.path.isfile(path) and path not in candidates:
                        candidates.append(path)
            on_path = shutil.which("iconvert")
            if on_path and on_path not in candidates:
                candidates.append(on_path)

            converted = False
            for iconvert_exe in candidates:
                try:
                    # Fallback conversion for EXR/HDR when Qt cannot decode directly.
                    if os.name == "nt":
                        subprocess.run(
                            [iconvert_exe, source_path, preview_path],
                            check=True,
                            timeout=8,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            creationflags=0x08000000,
                        )
                    else:
                        subprocess.run(
                            [iconvert_exe, source_path, preview_path],
                            check=True,
                            timeout=8,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        )
                    converted = True
                    break
                except (OSError, subprocess.SubprocessError):
                    pass

            if not converted:
                return None

        preview_pixmap = QtGui.QPixmap(preview_path)
        if preview_pixmap.isNull():
            return None
        return preview_pixmap

    # ------------------------------------------------------------
    @_guarded_slot
    def _do_hdri_preview(self):
        source_path = self.line_hdri_path.text().strip()
        if not source_path:
            self._set_hdri_preview_message("No HDRI path")
            return

        try:
            source_path = os.path.abspath(_expand_plain_path(source_path))
        except ValueError:
            self._set_hdri_preview_message("Path refused: it contains an expression")
            return
        if not os.path.isfile(source_path):
            self._set_hdri_preview_message("HDRI file not found")
            return
        if os.path.getsize(source_path) > HDRI_PREVIEW_MAX_BYTES:
            self._set_hdri_preview_message("File too large for a preview")
            return

        pixmap = self._load_hdri_preview_pixmap(source_path)
        if pixmap is None:
            self._set_hdri_preview_message("Preview unavailable for this format")
            return

        self.lbl_hdri_preview.setText("")
        self.lbl_hdri_preview.setPixmap(pixmap)
