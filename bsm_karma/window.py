# Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : The dialog: assembles the tabs, collects the settings, runs the build
# Houdini : 21 and 22
# Version : 1.0.0

import hou
import json
import os
import sys
from hutil.Qt import QtWidgets, QtCore, QtGui
from .build import setup_karma_environment
from .catalog import _CATALOG_WRAPPERS
from .buildinfo import build_summary, build_tag
from .config import FORM_LABEL_GAP, SCRIPT_VERSION
from .debuglog import _debug, _debug_session_header, _guarded_slot
from .live import LiveUpdateMixin, _structure_of
from .snapshots import SnapshotMixin
from .styles import BSM_STYLE, _C, _btn_style
from .tab_atmosphere import AtmosphereTab
from .tab_export import ExportTab
from .tab_lighting import LightingTab
from .tab_log import LogTab
from .tab_materials import MaterialsTab
from .tab_passes import PassesTab
from .tab_render import RenderTab
from .tab_scene import SceneTab
from .tab_shader import ShaderTab
from .util import _normalized_path
from .widgets import inside, space_layouts
from .viewport import ViewportMixin


# presets.json can be edited by hand: an entry with a missing or non numeric value is left out, with a note
def _valid_presets(entries, required, kind, notes):
    valid = {}
    for name, entry in (entries.items() if isinstance(entries, dict) else ()):
        numbers = isinstance(entry, dict) and all(
            isinstance(entry.get(key), (int, float)) and not isinstance(entry.get(key), bool) for key in required)
        if numbers:
            valid[name] = entry
        else:
            notes.append("{} preset '{}' ignored: it needs numbers for {}".format(kind, name, ", ".join(required)))
    return valid


# --------------------------------------------------------
# bug trouvé et fixé: super(Classe, self) casse après importlib.reload (TypeError sur l'ancien dialogue),
# d'où super() sans argument partout :)
class KarmaBuilderUI(SceneTab, LightingTab, AtmosphereTab, MaterialsTab, ShaderTab, RenderTab, PassesTab, ExportTab, ViewportMixin,
                     SnapshotMixin, LogTab, LiveUpdateMixin, QtWidgets.QDialog):

    def __init__(self, parent=None):
        # Fix erreur = hou.qt.mainWindow() en argument par défaut était évalué à l'import, on le résout à l'appel
        if parent is None:
            parent = hou.qt.mainWindow()
        super().__init__(parent)
        self.setWindowTitle("Karma Builder {} ({})".format(SCRIPT_VERSION, build_tag()))
        self.resize(540, 600)
        self.setMinimumSize(440, 420)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        self.setStyleSheet(BSM_STYLE)
        # child of the main window: without this a closed dialog lives until Houdini exits
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

        _debug_session_header()
        self._released = False
        self._live_building = False
        self._live_structure = None
        self._live_seen = set()
        self._pending_logs = []
        self._amd_folder = None
        self._release_errors = []
        self._karma_scene_viewer = None
        self._parm_pane_tab = None
        self._material_source_changed = False
        self._mx_dialog = None
        self._snapshot_source_image = QtGui.QImage()
        self._snapshot_compare_image = QtGui.QImage()
        self._snapshot_slot_target = "A"
        self._last_snapshot_preview_size = QtCore.QSize()
        self._hdri_temp_files = []

        self.presets = {}
        self.sky_presets = {}
        self.fog_presets = {}
        self.cloud_presets = {}
        self._load_presets()
        
        self._sky_preset_names = ["-- Custom --"] + list(self.sky_presets.keys())
        
        main_layout = QtWidgets.QVBoxLayout()
        tabs = QtWidgets.QTabWidget()
        self._config_tabs = []
        self._build_scene_tab(tabs)
        self._build_lighting_tab(tabs)
        self._build_atmosphere_tab(tabs)
        self._build_materials_tab(tabs)
        self._build_shader_tab(tabs)
        self._build_render_tab(tabs)
        self._build_passes_tab(tabs)
        self._build_export_tab(tabs)
        self._build_log_tab(tabs)
        self._build_about_tab(tabs)
        
        main_layout.addWidget(tabs)
        
        self.btn_build = QtWidgets.QPushButton("Build Environment Only")
        self.btn_build.setStyleSheet(_btn_style(_C["amber"]))
        self.btn_build.clicked.connect(self.on_build)
        main_layout.addWidget(self.btn_build)
        
        self.setLayout(main_layout)
        
        self.combo_preset.setCurrentText("Mid (1080p / 256s)")
        self.apply_preset()
        self.combo_time_preset.setCurrentText("Clear Sky (Midday)")
        self.refresh_stage_cameras()
        self.toggle_frame_range()
        self.update_environment_tab()
        self.apply_aov_preset()
        self.update_aov_ui()
        self.update_output_format_ui()
        self._do_hdri_preview()
        
        self.atm_widget.update_fog(self.sld_fog_height.value(), self.sld_fog_density.value())
        self.atm_widget.update_cloud(self.sld_cloud_altitude.value(), self.sld_cloud_density.value())

        self.update_material_source_ui()
        self.refresh_geo_sources()
        for message in self._pending_logs:
            self.log_message("[WARN] {}".format(message))
        self._pending_logs.clear()

        self.combo_engine.currentTextChanged.connect(self._sync_viewport_engine_combo)
        self._set_snapshot_slot_target("A")
        self._update_snapshot_slots_ui()

        self._update_debug_path_label()
        self.log_message("[INFO] {}".format(build_summary(SCRIPT_VERSION)))

        # live update is wired last: the values set while the window is built must not trigger a build
        self._live_timer = QtCore.QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._live_build)
        self._connect_live_update(self._config_tabs)
        self.chk_live_update.toggled.connect(self.on_live_toggled)

        self._compact_combos()
        self._space_forms()
        space_layouts(self, skip=getattr(self, "mat_gallery", None))

    # ----------------------------------------
    def _close_pane_tab(self, pane_tab):
        if pane_tab is None:
            return
        try:
            panel = pane_tab.floatingPanel()
        except hou.Error:
            return  # already gone
        try:
            pane_tab.close()
        except hou.Error:
            pass
        if panel is not None:
            try:
                if not panel.paneTabs():
                    panel.close()
            except hou.Error:
                pass

    # ----------------------------------------------------------------
    # ATTENTION -> appelé depuis des surcharges Qt (done, closeEvent): une exception qui en sort plante Houdini,
    # donc chaque étape est isolée et les erreurs vont dans self._release_errors. Sans danger si appelé deux fois.
    def _release_resources(self):
        if self._released:
            return
        self._released = True
        self._release_errors = []

        def step(label, action):
            try:
                action()
            except Exception as exc:
                self._release_errors.append("{}: {}".format(label, exc))

        _debug("window closed")
        step("timer", self._hdri_preview_timer.stop)
        step("live timer", self._live_timer.stop)
        step("material edit", self._flush_shader_edit)

        step("viewport panel", lambda: self._close_pane_tab(self._karma_scene_viewer))
        step("parameter panel", lambda: self._close_pane_tab(self._parm_pane_tab))
        self._karma_scene_viewer = None
        self._parm_pane_tab = None

        step("viewport drop", self._viewport_drop.disarm)
        step("download window", self._close_downloader)
        step("catalog source", self._restore_material_source)
        step("snapshots", self._clear_snapshot_images)
        step("target list", lambda: self.tree_mat_targets.set_prims([], {}))
        step("temp files", self._remove_temp_files)

    # ------------------------------------------------------------
    def _close_downloader(self):
        dialog, self._mx_dialog = self._mx_dialog, None
        if dialog is not None:
            dialog.close()

    # ------------------------------------------------------------
    def _remove_temp_files(self):
        for tmp_file in self._hdri_temp_files:
            _CATALOG_WRAPPERS.pop(_normalized_path(tmp_file), None)
            try:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except OSError:
                pass
        self._hdri_temp_files.clear()

    # ------------------------------------------------------------------------
    def done(self, result):
        self._release_resources()
        super().done(result)

    # ------------------------------------------------------------
    def closeEvent(self, event):
        self._release_resources()
        super().closeEvent(event)

    # ------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "lbl_snapshot_preview"):
            return
        if not self._snapshot_any_image():
            return

        cur_size = self.lbl_snapshot_preview.size()
        if cur_size == self._last_snapshot_preview_size:
            return
        self._last_snapshot_preview_size = cur_size
        self._update_snapshot_preview()

    # --------------------------------------------------------
    # Presets: the text embedded in the HDA, else presets.json next to the code, else a minimal set.
    def _load_presets(self):
        try:
            data = None
            embedded = sys.modules[__package__].__dict__.get("EMBEDDED_PRESETS")
            if embedded:
                data = json.loads(embedded)
            else:
                preset_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets.json")
                if os.path.isfile(preset_file):
                    with open(preset_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
            if data is not None:
                notes = self._pending_logs
                self.presets = _valid_presets(data.get("render_qualities", {}), ("rx", "ry", "spl"), "quality", notes)
                self.sky_presets = _valid_presets(data.get("sky_presets", {}), ("elv", "s_int", "turb", "sk_int", "hz"), "sky", notes)
                self.fog_presets = _valid_presets(data.get("fog_presets", {}), ("dens", "h", "rad", "phase"), "fog", notes)
                self.cloud_presets = _valid_presets(data.get("cloud_presets", {}), ("dens", "alt", "scale"), "cloud", notes)
                return
        except (OSError, ValueError, AttributeError) as e:
            self._pending_logs.append("Failed to load the presets: {}".format(e))

        self.presets = {"Mid (1080p / 256s)": {"rx": 1920, "ry": 1080, "spl": 256}}
        self.sky_presets = {"Clear Sky (Midday)": {"elv": 60.0, "s_int": 3.0, "turb": 2.8, "sk_int": 2.0, "hz": 2.0, "sun_t": 5500, "amb_r": 1.0, "amb_g": 1.0, "amb_b": 1.0, "atm_r": 1.0, "atm_m": 0.5}}
        self.fog_presets = {"Light Mist": {"dens": 0.05, "h": 20.0, "rad": 150.0, "phase": 0.2, "ns": 0.1, "na": 0.2}}
        self.cloud_presets = {"Low Cumulus": {"dens": 0.20, "alt": 80.0, "scale": 150.0, "div": 5, "clip": 0.45}}

    # ------------------------------------------------------------
    def _set_form_field_visible(self, form_layout, field, visible):
        try:
            form_layout.setRowVisible(field, visible)
            return
        except AttributeError:
            pass  # Qt before 6.4

        label = form_layout.labelForField(field)
        if label is not None:
            label.setVisible(visible)
        field.setVisible(visible)

    # --------------------------------------------------------
    def _collect_config(self):
        # opt-in: the heading of the active viewer is added to the sun direction
        view_y_rot = 0.0
        if self.chk_sky_follow_view.isChecked():
            try:
                viewer = self._get_active_scene_viewer()
                if viewer is not None:
                    view_y_rot = viewer.curViewport().viewTransform().extractRotates()[1]
            except (hou.Error, AttributeError):
                pass
            
        is_env_mode = (self.combo_scene_mode.currentText() == "Environment")
        return {
            "scene_mode": self.combo_scene_mode.currentText(),
            "env_type": self.combo_env_type.currentText(),
            "engine": self.combo_engine.currentText(),
            "res_x": self.spin_resX.value(),
            "res_y": self.spin_resY.value(),
            "samples": self.sld_samples.value(),
            "camera_choice": self._current_camera_choice(),
            "new_cam_focal": self.spin_cam_focal.value(),
            "new_cam_from_viewport": self.chk_cam_from_viewport.isChecked(),
            "viewport_matrix": self._viewport_matrix() if self.chk_cam_from_viewport.isChecked() else None,
            
            "area_int": self.sld_area_int.value(),
            "hdri_int": self.sld_hdri_int.value(),
            "hdri_path": self.line_hdri_path.text().strip() or "$HIP/hdri/overcast_sky.exr",
            "hdri_ev": self.sld_hdri_ev.value(),
            "hdri_rot": self.sld_hdri_rot.value(),
            "hdri_sat": self.sld_hdri_sat.value(),
            "hdri_temp": self.spin_hdri_temp.value(),
            "hdri_tint": self.sld_hdri_tint.value(),
            "lamp_key_temp": self.spin_lamp_key_temp.value(),
            "lamp_key_tint": self.sld_lamp_key_tint.value(),
            "lamp_fill_temp": self.spin_lamp_fill_temp.value(),
            "lamp_fill_tint": self.sld_lamp_fill_tint.value(),
            "lamp_rim_temp": self.spin_lamp_rim_temp.value(),
            "lamp_rim_tint": self.sld_lamp_rim_tint.value(),
            "enable_fog": is_env_mode and self.chk_enable_fog.isChecked(),
            "fog_density": self.sld_fog_density.value(),
            "fog_height": self.sld_fog_height.value(),
            "fog_radius": self.sld_fog_radius.value(),
            "fog_phase": self.sld_fog_phase.value(),
            "fog_noise_scale": self.sld_fog_noise_scale.value(),
            "fog_noise_amp": self.sld_fog_noise_amp.value(),
            "enable_clouds": is_env_mode and self.chk_enable_clouds.isChecked(),
            "cloud_density": self.sld_cloud_density.value(),
            "cloud_altitude": self.sld_cloud_altitude.value(),
            "cloud_scale": self.sld_cloud_scale.value(),
            "cloud_precision": self.sld_cloud_precision.value(),
            "cloud_clip": self.sld_cloud_clip.value(),
            "cloud_material_path": self.line_cloud_mat.text().strip(),
            "cloud_type": self.combo_cloud_type.currentIndex(),
            "cloud2d_coverage": self.sld_cloud2d_coverage.value(),
            "cloud2d_softness": self.sld_cloud2d_softness.value(),
            "cloud2d_scale": self.sld_cloud2d_scale.value(),
            "cloud2d_brightness": self.sld_cloud2d_brightness.value(),
            "cloud2d_seed": self.sld_cloud2d_seed.value(),
            "cloud2d_drift": self.sld_cloud2d_drift.value(),
            "cloud_wind_speed": self.sld_cloud_wind.value(),
            "cloud_wind_dir": self.sld_cloud_wind_dir.value(),
            "geo_source": self._current_geo_source(),

            "sky_mode": self.combo_sky_mode.currentIndex(),
            "sky_elev": self.sld_sky_elev.value(),
            "sky_azim": (self.sld_sky_azim.value() + view_y_rot) % 360.0,
            "sky_sun_int": self.sld_sun_int.value(),
            "sky_sun_size": self.sld_sun_size.value(),
            "sky_sun_temp": self.spin_sun_temp.value(),
            "sky_amb_r": self.sp_amb_r.value(),
            "sky_amb_g": self.sp_amb_g.value(),
            "sky_amb_b": self.sp_amb_b.value(),
            "sky_turbidity": self.sld_turbidity.value(),
            "sky_int": self.sld_sky_int.value(),
            "sky_hz_blur": self.sld_hz_blur.value(),
            "sky_atm_rayleigh": self.sld_atm_rayleigh.value(),
            "sky_atm_mie": self.sld_atm_mie.value(),
            
            "denoiser": self.combo_denoiser.currentText(),
            "pixel_filter": self.combo_pixel_filter.currentText(),
            "enable_ao": self.chk_ao.isChecked(),
            "aov_ao": self.chk_ao.isChecked(),
            "aov_depth": self.chk_aov_depth.isChecked(),
            "aov_normal": self.chk_aov_normal.isChecked(),
            "aov_position": self.chk_aov_position.isChecked(),
            "aov_albedo": self.chk_aov_albedo.isChecked(),
            "aov_emission": self.chk_aov_emission.isChecked(),
            "aov_diffuse": self.chk_aov_diffuse.isChecked(),
            "aov_specular": self.chk_aov_specular.isChecked(),
            "aov_motion": self.chk_aov_motion.isChecked(),
            "aov_shadow": self.chk_aov_shadow.isChecked(),
            "aov_id": self.chk_aov_id.isChecked(),
            "aov_multilayer": self.chk_aov_multilayer.isChecked(),
            "aov_half_precision": self.chk_aov_half_precision.isChecked(),
            "diffuse_limit": self.sld_diffuse_limit.value(),
            "reflection_limit": self.sld_reflection_limit.value(),
            "transmission_limit": self.sld_transmission_limit.value(),
            
            "volume_limit": self.sld_vol_limit.value(),
            "color_limit": self.sld_color_limit.value(),
            "noise_level": self.sld_noise_level.value(),
            
            "enable_aovs": self.chk_aovs.isChecked(),
            "output_format": self.combo_output_format.currentText(),
            "exr_precision": self.combo_exr_precision.currentText(),
            "trange": 1 if self.combo_trange.currentText() == "Frame Range" else 0,
            "f_start": self.spin_fStart.value(),
            "f_end": self.spin_fEnd.value(),
            "out_path": self.line_out.text().strip() or "$HIP/render/beauty/frame_$F4.exr"
        }

    # ------------------------------------------------------------------------
    def _run_build(self, log, undo_name, live=False):
        self.sync_output_extension()
        config = self._collect_config()
        config["live"] = live
        _debug("build settings: " + json.dumps(config, sort_keys=True, default=str))
        try:
            with hou.undos.group(undo_name):
                setup_karma_environment(config, log)
        except hou.Error as exc:
            log("[ERROR] Build stopped: {}".format(exc))
            return False
        self._live_structure = _structure_of(config)
        self._set_build_hint("")
        return True

    # ------------------------------------------------------------
    def _set_build_hint(self, changed_labels):
        if changed_labels:
            self.btn_build.setText("Build to apply: {}".format(changed_labels))
            self.btn_build.setToolTip("Live Update does not add or remove nodes by itself. Press to apply the change.")
        else:
            self.btn_build.setText("Build Environment Only")
            self.btn_build.setToolTip("")

    # ------------------------------------------------------------------------
    @_guarded_slot
    def on_build(self):
        self._live_seen.clear()
        if not self._run_build(self.log_message, "Karma Builder - Build"):
            return False
        self.refresh_stage_cameras()
        self.refresh_material_targets()
        return True

    # ------------------------------------------------------------
    def _space_forms(self):
        for form in self.findChildren(QtWidgets.QFormLayout):
            form.setHorizontalSpacing(FORM_LABEL_GAP)

    # ------------------------------------------------------------
    # A combo box asks for the width of its longest item, which sets the width of a whole tab. Give it a short
    # minimum instead and let the popup be as wide as its longest entry.
    def _compact_combos(self):
        for combo in self.findChildren(QtWidgets.QComboBox):
            if inside(combo, getattr(self, "mat_gallery", None)):
                continue   # Houdini's own gallery keeps its own combo boxes
            combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(9)
            combo.setMinimumWidth(104)
            if combo.count():
                combo.view().setMinimumWidth(combo.view().sizeHintForColumn(0) + 28)
        # the camera row also holds two buttons: its combo gives way first (the text is elided)
        self.combo_camera.setMinimumWidth(70)
