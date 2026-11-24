# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Lighting tab of the Karma Builder dialog, with the HDRI and physical sky controls.

# Houdini : 21 and 22

import datetime
import hashlib
import hou
import math
import os
import shutil
import subprocess
from hutil.Qt import QtWidgets, QtCore, QtGui
from .debuglog import _debug, _guarded_slot
from .ephemeris import sky_snapshot
from .gauges import FloatSlider, IntSlider
from .hdrireader import PREVIEW_COLUMNS, read_preview
from .previews import SunAltitudeWidget, SunCompassWidget
from .styles import _C
from .util import _apply_saturation, _apply_tint, _kelvin_to_rgb, _datas_folder, _default_hdri_path, _expand_plain_path, _private_temp_dir
from .widgets import ColorSwatch, FoldGroup, HdriPreview, wrap_tab

HDRI_PREVIEW_MAX_BYTES = 400 * 1024 * 1024

# ------------------------------------------------------------
class LightingTab:

    def _build_lighting_tab(self, tabs):
        tab_lights = QtWidgets.QWidget()
        layout_lights = QtWidgets.QVBoxLayout(tab_lights)
        
        grp_base = QtWidgets.QGroupBox("General Lights / HDRI")
        grp_base.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        self.form_base = QtWidgets.QFormLayout(grp_base)
        self.sld_hdri_int = FloatSlider(0.0, 4.0, 1.0)
        self.sld_area_int = FloatSlider(0.0, 100.0, 10.0)
        self.form_base.addRow("Dome Intensity:", self.sld_hdri_int)
        self.form_base.addRow("Area Intensity:", self.sld_area_int)

        self.w_hdri_path = QtWidgets.QWidget()
        layout_hdri = QtWidgets.QHBoxLayout(self.w_hdri_path)
        layout_hdri.setContentsMargins(0, 0, 0, 0)
        self.line_hdri_path = QtWidgets.QLineEdit(_default_hdri_path())
        
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
        # the preview follows the exposure, rotation, saturation, temperature and tint sliders (a short pause
        # between two moves of a slider, the picture is rebuilt with numpy)
        self._hdri_preview_base = None
        self._hdri_look_timer = QtCore.QTimer(self)
        self._hdri_look_timer.setSingleShot(True)
        self._hdri_look_timer.timeout.connect(self._refresh_hdri_look)
        for slider in (self.sld_hdri_ev, self.sld_hdri_rot, self.sld_hdri_sat, self.spin_hdri_temp, self.sld_hdri_tint):
            slider.valueChanged.connect(lambda _v=None: self._hdri_look_timer.start(60))
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
        
        # The sky is cut in folding sections: the preset and the exact sky first (the exact sky decides what the sun, the moon and
        # the stars read), then the sun, then the atmosphere. The moon and the stars are in their own tab (Night Sky).
        self.grp_sky = QtWidgets.QWidget()
        self.grp_sky.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        lay_sky = QtWidgets.QVBoxLayout(self.grp_sky)
        lay_sky.setContentsMargins(0, 0, 0, 0)

        fold_sky = FoldGroup("Karma Physical Sky")
        form_sky = fold_sky.form
        self.fold_sky = fold_sky

        self.combo_sky_preset = QtWidgets.QComboBox()
        self.combo_sky_preset.addItems(self._sky_preset_names)
        self.combo_sky_preset.currentIndexChanged.connect(self.sync_from_lights_tab)
        form_sky.addRow("Sky Preset:", self.combo_sky_preset)

        self.combo_sky_mode = QtWidgets.QComboBox()
        self.combo_sky_mode.addItems(["Basic Projection (Fast)", "Volumetric Atmosphere (Realistic)"])
        self.combo_sky_mode.currentIndexChanged.connect(self.sync_from_lights_tab)
        form_sky.addRow("Sky Rendering:", self.combo_sky_mode)

        self.chk_exact = QtWidgets.QCheckBox("Exact Sky (date, time, place)")
        self.chk_exact.setToolTip("The sun, the moon, the planets and the stars are where they really are for this date, this time (UT) and this place. "
                                  "Solar Altitude, Solar Direction, Moon Phase and Star Time are then computed and not read from the sliders.")
        form_sky.addRow(self.chk_exact)
        lbl_exact_hint = QtWidgets.QLabel("On: Solar Altitude, Solar Direction, Moon Phase and Star Time come from the date below and are greyed.")
        lbl_exact_hint.setWordWrap(True)
        lbl_exact_hint.setStyleSheet("color: {};".format(_C["text_muted"]))
        form_sky.addRow(lbl_exact_hint)

        # the place and the date: opens by itself with the exact sky
        self.fold_place = FoldGroup("Place and Date", opened=False)
        form_place = self.fold_place.form
        self.sld_star_lat = FloatSlider(-90.0, 90.0, 45.0, decimals=1)
        self.sld_star_lat.setToolTip("Latitude of the observer: how high the celestial pole stands above the north horizon (north is -Z). "
                                     "It tilts the stars and the path of the moon, with or without the exact sky.")
        form_place.addRow("Latitude:", self.sld_star_lat)
        self.sld_star_lon = FloatSlider(-180.0, 180.0, 0.0, decimals=2)
        self.sld_star_lon.setToolTip("Longitude of the observer, east is positive (Paris 2.35, New York -74). Exact Sky only.")
        form_place.addRow("Longitude:", self.sld_star_lon)
        today = datetime.datetime.now(datetime.timezone.utc)
        row_date = QtWidgets.QHBoxLayout()
        self.spin_sky_year = QtWidgets.QSpinBox()
        self.spin_sky_year.setRange(1900, 2100)
        self.spin_sky_year.setValue(today.year)
        self.spin_sky_month = QtWidgets.QSpinBox()
        self.spin_sky_month.setRange(1, 12)
        self.spin_sky_month.setValue(today.month)
        self.spin_sky_day = QtWidgets.QSpinBox()
        self.spin_sky_day.setRange(1, 31)
        self.spin_sky_day.setValue(today.day)
        for spin, label in ((self.spin_sky_year, "Year"), (self.spin_sky_month, "Month"), (self.spin_sky_day, "Day")):
            spin.setToolTip(label)
            row_date.addWidget(spin)
        form_place.addRow("Date:", row_date)
        self.sld_sky_hour = FloatSlider(0.0, 24.0, 21.0, decimals=2)
        self.sld_sky_hour.setToolTip("Time of the day in UT (Greenwich), in hours: 21.5 is 21:30. Local time is UT plus the longitude divided by 15.")
        form_place.addRow("Time (UT h):", self.sld_sky_hour)
        self.lbl_exact_info = QtWidgets.QLabel("")
        self.lbl_exact_info.setWordWrap(True)
        self.lbl_exact_info.setTextFormat(QtCore.Qt.PlainText)
        self.lbl_exact_info.setStyleSheet("color: {};".format(_C["text_muted"]))
        form_place.addRow(self.lbl_exact_info)
        form_sky.addRow(self.fold_place)

        lay_sky.addWidget(fold_sky)

        fold_sun = FoldGroup("Sun")
        form_sun = fold_sun.form
        self.fold_sun = fold_sun

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

        form_sun.addRow("Solar Altitude:", self.sld_sky_elev)
        form_sun.addRow("Solar Direction:", self.sld_sky_azim)
        self.chk_sky_follow_view = QtWidgets.QCheckBox("Follow the viewport heading")
        self.chk_sky_follow_view.setToolTip(
            "Off: the sun sits at the Solar Direction shown by the compass.\n"
            "On: the Y rotation of the active Scene Viewer is added, so the sun turns with the view.")
        form_sun.addRow("Align to View:", self.chk_sky_follow_view)
        form_sun.addRow(lay_azim_compass)   # spans both columns: it must not add to the width of the labels

        self.sld_sun_int = FloatSlider(0.0, 50.0, 1.0)
        self.sld_sun_size = FloatSlider(0.01, 10.0, 0.53)
        form_sun.addRow("Sun Intensity:", self.sld_sun_int)
        form_sun.addRow("Angular Size:", self.sld_sun_size)

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

        form_sun.addRow("Sun Temp. (K):", lay_sun_temp)
        lay_sky.addWidget(fold_sun)

        fold_air = FoldGroup("Atmosphere")
        form_air = fold_air.form
        self.fold_air = fold_air

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
        form_air.addRow(w_amb_label, lay_rgb_amb)

        def _update_amb_swatch(*_):
            self.swatch_amb.set_rgb(self.sp_amb_r.value(), self.sp_amb_g.value(), self.sp_amb_b.value())
        for slider in (self.sp_amb_r, self.sp_amb_g, self.sp_amb_b):
            slider.valueChanged.connect(_update_amb_swatch)
        _update_amb_swatch()

        self.sld_turbidity = FloatSlider(1.0, 10.0, 3.0)
        self.sld_sky_int = FloatSlider(0.0, 30.0, 1.0)
        self.sld_turbidity.setToolTip("Haze of the Basic Projection (classic) sky.")
        form_air.addRow("Turbidity:", self.sld_turbidity)
        form_air.addRow("Sky Intensity:", self.sld_sky_int)
        self.sld_hz_blur = FloatSlider(0.0, 45.0, 5.0)
        self.sld_hz_blur.setToolTip("Horizon blur of the Basic Projection (classic) sky.")
        form_air.addRow("Horizon Blur:", self.sld_hz_blur)

        self.sld_atm_rayleigh = FloatSlider(0.0, 5.0, 1.0)
        self.sld_atm_mie = FloatSlider(0.0, 5.0, 1.0)
        self.sld_atm_rayleigh.setToolTip("Rayleigh scattering: the blue of the volumetric atmosphere.")
        form_air.addRow("Rayleigh:", self.sld_atm_rayleigh)
        self.sld_atm_mie.setToolTip("Mie scattering: the haze of the volumetric atmosphere.")
        form_air.addRow("Mie:", self.sld_atm_mie)
        lay_sky.addWidget(fold_air)

        layout_lights.addWidget(self.grp_sky)
        layout_lights.addStretch(1)
        tabs.addTab(wrap_tab(tab_lights), "Lighting")
        self._config_tabs.append(tab_lights)

        for widget in (self.spin_sky_year, self.spin_sky_month, self.spin_sky_day):
            widget.valueChanged.connect(self._update_exact_info)
        for widget in (self.sld_sky_hour, self.sld_star_lon, self.sld_star_lat):
            widget.valueChanged.connect(self._update_exact_info)
        self.chk_exact.toggled.connect(self._update_exact_info)
        self.chk_exact.toggled.connect(self.fold_place.set_opened)

    # ------------------------------------------------------------
    # The moon, the stars and the Milky Way, in a tab of their own: the sky of the day has nothing to do with them. Only for the
    # physical sky (the tab is greyed otherwise, see update_environment_tab).
    def _build_night_sky_tab(self, tabs):
        tab_night = QtWidgets.QWidget()
        layout_night = QtWidgets.QVBoxLayout(tab_night)

        self.lbl_night_exact = QtWidgets.QLabel("Exact Sky is on (Lighting tab): the moon phase and the star time come from the date, they are greyed here.")
        self.lbl_night_exact.setWordWrap(True)
        self.lbl_night_exact.setStyleSheet("color: {};".format(_C["text_muted"]))
        layout_night.addWidget(self.lbl_night_exact)

        fold_moon = FoldGroup("Moon")
        form_moon = fold_moon.form
        self.chk_moon = QtWidgets.QCheckBox("Moon")
        self.chk_moon.setChecked(True)
        self.chk_moon.setToolTip("The moon: a lit ball with a halo, placed from the sun and the phase. It follows an inclined path of its own as Solar Altitude, "
                                 "Solar Direction, Latitude and Star Time change, and it is only built while it is above the horizon.")
        form_moon.addRow(self.chk_moon)
        self.sld_moon_phase = FloatSlider(0.0, 1.0, 0.5, decimals=2)
        self.sld_moon_phase.setToolTip("0 new moon, 0.25 first quarter, 0.5 full moon, 0.75 last quarter. The phase is where the moon stands compared "
                                       "with the sun: a full moon rises when the sun sets, a crescent follows the sun.")
        form_moon.addRow("Moon Phase:", self.sld_moon_phase)
        self.sld_moon_halo = FloatSlider(0.0, 3.0, 1.0)
        self.sld_moon_halo.setToolTip("Strength of the halo round the moon.")
        form_moon.addRow("Moon Halo:", self.sld_moon_halo)
        self.sld_moon_int = FloatSlider(0.0, 5.0, 1.0)
        self.sld_moon_int.setToolTip("Brightness of the moon and of its light.")
        form_moon.addRow("Moon Intensity:", self.sld_moon_int)
        self.sld_moon_size = FloatSlider(0.3, 10.0, 2.0)
        self.sld_moon_size.setToolTip("Angular size in degrees. The real moon is 0.5, a bigger one reads better in a wide shot.")
        form_moon.addRow("Moon Size:", self.sld_moon_size)
        for widget in (self.sld_moon_halo, self.sld_moon_int, self.sld_moon_size):
            self.chk_moon.toggled.connect(widget.setEnabled)
        # bug trouvé et fixé: setEnabled(checked) woke the phase while the exact sky decides it, and the exact sky woke it with the moon off;
        # both conditions are in one place
        self.chk_moon.toggled.connect(self._update_exact_info)
        layout_night.addWidget(fold_moon)

        fold_stars = FoldGroup("Stars")
        form_stars = fold_stars.form
        self.chk_stars = QtWidgets.QCheckBox("Stars at Night")
        self.chk_stars.setChecked(True)
        self.chk_stars.setToolTip("The star catalogue as points (colour, size and halo from the magnitude, a twinkle of their own), sharp at any resolution. "
                                  "They show when the sun is below -3 degrees and replace the sky at -12; nothing is built before. "
                                  "Needs datas/Sky (stars.npz) beside the tool or in the Houdini preferences.")
        form_stars.addRow(self.chk_stars)
        self.chk_milky = QtWidgets.QCheckBox("Milky Way")
        self.chk_milky.setChecked(True)
        self.chk_milky.setToolTip("The Milky Way (NASA/Gaia map, datas/Sky/milky_way_1k.exr) behind the stars. A soft picture: it is the one part that is not points.")
        form_stars.addRow(self.chk_milky)
        self.sld_stars_int = FloatSlider(0.0, 5.0, 1.0)
        self.sld_stars_int.setToolTip("Brightness of the stars and of the Milky Way.")
        form_stars.addRow("Star Brightness:", self.sld_stars_int)
        self.sld_stars_size = FloatSlider(0.3, 4.0, 1.0)
        self.sld_stars_size.setToolTip("Size of the stars: 1 is a pin point for the faint ones and a small dot for Sirius.")
        form_stars.addRow("Star Size:", self.sld_stars_size)
        self.sld_stars_twinkle = FloatSlider(0.0, 2.0, 1.0, decimals=2)
        self.sld_stars_twinkle.setToolTip("How much the stars flicker with the time (play the timeline or render an animation). It grows towards the horizon, as in the sky.")
        form_stars.addRow("Twinkle:", self.sld_stars_twinkle)
        self.sld_stars_glow = FloatSlider(0.0, 3.0, 1.0)
        self.sld_stars_glow.setToolTip("Strength of the halo round the bright stars.")
        form_stars.addRow("Star Glow:", self.sld_stars_glow)
        self.sld_star_time = FloatSlider(0.0, 24.0, 0.0, decimals=1)
        self.sld_star_time.setToolTip("Hours: turns the stars round the celestial pole (15 degrees an hour). The latitude is in the Lighting tab (Place and Date).")
        form_stars.addRow("Star Time (h):", self.sld_star_time)
        for widget in (self.chk_milky, self.sld_stars_int, self.sld_stars_size, self.sld_stars_twinkle, self.sld_stars_glow):
            self.chk_stars.toggled.connect(widget.setEnabled)
        layout_night.addWidget(fold_stars)

        fold_render = FoldGroup("Rendering")
        form_render = fold_render.form
        self.chk_sky_plate = QtWidgets.QCheckBox("Composite the sky layers after the render")
        self.chk_sky_plate.setToolTip("No geometry in the scene: the moon, the stars, the Milky Way and the 2D clouds are drawn for the render camera at its resolution "
                                      "and composed under the render in a Copernicus network (/obj/karma_sky_comp, the picture is written beside the render, with _sky "
                                      "before the extension). Sharp at any resolution. Only Render to Disk makes it: the Karma viewport does not show these layers.")
        form_render.addRow(self.chk_sky_plate)
        lbl_plate_hint = QtWidgets.QLabel("Moon, stars, Milky Way and 2D clouds are drawn at the render resolution and composed in Copernicus. "
                                          "Only Render to Disk makes it: the Karma viewport does not show them.")
        lbl_plate_hint.setWordWrap(True)
        lbl_plate_hint.setStyleSheet("color: {};".format(_C["text_muted"]))
        form_render.addRow(lbl_plate_hint)
        layout_night.addWidget(fold_render)

        layout_night.addStretch(1)
        self.tabs_main = tabs
        self.tab_night_scroll = wrap_tab(tab_night)
        tabs.addTab(self.tab_night_scroll, "Night Sky")
        self._config_tabs.append(tab_night)
        self._update_exact_info()

    # ------------------------------------------------------------
    # With the exact sky on, the sun, the moon and the sidereal time come from the date: their sliders are put aside and a line
    # says where everything is.
    def _update_exact_info(self, *_):
        exact = self.chk_exact.isChecked()
        for widget in (self.sld_sky_elev, self.sld_sky_azim, self.sld_star_time):
            widget.setEnabled(not exact)
        self.sld_moon_phase.setEnabled(not exact and self.chk_moon.isChecked())
        for widget in (self.spin_sky_year, self.spin_sky_month, self.spin_sky_day, self.sld_sky_hour, self.sld_star_lon):
            widget.setEnabled(exact)
        self.lbl_night_exact.setVisible(exact)
        if not exact:
            self.lbl_exact_info.setText("")
            return
        try:
            snap = sky_snapshot(self.spin_sky_year.value(), self.spin_sky_month.value(), self.spin_sky_day.value(), self.sld_sky_hour.value(),
                                self.sld_star_lat.value(), self.sld_star_lon.value())
        except (ValueError, ZeroDivisionError) as exc:
            self.lbl_exact_info.setText("This date cannot be computed: {}".format(exc))
            return
        sun, moon = snap["sun"], snap["moon"]
        elongation = math.degrees(math.acos(max(-1.0, min(1.0, math.sin(sun["dec"]) * math.sin(moon["dec"]) + math.cos(sun["dec"]) * math.cos(moon["dec"]) * math.cos(sun["ra"] - moon["ra"])))))
        lit = (1.0 - math.cos(math.radians(elongation))) / 2.0
        planets = ", ".join("{} {:+.1f}".format(p[0], p[3]) for p in snap["planets"])
        self.lbl_exact_info.setText("Sun: altitude {:.1f}, azimuth {:.0f}. Moon: altitude {:.1f}, azimuth {:.0f}, {:.0f}% lit. Sidereal time {:.2f} h. "
                                    "Planets (magnitude): {}.".format(sun["altitude"], sun["azimuth"], moon["altitude"], moon["azimuth"], lit * 100.0, snap["lst"], planets))

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
        start = os.path.dirname(self.line_hdri_path.text().strip()) or _datas_folder() or "$HIP"
        path = hou.ui.selectFile(start_directory=start, title="Select HDRI", pattern="*.exr *.hdr *.rat", chooser_mode=hou.fileChooserMode.Read)
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
        if hasattr(self, "lbl_disk_sky"):   # the Output tab is built after this one
            self._update_disk_sky_note()
        index = self.tabs_main.indexOf(self.tab_night_scroll)
        self.tabs_main.setTabEnabled(index, is_physical)
        self.tabs_main.setTabToolTip(index, "" if is_physical else "Moon and stars need the Environment mode with a Physical Sky.")

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
        self._hdri_preview_base = None
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
    # Preview of the HDRI sliders, same colour math as the dome light. The preview is already toned down, so exposure is applied in linear light on it.
    # Unchanged at the default settings.
    # TODO: the direction of the rotation is not checked against a Karma render
    @_guarded_slot
    def _refresh_hdri_look(self):
        base = getattr(self, "_hdri_preview_base", None)
        if base is None:
            return
        image = base
        try:
            import numpy as np
            rgb = base.convertToFormat(QtGui.QImage.Format_RGB888)
            width, height = rgb.width(), rgb.height()
            raw = np.frombuffer(rgb.constBits(), dtype=np.uint8, count=rgb.bytesPerLine() * height)
            pixels = raw.reshape(height, rgb.bytesPerLine())[:, :width * 3].reshape(height, width, 3).astype(np.float32) / 255.0
            neutral = _kelvin_to_rgb(6500.0)
            temp = _kelvin_to_rgb(float(self.spin_hdri_temp.value()))
            color = _apply_saturation(_apply_tint(temp, self.sld_hdri_tint.value()), self.sld_hdri_sat.value())
            gain = np.array([c / max(n, 1e-4) for c, n in zip(color, _apply_saturation(neutral, 1.0))], dtype=np.float32)
            linear = np.power(pixels, 2.2) * gain * (2.0 ** self.sld_hdri_ev.value())
            shifted = np.roll(linear, -int(round(self.sld_hdri_rot.value() / 360.0 * width)), axis=1)
            out = (np.power(np.clip(shifted, 0.0, 1.0), 1.0 / 2.2) * 255.0 + 0.5).astype(np.uint8)
            image = QtGui.QImage(out.tobytes(), width, height, width * 3, QtGui.QImage.Format_RGB888).copy()
        except Exception as exc:   # no numpy or an odd picture: the preview stays as loaded
            _debug("HDRI preview look: {}".format(exc))
        self.lbl_hdri_preview.set_picture(image)

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
        self._hdri_preview_base = image
        self._refresh_hdri_look()
