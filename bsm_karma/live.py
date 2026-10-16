# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Live update: rebuild when a value changes
# Houdini : 21 and 22 (PySide6 only, no hou calls)
# Version : 1.0.0

from hutil.Qt import QtWidgets
from .config import LIVE_STRUCTURE_KEYS
from .debuglog import _debug, _guarded_slot
from .gauges import GaugeBar


# ------------------------------------------------------------
LIVE_STRUCTURE_LABELS = {
    "scene_mode": "Scene Mode", "env_type": "Environment", "sky_mode": "Sky Rendering", "enable_fog": "Fog",
    "enable_clouds": "Clouds", "cloud_type": "Cloud Type", "enable_aovs": "AOVs", "engine": "Engine", "camera_choice": "Camera",
    "geo_source": "Geometry Source", "cloud_material_path": "Cloud Material Path",
}


# ------------------------------------------------------------
def _structure_of(config):
    return {key: config.get(key) for key in LIVE_STRUCTURE_KEYS}

# ------------------------------------------------------------
class LiveUpdateMixin:

    # ------------------------------------------------------------------------
    # Live update. Off: nothing happens until Build is pressed (slow machines). On: a change of any value
    # rebuilds the network after a short pause, so a slider can be dragged without a build per step.
    LIVE_UPDATE_DELAY_MS = 350

    # ------------------------------------------------------------
    def _connect_live_update(self, pages):
        skipped = {self.chk_live_update, self.combo_viewport_engine, self.chk_snapshot_safe,
                   self.combo_snapshot_safe_type, self.chk_snapshot_compare}
        trigger = self._schedule_live_update
        for page in pages:
            for widget in page.findChildren(QtWidgets.QWidget):
                if widget in skipped:
                    continue
                if isinstance(widget, GaugeBar):
                    widget.valueChanged.connect(trigger)
                elif isinstance(widget, QtWidgets.QComboBox):
                    widget.currentIndexChanged.connect(trigger)
                elif isinstance(widget, QtWidgets.QCheckBox):
                    widget.toggled.connect(trigger)
                elif isinstance(widget, QtWidgets.QGroupBox) and widget.isCheckable():
                    widget.toggled.connect(trigger)
                elif isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                    widget.valueChanged.connect(trigger)
                elif isinstance(widget, QtWidgets.QLineEdit):
                    if not isinstance(widget.parent(), QtWidgets.QAbstractSpinBox):   # not the editor inside a spin box
                        self._connect_live_line_edit(widget)

    # ------------------------------------------------------------
    # A path is built when typing ends and only if the text was edited, not at every letter or focus change.
    def _connect_live_line_edit(self, edit):
        edited = {"flag": False}

        def mark(*_):
            edited["flag"] = True

        def finished():
            if edited["flag"]:
                edited["flag"] = False
                self._schedule_live_update()

        edit.textEdited.connect(mark)
        edit.editingFinished.connect(finished)

    # ------------------------------------------------------------
    def on_live_toggled(self, enabled):
        self._live_seen.clear()
        _debug("live update {}".format("on" if enabled else "off"))
        if enabled:
            self._schedule_live_update()
        else:
            self._live_timer.stop()
            self._set_build_hint("")

    # ------------------------------------------------------------
    def _schedule_live_update(self, *_):
        if self.chk_live_update.isChecked() and not self._released:
            self._live_timer.start(self.LIVE_UPDATE_DELAY_MS)

    # ------------------------------------------------------------
    # Only problems reach the Log tab, once each; the debug file keeps every message.
    def _live_log(self, message):
        text = message.strip()
        if text.startswith(("[WARN]", "[ERROR]")) and text not in self._live_seen:
            self._live_seen.add(text)
            self.log_message(message)
        else:
            _debug(message, "LOG")

    # ------------------------------------------------------------
    # What differs from the last Build in the settings that change the node structure ([] when nothing does).
    def _live_structure_changes(self):
        built = self._live_structure
        if built is None:
            return ["no Build yet"]
        now = _structure_of(self._collect_config())
        return [key for key in LIVE_STRUCTURE_KEYS if now[key] != built.get(key)]

    # ------------------------------------------------------------
    def _live_pause(self, reasons):
        if reasons == ["no Build yet"]:
            text = "[INFO] Live Update waits for a first Build: press Build Environment Only."
        else:
            text = ("[INFO] Live Update paused: {} changed. That adds or removes nodes, which can freeze a running "
                    "Karma viewport. Press Build Environment Only; Live Update then goes on.".format(
                ", ".join(LIVE_STRUCTURE_LABELS.get(key, key) for key in reasons)))
        if text not in self._live_seen:
            self._live_seen.add(text)
            self.log_message(text)
        self._set_build_hint("" if reasons == ["no Build yet"] else ", ".join(LIVE_STRUCTURE_LABELS.get(key, key) for key in reasons))
        _debug("live update paused: {}".format(reasons))

    # ------------------------------------------------------------
    @_guarded_slot
    def _live_build(self):
        if self._live_building or not self.chk_live_update.isChecked():
            return
        reasons = self._live_structure_changes()
        if reasons:
            self._live_pause(reasons)
            return
        self._set_build_hint("")
        self._live_building = True
        try:
            self._run_build(self._live_log, "BSM Karma - Live Update", live=True)
        finally:
            self._live_building = False
