# Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Lighting tab: HDRI and physical sky
# Houdini : 21 and 22
# Version : 1.0.0

import hashlib
import hou
import os
import shutil
import subprocess
from hutil.Qt import QtWidgets, QtCore, QtGui
from .debuglog import _debug, _guarded_slot
from .gauges import FloatSlider, IntSlider
from .hdrireader import PREVIEW_COLUMNS, read_preview
from .previews import SunAltitudeWidget, SunCompassWidget
from .util import _expand_plain_path, _private_temp_dir
from .widgets import ColorSwatch, HdriPreview, wrap_tab

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

        self.lbl_hdri_preview = HdriPreview("HDRI preview")
        self.lbl_hdri_preview.setObjectName("hdriPreview")
        self.form_base.addRow("HDRI Preview:", self.lbl_hdri_preview)

        layout_lights.addWidget(grp_base)

        self.grp_lamps = QtWidgets.QGroupBox("Lamp Colors")
        self.grp_lamps.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        self.form_lamps = QtWidgets.QFormLayout(self.grp_lamps)
        for lamp, label in (("key", "Key"), ("fill", "Fill"), ("rim", "Rim")):
            temp = IntSlider(2500, 12000, 6500)
            temp.setToolTip("Color temperature of the lamp in kelvin: low is warm (orange), high is cool (blue). 6500 is neutral.")
            tint = FloatSlider(-1.0, 1.0, 0.0)
            tint.setToolTip("Shift between green (negative) and magenta (positive).")
            setattr(self, "spin_lamp_{}_temp".format(lamp), temp)
            setattr(self, "sld_lamp_{}_tint".format(lamp), tint)
            self.form_lamps.addRow("{} Temp. (K):".format(label), temp)
            self.form_lamps.addRow("{} Tint:".format(label), tint)
        layout_lights.addWidget(self.grp_lamps)
        
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

        w_amb_label = QtWidgets.QWidget()
        lay_amb_label = QtWidgets.QVBoxLayout(w_amb_label)
        lay_amb_label.setContentsMargins(0, 0, 0, 0)
        lay_amb_label.setSpacing(3)
        lay_amb_label.addStretch(1)
        lay_amb_label.addWidget(QtWidgets.QLabel("Ambient Tint:"))
        self.swatch_amb = ColorSwatch()
        lay_amb_label.addWidget(self.swatch_amb)
        lay_amb_label.addStretch(1)
        form_sky.addRow(w_amb_label, lay_rgb_amb)

        def _update_amb_swatch(*_):
            self.swatch_amb.set_rgb(self.sp_amb_r.value(), self.sp_amb_g.value(), self.sp_amb_b.value())
        for slider in (self.sp_amb_r, self.sp_amb_g, self.sp_amb_b):
            slider.valueChanged.connect(_update_amb_swatch)
        _update_amb_swatch()

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
        self._sync_env_type_items(mode)
        env_type = self.combo_env_type.currentText()

        self.combo_env_type.setEnabled(mode in ["Environment", "Interior"])

        is_hdri = (mode in ["Studio", "3 Points"]) or (mode in ["Environment", "Interior"] and env_type == "HDRI Image")
        # an interior has no sky: its light is the window, and an HDRI is only what is seen through it
        is_physical = (mode == "Environment" and env_type == "Physical Sky")
        
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

        self.grp_lamps.setVisible(mode in ["Studio", "3 Points", "Interior"])
        key_name = "Window" if mode == "Interior" else "Key"
        self.form_lamps.labelForField(self.spin_lamp_key_temp).setText("{} Temp. (K):".format(key_name))
        self.form_lamps.labelForField(self.sld_lamp_key_tint).setText("{} Tint:".format(key_name))
        for lamp in ("fill", "rim"):
            for widget in (getattr(self, "spin_lamp_{}_temp".format(lamp)), getattr(self, "sld_lamp_{}_tint".format(lamp))):
                self._set_form_field_visible(self.form_lamps, widget, mode == "3 Points")

        # the preset is applied when it is picked (sync_from_*), not at every refresh: that wiped the sliders
        self.grp_sky.setVisible(is_physical)

    # ------------------------------------------------------------
    # Environment: a physical sky or an HDRI. Interior: nothing outside (the window light alone) or an HDRI seen through
    # the window. The choice is kept when it exists in the new list.
    def _sync_env_type_items(self, mode):
        wanted = ["None", "HDRI Image"] if mode == "Interior" else ["Physical Sky", "HDRI Image"]
        current = [self.combo_env_type.itemText(i) for i in range(self.combo_env_type.count())]
        label = self.form_main.labelForField(self.combo_env_type)
        if label is not None:
            label.setText("Window View:" if mode == "Interior" else "Environment Type:")
        self.combo_env_type.setToolTip("No sky in an interior: the window light is the light. An HDRI is seen through the window and also lights the room." if mode == "Interior" else "")
        if current == wanted:
            return
        keep = self.combo_env_type.currentText()
        self.combo_env_type.blockSignals(True)
        self.combo_env_type.clear()
        self.combo_env_type.addItems(wanted)
        self.combo_env_type.setCurrentText(keep if keep in wanted else wanted[0])
        self.combo_env_type.blockSignals(False)

    # ----------------------------------------------------------------------
    def _set_hdri_preview_message(self, message):
        self.lbl_hdri_preview.set_message(message)

    # ------------------------------------------------------------------------
    # The picture to preview, at most PREVIEW_COLUMNS wide, and what went wrong when there is none. Qt reads the usual
    # formats; Radiance and OpenEXR are read by hdrireader; Houdini's iconvert is the last resort.
    def _load_hdri_preview_image(self, source_path):
        reader = QtGui.QImageReader(source_path)
        reader.setAutoTransform(True)
        if hasattr(reader, "setAllocationLimit"):
            reader.setAllocationLimit(0)
        if reader.canRead():
            size = reader.size()
            if size.width() > PREVIEW_COLUMNS:
                reader.setScaledSize(QtCore.QSize(PREVIEW_COLUMNS, max(1, round(size.height() * PREVIEW_COLUMNS / float(size.width())))))
            image = reader.read()
            if not image.isNull():
                return image, ""

        pixels, reason = read_preview(source_path)
        if pixels is not None:
            height, width = pixels.shape[:2]
            return QtGui.QImage(pixels.tobytes(), width, height, width * 3, QtGui.QImage.Format_RGB888).copy(), ""
        _debug("HDRI preview: own reader: {}".format(reason))

        converted, detail = self._convert_with_iconvert(source_path)
        if converted is not None:
            return converted, ""
        return None, "{}; {}".format(reason, detail)

    # ------------------------------------------------------------------------
    def _convert_with_iconvert(self, source_path):
        key = hashlib.md5(source_path.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
        preview_path = os.path.join(_private_temp_dir(), "hdri_preview_{}.jpg".format(key))
        if preview_path not in getattr(self, "_hdri_temp_files", []):
            self._hdri_temp_files.append(preview_path)
        try:
            fresh = os.path.isfile(preview_path) and os.path.getmtime(preview_path) >= os.path.getmtime(source_path)
        except OSError:
            return None, "the file cannot be read"

        detail = "iconvert not found"
        if not fresh:
            # only the executables that exist: a missing path costs a blocking launch
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
            for iconvert_exe in candidates:
                try:
                    subprocess.run([iconvert_exe, source_path, preview_path], check=True, timeout=30,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=0x08000000 if os.name == "nt" else 0)
                    break
                except subprocess.CalledProcessError as exc:
                    detail = "iconvert failed: {}".format((exc.stderr or b"").decode("utf-8", "replace").strip()[:120] or exc.returncode)
                except (OSError, subprocess.SubprocessError) as exc:
                    detail = "iconvert failed: {}".format(exc)
            else:
                _debug("HDRI preview: {}".format(detail))
                return None, detail

        reader = QtGui.QImageReader(preview_path)
        if hasattr(reader, "setAllocationLimit"):
            reader.setAllocationLimit(0)
        size = reader.size()
        if size.width() > PREVIEW_COLUMNS:
            reader.setScaledSize(QtCore.QSize(PREVIEW_COLUMNS, max(1, round(size.height() * PREVIEW_COLUMNS / float(size.width())))))
        image = reader.read()
        return (image, "") if not image.isNull() else (None, "iconvert wrote a file Qt cannot read")

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

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            image, reason = self._load_hdri_preview_image(source_path)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if image is None:
            _debug("HDRI preview of {}: {}".format(source_path, reason))
            self._set_hdri_preview_message("Preview unavailable: {}".format(reason))
            return
        self.lbl_hdri_preview.set_picture(image)
