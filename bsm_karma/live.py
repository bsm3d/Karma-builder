# live.py - BSM Karma Builder - live update: rebuild when a value changes
# Version : 2026.10.15.1 | Revision : 15-10-2026 | Auteur : BSM

from hutil.Qt import QtWidgets
from .debuglog import _debug, _guarded_slot
from .gauges import GaugeBar

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
    @_guarded_slot
    def _live_build(self):
        if self._live_building or not self.chk_live_update.isChecked():
            return
        self._live_building = True
        try:
            self._run_build(self._live_log, "BSM Karma - Live Update", live=True)
        finally:
            self._live_building = False
