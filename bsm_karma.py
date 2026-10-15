# ************************************************************
# bsm_karma.py - BSM Karma Builder
# Karma environment builder for Houdini 21 and 22 (LOPs): lights, sky, fog, clouds, AOVs, render settings,
# plus a MaterialX browser with drag and drop assignment.
# Version : 2026.10.10.5 | Revision : 10-10-2026 | Auteur : BSM
# ************************************************************

import atexit
import functools
import os
import platform
import re
import hashlib
import sys
import tempfile
import shutil
import subprocess
import traceback
import uuid
import math
import hou
import datetime
import json
from hutil.Qt import QtWidgets, QtCore, QtGui

SCRIPT_VERSION = "2026.10.10.5"


# ============================================
# DEBUG LOG
# ============================================
# Everything the tool does goes to a text file: the log messages, the build configuration, the parameters that were
# not found, the node graph after a build and the traceback of any error. Send that file when something fails.
# Folder: the one holding bsm_karma.py; for the HDA (no file on disk) or a read-only folder, the user preferences
# folder (bsm_karma/), else the temp folder. BSM_KARMA_DEBUG=0 in the environment starts with the log off.

DEBUG_LOG_NAME = "bsm_karma_debug.log"
DEBUG_LOG_MAX_BYTES = 1000000
_debug_state = {"enabled": os.environ.get("BSM_KARMA_DEBUG", "1") != "0", "path": None, "broken": False}


# ------------------------------------------------------------
def _debug_candidate_folders():
    folders = []
    source = globals().get("__file__") or ""
    if os.path.isfile(source):
        folders.append(os.path.dirname(os.path.abspath(source)))
    try:
        pref_dir = hou.text.expandString("$HOUDINI_USER_PREF_DIR")
        if pref_dir and not pref_dir.startswith("$"):
            folders.append(os.path.join(pref_dir, "bsm_karma"))
    except Exception:
        pass
    folders.append(os.path.join(tempfile.gettempdir(), "bsm_karma"))
    return folders


# ------------------------------------------------------------
# Path of the log file: the first folder that can be written to.
def debug_log_path():
    if _debug_state["path"] and os.path.isdir(os.path.dirname(_debug_state["path"])):
        return _debug_state["path"]
    for folder in _debug_candidate_folders():
        try:
            os.makedirs(folder, exist_ok=True)
            probe = os.path.join(folder, DEBUG_LOG_NAME)
            with open(probe, "a", encoding="utf-8"):
                pass
            _debug_state["path"] = probe
            return probe
        except OSError:
            continue
    return None


# ------------------------------------------------------------
# One backup is kept: bsm_karma_debug.log.1
def _debug_rotate(path):
    try:
        if os.path.getsize(path) > DEBUG_LOG_MAX_BYTES:
            os.replace(path, path + ".1")
    except OSError:
        pass


# ------------------------------------------------------------
# Never raises: a log that cannot be written must not break the tool.
def _debug(message, level="DEBUG"):
    if not _debug_state["enabled"] or _debug_state["broken"]:
        return
    try:
        path = debug_log_path()
        if path is None:
            _debug_state["broken"] = True
            return
        _debug_rotate(path)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with open(path, "a", encoding="utf-8", errors="replace") as handle:
            handle.write("{} [{}] {}\n".format(stamp, level, message))
    except Exception:
        _debug_state["broken"] = True


# ------------------------------------------------------------
def _debug_exception(where):
    _debug("exception in {}:\n{}".format(where, traceback.format_exc().rstrip()), "ERROR")


# ------------------------------------------------------------
def _debug_node_label(node):
    try:
        return "{} ({})".format(node.path(), node.type().nameWithCategory())
    except Exception:
        return "<node gone>"


# ------------------------------------------------------------
def _debug_session_header():
    try:
        houdini = "{} ({})".format(hou.applicationVersionString(), hou.applicationName())
    except Exception:
        houdini = "unknown"
    try:
        binding = QtCore.__name__.split(".")[0]
        qt_version = QtCore.qVersion()
    except Exception:
        binding, qt_version = "unknown", "unknown"
    _debug("=" * 72, "SESSION")
    _debug("BSM Karma Builder {} | Houdini {}".format(SCRIPT_VERSION, houdini), "SESSION")
    _debug("Python {} | {} (Qt {}) | {}".format(
        sys.version.split()[0], binding, qt_version, platform.platform()), "SESSION")
    _debug("script: {}".format(globals().get("__file__") or "<embedded>"), "SESSION")
    _debug("hip file: {}".format(hou.hipFile.path()), "SESSION")


# ------------------------------------------------------------
# The node graph of /stage: what the next build found or left behind.
def _debug_stage_dump(stage):
    if not _debug_state["enabled"] or stage is None:
        return
    try:
        lines = []
        for node in sorted(stage.children(), key=lambda n: n.name()):
            sources = ", ".join(n.name() if n is not None else "-" for n in node.inputs()) or "-"
            tagged = "tool" if _is_tool_node_candidate(node, node.name()) else "user"
            lines.append("  {:<26} {:<34} <- {:<34} [{}]".format(
                node.name(), node.type().nameWithCategory(), sources, tagged))
        _debug("/stage after the build:\n" + "\n".join(lines))
    except Exception:
        _debug_exception("_debug_stage_dump")


# ------------------------------------------------------------
# For the buttons: an error inside a slot is written to the log (with its traceback) and shown in the Log tab,
# instead of surfacing as a raw traceback of the Houdini console. The signal arguments are trimmed to what the
# slot accepts, a decorated method can still be connected to clicked(bool).
def _guarded_slot(func):
    takes_all = bool(func.__code__.co_flags & 0x04)
    accepted = max(0, func.__code__.co_argcount - 1)

    @functools.wraps(func)
    def wrapper(self, *args):
        try:
            return func(self, *(args if takes_all else args[:accepted]))
        except Exception as exc:
            _debug_exception(func.__name__)
            traceback.print_exc()
            try:
                self.log_message("[ERROR] {} failed: {}: {} (details in the debug log)".format(
                    func.__name__, type(exc).__name__, exc))
            except Exception:
                pass
            return None
    return wrapper


# ============================================
# STYLES
# ============================================

_C = {
    "bg":          "#1e1e1e",
    "surface":     "#2b2b2b",
    "border":      "#3f3f3f",
    "text":        "#cccccc",
    "text_muted":  "#888888",
    "text_log":    "#a9b7c6",
    "accent_blue": "#2b4c7e",
    "accent_teal": "#325a70",
    "accent_green":"#2b4c3b",
    "accent_brown":"#4b3621",
    "danger":      "#7a3232",
    "primary":     "#3e5a78",
}

BSM_STYLE = f"""
/* Utilisation du thème natif de Houdini, on ne style que l'agencement et quelques éléments isolés. */
QTabBar::tab {{
    padding: 5px 12px;
}}
QGroupBox {{
    font-weight: bold;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 4px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QTextEdit {{
    background-color: {_C['surface']};
    color: {_C['text_log']};
    font-family: monospace;
}}
#hdriPreview, #snapshotPreview {{
    background-color: #1f1f1f;
    border: 1px solid #3f3f3f;
}}
"""


# ------------------------------------------------------------
# A full rule with a border: with only a background-color, the Houdini 22 theme draws no button, just the text.
def _btn_style(bg):
    base = QtGui.QColor(bg)
    return (
        "QPushButton {{ background-color: {bg}; color: white; font-weight: bold; padding: 10px;"
        " border: 1px solid {edge}; border-radius: 4px; }}"
        "QPushButton:hover {{ background-color: {hover}; }}"
        "QPushButton:pressed {{ background-color: {pressed}; }}"
        "QPushButton:disabled {{ background-color: #3a3a3a; color: #7a7a7a; border-color: #4a4a4a; }}"
    ).format(bg=bg, edge=base.lighter(160).name(), hover=base.lighter(125).name(), pressed=base.darker(125).name())

TOOL_NODE_TAG_KEY = "bsm_karma_managed"
TOOL_NODE_TAG_VALUE = "1"

TOOL_STAGE_NODE_TYPES = {
    "render_cam": {"camera"},
    "physical_sky": {"karmaphysicalsky"},
    "sky_atmosphere_linker": {"lightlinker"},
    "env_hdri": {"domelight"},
    "studio_hdri": {"domelight"},
    "fill_hdri": {"domelight"},
    "dome_light": {"domelight"},
    "studio_key": {"light"},
    "key_light": {"light"},
    "fill_light": {"light"},
    "rim_light": {"light"},
    "window_portal": {"light"},
    "atmosphere_fog": {"karmafogbox"},
    "cloud_geo": {"sopcreate"},
    "quickcloudmaterial": {"editmaterialproperties"},
    "env_merge": {"merge"},
    "mtlx_materials": {"materiallibrary"},
    "material_linker": {"materiallinker"},
    "geo_merge": {"merge"},
    "standard_aovs": {"karmastandardrendervars"},
    "karma_settings": {"karmarendersettings"},
    "render_to_disk": {"usdrender_rop"},
}

TOOL_STAGE_DELETE_ORDER = [
    "render_to_disk",
    "karma_settings",
    "standard_aovs",
    "material_linker",
    "mtlx_materials",
    "geo_merge",
    "env_merge",
    "atmosphere_fog",
    "cloud_geo",
    "window_portal",
    "rim_light",
    "fill_light",
    "key_light",
    "studio_key",
    "dome_light",
    "fill_hdri",
    "studio_hdri",
    "env_hdri",
    "sky_atmosphere_linker",
    "physical_sky",
    "render_cam",
]


# ============================================================
# CUSTOM WIDGETS
# ============================================================


# ------------------------------------------------------------
class ClickSlider(QtWidgets.QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)

    # --------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            if self.orientation() == QtCore.Qt.Horizontal:
                pos = event.pos().x()
                span = max(1, self.width() - 1)
            else:
                pos = event.pos().y()
                span = max(1, self.height() - 1)

            ratio = float(pos) / float(span)
            ratio = _clamp(ratio, 0.0, 1.0)

            if self.orientation() == QtCore.Qt.Vertical:
                ratio = 1.0 - ratio
            if self.invertedAppearance():
                ratio = 1.0 - ratio

            value = self.minimum() + (self.maximum() - self.minimum()) * ratio
            self.setValue(int(round(value)))
            event.accept()

        super().mousePressEvent(event)


# ----------------------------------------
def _slider_stylesheet():
    return (
        "QSlider::groove:horizontal {height: 10px; border-radius: 3px;}"
        "QSlider::handle:horizontal {width: 16px; margin: -6px 0; border-radius: 3px;}"
    )


#------------------------------------------------------------
class _SliderTickLabels(QtWidgets.QWidget):
    def __init__(self, tick_points=None, parent=None):
        super().__init__(parent)
        self.tick_points = tick_points or []
        self.setFixedHeight(18)
        

    # --------------------------------------------------
    def paintEvent(self, event):
        if not self.tick_points:
            return
        
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtGui.QColor(150, 150, 150))
        font = QtGui.QFont("Segoe UI", 8, QtGui.QFont.Bold)
        painter.setFont(font)
        
        min_val = self.tick_points[0][0]
        max_val = self.tick_points[-1][0]
        range_val = max(1e-5, max_val - min_val)
        
        for pos, label in self.tick_points:
            ratio = (pos - min_val) / range_val
            x = int(ratio * (self.width() - 14)) + 7
            painter.drawText(x - 15, 0, 30, 18, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, str(label))
        painter.end()


# ------------------------------------------------------------
class SunCompassWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.azimuth = 0.0
        self.elevation = 30.0
        self.setFixedSize(140, 140)
        self.setStyleSheet("background-color: #2b2b2b; border: 1px solid #1a1a1a; border-radius: 4px;")
        


    # ------------------------------------------------------------------------
    def set_azimuth(self, degrees):
        self.azimuth = float(degrees) % 360.0
        self.update()
        

    # ----------------------------------------------------------------
    def set_elevation(self, degrees):
        self.elevation = float(degrees)
        self.update()
        

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        center_x, center_y = 70, 70
        radius = 55
        
        painter.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100), 1))
        painter.setBrush(QtGui.QColor(40, 40, 40))
        painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
        
        painter.setPen(QtGui.QPen(QtGui.QColor(200, 200, 200)))
        font = QtGui.QFont("Segoe UI", 8, QtGui.QFont.Bold)
        painter.setFont(font)
        
        painter.drawText(center_x - 10, center_y - radius + 4, 20, 16, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, "N")
        painter.drawText(center_x - 10, center_y + radius - 20, 20, 16, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom, "S")
        painter.drawText(center_x + radius - 24, center_y - 8, 20, 16, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, "E")
        painter.drawText(center_x - radius + 4, center_y - 8, 20, 16, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "W")
        
        painter.setPen(QtGui.QPen(QtGui.QColor(80, 80, 80), 1))
        painter.drawLine(center_x, center_y - radius, center_x, center_y + radius)
        painter.drawLine(center_x - radius, center_y, center_x + radius, center_y)
        
        # angle goes clockwise from top (N = 0)
        sun_rad = math.radians(self.azimuth - 90)
        # altitude maps from 90 (center) to 0 (edge) to -20 (slightly outside or hidden)
        alt_clamped = max(-20.0, min(90.0, self.elevation))
        mapped_r = radius * (1.0 - (alt_clamped / 90.0)) if alt_clamped >= 0 else radius + (radius * 0.1)
        
        sun_x = center_x + mapped_r * math.cos(sun_rad)
        sun_y = center_y + mapped_r * math.sin(sun_rad)
        
        color = QtGui.QColor(255, 200, 0) if alt_clamped > 0 else QtGui.QColor(255, 100, 0, 100)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1))
        painter.setBrush(color)
        painter.drawEllipse(int(sun_x - 5), int(sun_y - 5), 10, 10)
        painter.end()

class SunAltitudeWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.elevation = 30.0
        self.setFixedSize(140, 140)
        self.setStyleSheet("background-color: #2b2b2b; border: 1px solid #1a1a1a; border-radius: 4px;")
        

    # ----------------------------------------
    def set_elevation(self, degrees):
        self.elevation = float(degrees)
        self.update()
        

    # ----------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        center_x, center_y = 30, 110
        radius = 80
        
        painter.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100), 1))
        painter.setBrush(QtGui.QColor(50, 50, 50))
        # drawPie angles are in 1/16 of a degree
        painter.drawPie(center_x - radius, center_y - radius, radius * 2, radius * 2, 0, 90 * 16)
        
        painter.setPen(QtGui.QPen(QtGui.QColor(120, 120, 120), 2))
        painter.drawLine(center_x - 10, center_y, center_x + radius + 10, center_y)
        painter.drawLine(center_x, center_y + 10, center_x, center_y - radius - 10)
        
        painter.setPen(QtGui.QPen(QtGui.QColor(200, 200, 200)))
        font = QtGui.QFont("Segoe UI", 8, QtGui.QFont.Bold)
        painter.setFont(font)
        painter.drawText(center_x + radius + 5, center_y - 6, 25, 16, QtCore.Qt.AlignLeft, "0°")
        painter.drawText(center_x - 12, center_y - radius - 24, 25, 16, QtCore.Qt.AlignCenter, "90°")
        
        alt_clamped = max(-20.0, min(90.0, self.elevation))
        sun_rad = math.radians(alt_clamped)
        sun_x = center_x + radius * math.cos(sun_rad)
        sun_y = center_y - radius * math.sin(sun_rad)
        
        if alt_clamped >= 0:
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 0, 100), 1, QtCore.Qt.DashLine))
            painter.drawLine(center_x, center_y, int(sun_x), int(sun_y))
            
        color = QtGui.QColor(255, 200, 0) if alt_clamped > 0 else QtGui.QColor(255, 100, 0, 100)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1))
        painter.setBrush(color)
        painter.drawEllipse(int(sun_x - 5), int(sun_y - 5), 10, 10)
        
        painter.setPen(QtGui.QPen(QtGui.QColor(180, 180, 180)))
        painter.drawText(center_x + 10, center_y + 10, 100, 16, QtCore.Qt.AlignLeft, f"Alt: {self.elevation:.1f}°")
        painter.end()

# ------------------------------------------------------------
class AtmosphereVisualWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fog_height = 30.0
        self.fog_density = 0.25
        self.cloud_alt = 140.0
        self.cloud_density = 0.20
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setMinimumHeight(150)
        self.setStyleSheet("background-color: #2b2b2b; border: 1px solid #1a1a1a; border-radius: 4px;")
        

    def update_fog(self, height, density):
        self.fog_height = height
        self.fog_density = density
        self.update()
        

    # ------------------------------------------------------------
    def update_cloud(self, alt, density):
        self.cloud_alt = alt
        self.cloud_density = density
        self.update()

    # ------------------------------------------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        ground_y = h - 20
        
        def map_alt(alt):
            return (min(max(alt, 0), 13000.0) / 13000.0) ** 0.5
            
        grad = QtGui.QLinearGradient(0, 0, 0, ground_y)
        grad.setColorAt(0, QtGui.QColor(40, 60, 90))
        grad.setColorAt(1, QtGui.QColor(80, 100, 120))
        painter.fillRect(0, 0, w, ground_y, grad)
        
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(45, 45, 45))
        painter.drawRect(0, ground_y, w, 20)
        painter.setPen(QtGui.QPen(QtGui.QColor(120, 120, 120), 1))
        painter.drawLine(0, ground_y, w, ground_y)
        
        fog_pixels = int(map_alt(self.fog_height) * (ground_y - 20))
        
        fog_alpha = min(255, int(self.fog_density * 800))
        if fog_alpha > 0 and fog_pixels > 0:
            fog_grad = QtGui.QLinearGradient(0, ground_y - fog_pixels, 0, ground_y)
            fog_grad.setColorAt(0, QtGui.QColor(200, 200, 200, 0))
            fog_grad.setColorAt(1, QtGui.QColor(200, 200, 200, fog_alpha))
            painter.fillRect(0, ground_y - fog_pixels, w, fog_pixels, fog_grad)
            
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 255)))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(5, ground_y - int(fog_pixels*0.5) - 5, w, 20, QtCore.Qt.AlignLeft, f"Fog: {self.fog_height:.0f}m")
            
        cloud_y = ground_y - int(map_alt(self.cloud_alt) * (ground_y - 20))
        cloud_alpha = min(255, int(self.cloud_density * 400))
        
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 150), 1, QtCore.Qt.DashLine))
        painter.drawLine(0, cloud_y, w, cloud_y)
        
        if cloud_alpha > 0:
            font.setPointSize(28)
            painter.setFont(font)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, max(150, cloud_alpha))))
            for x in range(w // 2, w - 20, 80):
                painter.drawText(x, cloud_y + 15, "☁")
            
        font = painter.font()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        
        if self.cloud_alt < 2000:
            c_type = "Stratus / Cumulus"
        elif self.cloud_alt < 7000:
            c_type = "Altocumulus / Altostratus"
        else:
            c_type = "Cirrus / Cirrostratus"
            
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 255)))
        painter.drawText(5, cloud_y - 18, w, 20, QtCore.Qt.AlignLeft, f"Cloud: {self.cloud_alt:.0f}m ({c_type})")

        painter.end()


# ----------------------------------------------------------------------
class FloatSlider(QtWidgets.QWidget):
    # real value, whether it came from the slider, the spin box or setValue()
    valueChanged = QtCore.Signal(float)

    def __init__(self, min_val, max_val, default_val, decimals=2, tick_points=None, snap_points=None):
        super().__init__()
        self.mult = 10 ** decimals
        self.snap_points = snap_points or []
        
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        slider_row = QtWidgets.QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)
        slider_row.setSpacing(6)
        
        self.slider = ClickSlider(QtCore.Qt.Horizontal)
        self.slider.setMinimum(int(round(min_val * self.mult)))
        self.slider.setMaximum(int(round(max_val * self.mult)))
        self.slider.setValue(int(round(default_val * self.mult)))
        self.slider.setMinimumHeight(22)
        self.slider.setStyleSheet(_slider_stylesheet())
        
        self.spin = QtWidgets.QDoubleSpinBox()
        self.spin.setDecimals(decimals)
        self.spin.setRange(min_val, max_val)
        self.spin.setValue(default_val)
        self.spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.spin.setAlignment(QtCore.Qt.AlignCenter)
        self.spin.setFixedWidth(55)
        
        slider_row.addWidget(self.slider, 1)
        slider_row.addWidget(self.spin)
        self.layout.addLayout(slider_row)
        
        if tick_points:
            labels_row = QtWidgets.QHBoxLayout()
            labels_row.setContentsMargins(0, 0, 0, 0)
            self.tick_labels = _SliderTickLabels(tick_points, self)
            labels_row.addWidget(self.tick_labels, 1)
            labels_row.addSpacing(74)
            self.layout.addLayout(labels_row)
        else:
            self.tick_labels = None
            
        self.slider.valueChanged.connect(self.slider_changed)
        self.spin.valueChanged.connect(self.spin_changed)
        

    # --------------------------------------------------------
    def _snap_value(self, val):
        if not self.snap_points:
            return val
        # snap within 5% of the range
        threshold = (self.slider.maximum() - self.slider.minimum()) / (self.mult * 20.0)
        for sp in self.snap_points:
            if abs(val - sp) < threshold:
                return sp
        return val
        

    # --------------------------------------------------------------------------------
    def slider_changed(self, val):
        real_val = val / float(self.mult)
        snapped_val = self._snap_value(real_val)
        
        if snapped_val != real_val:
            self.slider.blockSignals(True)
            self.slider.setValue(int(round(snapped_val * self.mult)))
            self.slider.blockSignals(False)
            real_val = snapped_val
            
        self.spin.blockSignals(True)
        self.spin.setValue(real_val)
        self.spin.blockSignals(False)
        self.valueChanged.emit(real_val)
        

    # ------------------------------------------------------------
    def spin_changed(self, val):
        snapped_val = self._snap_value(val)
        if snapped_val != val:
            self.spin.blockSignals(True)
            self.spin.setValue(snapped_val)
            self.spin.blockSignals(False)
            val = snapped_val
            
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(val * self.mult)))
        self.slider.blockSignals(False)
        self.valueChanged.emit(val)
        

    # ----------------------------------------------------------------------
    def value(self): return self.spin.value()


    def setValue(self, val): self.spin.setValue(val)


# ----------------------------------------
class IntSlider(QtWidgets.QWidget):
    def __init__(self, min_val, max_val, default_val):
        super().__init__()
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(6)
        
        self.slider = ClickSlider(QtCore.Qt.Horizontal)
        self.slider.setMinimum(min_val)
        self.slider.setMaximum(max_val)
        self.slider.setValue(default_val)
        self.slider.setMinimumHeight(22)
        self.slider.setStyleSheet(_slider_stylesheet())
        
        self.spin = QtWidgets.QSpinBox()
        self.spin.setRange(min_val, max_val)
        self.spin.setValue(default_val)
        self.spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.spin.setAlignment(QtCore.Qt.AlignCenter)
        self.spin.setFixedWidth(55)
        
        self.layout.addWidget(self.slider, 1)
        self.layout.addWidget(self.spin)
        
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        

    # ------------------------------------------------------------
    def value(self): return self.spin.value()

    # ----------------------------------------------------------------
    def setValue(self, val): self.spin.setValue(val)


# ====================================================
# LOGIQUE LOPs : GET OR CREATE
# ====================================================


# --------------------------------------------------------
class PopupRefreshComboBox(QtWidgets.QComboBox):
    popupAboutToShow = QtCore.Signal()

    # ------------------------------------------------------------
    def showPopup(self):
        self.popupAboutToShow.emit()
        super().showPopup()


# ------------------------------------------------------------
def _asset_mime_type():
    try:
        return hou.qt.mimeType.asset
    except Exception:
        return ""


# ------------------------------------------------------------
def _drop_event_pos(event):
    # Qt6 has event.position(), Qt5 only event.pos()
    if hasattr(event, "position"):
        return event.position().toPoint()
    return event.pos()

# ------------------------------------------------------------
# Prim list that takes materials dragged from the asset gallery. A drop emits assetDropped(payload, paths),
# and on a selected prim the whole selection is targeted.
class MaterialTargetTree(QtWidgets.QTreeWidget):
    assetDropped = QtCore.Signal(str, str)

    PATH_ROLE = QtCore.Qt.UserRole

    # ----------------------------------------------------------------------
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels(["Prim", "Type", "Material"])
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setUniformRowHeights(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DropOnly)
        self.setAlternatingRowColors(True)
        self.header().setStretchLastSection(True)
        self.setColumnWidth(0, 260)
        self.setColumnWidth(1, 90)
        self._hover_item = None
        self._items = {}

    # ------------------------------------------------------------
    # prims: [(path, parent_path, type_name)] in traversal order.
    def set_prims(self, prims, materials):
        selected = set(self.selected_paths())
        self.setUpdatesEnabled(False)
        self.clear()
        self._items = {}
        for path, parent_path, type_name in prims:
            parent_item = self._nearest_item(parent_path)
            item = QtWidgets.QTreeWidgetItem([path.rsplit("/", 1)[-1], type_name, materials.get(path, "")])
            item.setData(0, self.PATH_ROLE, path)
            item.setToolTip(0, path)
            if parent_item is None:
                self.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            self._items[path] = item
            if path in selected:
                item.setSelected(True)
        self.expandAll()
        self.setUpdatesEnabled(True)

    # ------------------------------------------------------------
    def _nearest_item(self, path):
        while path and path != "/":
            item = self._items.get(path)
            if item is not None:
                return item
            path = path.rsplit("/", 1)[0]
        return None

    # ------------------------------------------------------------
    def selected_paths(self):
        return [item.data(0, self.PATH_ROLE) for item in self.selectedItems()]

    # drag and drop

    # ----------------------------------------------------------------
    def _accepts(self, event):
        mime_type = _asset_mime_type()
        return bool(mime_type) and event.mimeData().hasFormat(mime_type)

    # ------------------------------------------------------------
    def _set_hover(self, item):
        if item is self._hover_item:
            return
        if self._hover_item is not None:
            for col in range(self.columnCount()):
                self._hover_item.setBackground(col, QtGui.QBrush())
        self._hover_item = item
        if item is not None:
            brush = QtGui.QBrush(QtGui.QColor(70, 120, 170, 150))
            for col in range(self.columnCount()):
                item.setBackground(col, brush)

    # ------------------------------------------------------------
    def dragEnterEvent(self, event):
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        item = self.itemAt(_drop_event_pos(event))
        if self._accepts(event) and item is not None:
            self._set_hover(item)
            event.acceptProposedAction()
        else:
            self._set_hover(None)
            event.ignore()


    # --------------------------------------------------
    def dragLeaveEvent(self, event):
        self._set_hover(None)
        super().dragLeaveEvent(event)

    # ------------------------------------------------------------
    def dropEvent(self, event):
        item = self.itemAt(_drop_event_pos(event))
        self._set_hover(None)
        if not self._accepts(event) or item is None:
            event.ignore()
            return
        paths = self.selected_paths() if item.isSelected() else [item.data(0, self.PATH_ROLE)]
        try:
            payload = bytes(event.mimeData().data(_asset_mime_type())).decode("utf-8")
        except (UnicodeDecodeError, TypeError, ValueError):
            event.ignore()
            return
        event.acceptProposedAction()
        self.assetDropped.emit(payload, "\n".join(paths))


# ----------------------------------------
def _pset(node, name, value, log_callback, quiet=False):
    p = node.parm(name)
    if p is not None:
        try:
            if p.isLocked(): p.lock(False)
            try:
                p.set(value)
            except TypeError:
                p.set(str(value))
            return True
        except hou.PermissionError:
            _debug("locked parm {}.{}".format(_debug_node_label(node), name))
            if not quiet: log_callback(f"  [WARN] Locked parm: '{name}' on {node.name()}")
            return False
    _debug("no parm '{}' on {}".format(name, _debug_node_label(node)))
    return False


# ------------------------------------------------------------------------
def _base_node_type_name(node):
    try:
        return node.type().name().split("::", 1)[0]
    except Exception:
        return ""


def _mark_tool_node(node):
    if node is None:
        return
    try:
        node.setUserData(TOOL_NODE_TAG_KEY, TOOL_NODE_TAG_VALUE)
    except Exception:
        pass


# ----------------------------------------------------------------------
def _is_tool_node_candidate(node, node_name=None):
    if node is None:
        return False

    try:
        if node.userData(TOOL_NODE_TAG_KEY) == TOOL_NODE_TAG_VALUE:
            return True
    except Exception:
        pass

    if node_name in TOOL_STAGE_NODE_TYPES:
        return _base_node_type_name(node) in TOOL_STAGE_NODE_TYPES[node_name]
    return False


def _get_or_create_node(parent, node_type, node_name):
    n = parent.node(node_name)
    if n is None:
        n = parent.createNode(node_type, node_name)
    elif not _is_tool_node_candidate(n, node_name) and _base_node_type_name(n) != node_type:
        # a user's node that only shares the name: never rewire, retag or delete it
        raise hou.OperationFailed("{} exists and is a '{}', not a '{}': rename it or delete it.".format(
            n.path(), _base_node_type_name(n), node_type))
    _mark_tool_node(n)
    return n


# ------------------------------------------------------------
def _safe_connect(node, prev):
    if node is not None and prev is not None and node.input(0) != prev:
        node.setInput(0, prev)


# ------------------------------------------------------------
def _get_or_create_stage():
    stage = hou.node("/stage")
    if stage is None:
        obj = hou.node("/obj")
        stage = obj.createNode("lopnet", "karma_render")
    return stage


#--------------------------------------------------------------------------------
def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


# ------------------------------------------------------------
def _kelvin_to_rgb(temp_k):
    t = _clamp(float(temp_k), 1000.0, 40000.0) / 100.0
    if t <= 66.0:
        r = 255.0
        g = 99.4708025861 * math.log(max(t, 1.0)) - 161.1195681661
        if t <= 19.0:
            b = 0.0
        else:
            b = 138.5177312231 * math.log(max(t - 10.0, 1.0)) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60.0) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60.0) ** -0.0755148492)
        b = 255.0

    return (
        _clamp(r / 255.0, 0.0, 1.0),
        _clamp(g / 255.0, 0.0, 1.0),
        _clamp(b / 255.0, 0.0, 1.0),
    )


# --------------------------------------------------
def _apply_tint(rgb, tint):
    t = _clamp(float(tint), -1.0, 1.0)
    if t >= 0.0:
        m = (1.0 + t * 0.45, 1.0 - t * 0.35, 1.0 + t * 0.45)
    else:
        tg = abs(t)
        m = (1.0 - tg * 0.25, 1.0 + tg * 0.45, 1.0 - tg * 0.25)

    return (
        _clamp(rgb[0] * m[0], 0.0, 2.0),
        _clamp(rgb[1] * m[1], 0.0, 2.0),
        _clamp(rgb[2] * m[2], 0.0, 2.0),
    )


# --------------------------------------------------------------------------------
def _apply_saturation(rgb, saturation):
    sat = _clamp(float(saturation), 0.0, 2.0)
    lum = rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722
    return (
        _clamp(lum + (rgb[0] - lum) * sat, 0.0, 2.0),
        _clamp(lum + (rgb[1] - lum) * sat, 0.0, 2.0),
        _clamp(lum + (rgb[2] - lum) * sat, 0.0, 2.0),
    )



def _set_light_color(node, rgb):
    color_parm = _find_usd_input_parm(node, "color")
    tuple_candidates = [
        color_parm.tuple().name() if color_parm is not None else "xn__inputscolor_i0a",
        "inputscolor",
        "lightcolor",
        "light_color",
        "color",
    ]
    for parm_name in tuple_candidates:
        pt = node.parmTuple(parm_name)
        if pt is None or len(pt) != 3:
            continue
        try:
            for p in pt:
                if p.isLocked():
                    p.lock(False)
            pt.set(rgb)
            return True
        except Exception:
            pass

    for pt in node.parmTuples():
        pname = pt.name().lower()
        if len(pt) == 3 and "color" in pname and ("input" in pname or "light" in pname):
            try:
                for p in pt:
                    if p.isLocked():
                        p.lock(False)
                pt.set(rgb)
                return True
            except Exception:
                pass
    return False


# ------------------------------------------------------------
def _set_first_existing_parm(node, parm_names, value, log_callback):
    for parm_name in parm_names:
        if _pset(node, parm_name, value, log_callback, quiet=True):
            return True
    return False


# ----------------------------------------------------------------
def _set_first_existing_parm_tuple(node, parm_names, values, log_callback):
    values = tuple(values)
    for parm_name in parm_names:
        pt = node.parmTuple(parm_name)
        if pt is None or len(pt) != len(values):
            continue
        try:
            for p in pt:
                if p.isLocked():
                    p.lock(False)
            pt.set(values)
            return True
        except Exception:
            continue
    return False


# ------------------------------------------------------------
def _set_menu_parm_by_keywords(node, parm_names, keywords, log_callback):
    keys = tuple(str(k).lower() for k in (keywords or ()))
    if not keys:
        return False

    for parm_name in parm_names:
        parm = node.parm(parm_name)
        if parm is None:
            continue
        try:
            items = list(parm.menuItems())
            labels = list(parm.menuLabels())
        except Exception:
            continue

        for idx, item in enumerate(items):
            label = labels[idx] if idx < len(labels) else ""
            blob = "{} {}".format(item, label).lower()
            if not any(k in blob for k in keys):
                continue

            for candidate in (item, idx):
                try:
                    if parm.isLocked():
                        parm.lock(False)
                    parm.set(candidate)
                    return True
                except Exception:
                    pass
    return False


# --------------------------------------------------
# ATTENTION -> le suffixe de xn__inputs<token>_<hash> change d'une version à l'autre,
# d'où la recherche par pattern ('width', 'color'...) et jamais par nom exact
def _find_usd_input_parm(node, token):
    pattern = re.compile(r"^xn__inputs{}_(?!control)[a-z0-9]+$".format(re.escape(token)), re.IGNORECASE)
    for parm in node.parms():
        if pattern.match(parm.name()):
            return parm
    return None

# --------------------------------------------------------
def _set_usd_input(node, token, value, log_callback, quiet=True):
    parm = _find_usd_input_parm(node, token)
    if parm is None:
        return False
    return _pset(node, parm.name(), value, log_callback, quiet=quiet)


# ------------------------------------------------------------
def _menu_has_value(parm, value):
    try:
        items = list(parm.menuItems())
    except hou.OperationFailed:
        return True
    return value in items


# ------------------------------------------------------------
def _is_lop_camera(node):
    if node is None:
        return False
    try:
        return "camera" in node.type().name().lower()
    except Exception:
        return False


#--------------------------------------------------------------------------------
def _normalize_output_path_extension(path, output_format):
    ext = ".exr" if str(output_format).upper() == "EXR" else ".png"
    root, cur_ext = os.path.splitext(path)
    # "beauty.$F4" has no extension: the frame token must survive, not be swapped for ".exr"
    if not cur_ext or "$" in cur_ext or "`" in cur_ext:
        return path + ext
    if cur_ext.lower() != ext:
        return root + ext
    return path

CAMERA_CREATE_LABEL = "Create New Camera"
USD_CAMERA_PREFIX = "usd:"
GENERATED_CAMERA_NAME = "render_cam"


# ------------------------------------------------------------
# Fix erreur = Render Settings veut le chemin de prim USD, pas le chemin du node
# (la caméra était ignorée avant)
def _camera_prim_path(cam):
    for parm_name in ("primpath", "primpattern"):
        parm = cam.parm(parm_name)
        if parm is not None:
            value = parm.evalAsString().strip()
            if value.startswith("/"):
                return value
    return "/cameras/{}".format(cam.name())


# ------------------------------------------------------------
def _lop_camera_nodes(stage):
    if stage is None:
        return []
    return [
        node for node in stage.children()
        if _is_lop_camera(node) and node.name() != GENERATED_CAMERA_NAME
    ]


# ------------------------------------------------------------
def _stage_camera_prims(usd_stage):
    from pxr import UsdGeom
    return [str(prim.GetPath()) for prim in usd_stage.Traverse() if prim.IsA(UsdGeom.Camera)]

# ------------------------------------------------------------
def _apply_matrix_to_camera(cam, matrix_values, log_callback):
    try:
        matrix = hou.Matrix4(tuple(matrix_values))
        translate = matrix.extractTranslates()
        rotate = matrix.extractRotates()
    except (hou.Error, TypeError, ValueError) as exc:
        log_callback("[WARN] Could not read the viewport transform: {}".format(exc))
        return False
    for name, value in zip(("tx", "ty", "tz"), translate):
        _pset(cam, name, value, log_callback, quiet=True)
    for name, value in zip(("rx", "ry", "rz"), rotate):
        _pset(cam, name, value, log_callback, quiet=True)
    return True


# --------------------------------------------------
# bug trouvé et fixé: la position était remise à zéro à chaque build, une caméra bougée à la main
# revenait à sa place. Maintenant seulement à la création ou pour un match du viewport. 🙂
def _create_camera(stage, focal, res_x, res_y, pos, log_callback, view_matrix=None):
    is_new = stage.node(GENERATED_CAMERA_NAME) is None
    cam = _get_or_create_node(stage, "camera", GENERATED_CAMERA_NAME)
    _pset(cam, "focalLength", float(focal), log_callback, quiet=True)
    if res_x / res_y > 2.0: _pset(cam, "aperture", 41.42, log_callback)
    if view_matrix:
        _apply_matrix_to_camera(cam, view_matrix, log_callback)
    elif is_new:
        _pset(cam, "tx", pos[0], log_callback); _pset(cam, "ty", pos[1], log_callback); _pset(cam, "tz", pos[2], log_callback)
    return cam


# ----------------------------------------------------------------------
def _remove_tool_node(stage, node_name, log_callback, reason=""):
    node = stage.node(node_name)
    if node is None or not _is_tool_node_candidate(node, node_name):
        return False
    try:
        node.destroy()
    except hou.OperationFailed as exc:
        log_callback("[WARN] Could not remove {}: {}".format(node_name, exc))
        return False
    if reason:
        log_callback("[INFO] Removed {} ({}).".format(node_name, reason))
    return True


# --------------------------------------------------
# (camera node or None, USD prim path). camera_choice is the create label, a camera LOP path, or
# 'usd:<prim path>' for a camera that lives in the geometry source (no node then).
def _resolve_render_camera(stage, cfg, log_callback):
    choice = str(cfg.get("camera_choice", CAMERA_CREATE_LABEL)).strip()

    if choice.startswith(USD_CAMERA_PREFIX):
        prim_path = choice[len(USD_CAMERA_PREFIX):]
        if not (cfg.get("geo_source") or "").strip():
            log_callback("[WARN] Camera prim {} only exists in the stage when its LOP is chosen as Geometry Source.".format(prim_path))
        _remove_tool_node(stage, GENERATED_CAMERA_NAME, log_callback, "a USD camera is used instead")
        return None, prim_path

    if choice and choice != CAMERA_CREATE_LABEL:
        cam = hou.node(choice)
        if _is_lop_camera(cam) and cam.name() != GENERATED_CAMERA_NAME:
            _remove_tool_node(stage, GENERATED_CAMERA_NAME, log_callback, "{} is used instead".format(cam.name()))
            return cam, _camera_prim_path(cam)
        log_callback("[WARN] Selected camera not found or invalid: {} | fallback to a new camera.".format(choice))

    cam = _create_camera(
        stage,
        float(cfg.get("new_cam_focal", 35.0)),
        cfg["res_x"],
        cfg["res_y"],
        (0.0, 2.0, 8.0),
        log_callback,
        view_matrix=cfg.get("viewport_matrix") if cfg.get("new_cam_from_viewport") else None,
    )
    return cam, _camera_prim_path(cam)


# ------------------------------------------------------------
def _create_dome_light(stage, prev, intensity, texture_path, log_callback, name="dome_light", hdri_opts=None):
    dome = _get_or_create_node(stage, "domelight", name)
    ev = 0.0 if hdri_opts is None else float(hdri_opts.get("hdri_ev", 0.0))
    final_intensity = max(0.0, float(intensity) * (2.0 ** ev))

    if not _set_usd_input(dome, "intensity", final_intensity, log_callback):
        _set_first_existing_parm(dome, ("intensity",), final_intensity, log_callback)
    if not (_set_usd_input(dome, "texturefile", texture_path, log_callback)
            or _set_usd_input(dome, "texture_file", texture_path, log_callback)):
        log_callback("[WARN] Dome light: texture parameter not found on {}.".format(dome.type().name()))

    if hdri_opts is not None:
        _pset(dome, "ry", float(hdri_opts.get("hdri_rot", 0.0)), log_callback, quiet=True)
        # no blur here: Karma's light schema has no attribute for it on H22

        temp_rgb = _kelvin_to_rgb(float(hdri_opts.get("hdri_temp", 6500.0)))
        tint_rgb = _apply_tint(temp_rgb, float(hdri_opts.get("hdri_tint", 0.0)))
        final_rgb = _apply_saturation(tint_rgb, float(hdri_opts.get("hdri_sat", 1.0)))
        _set_light_color(dome, final_rgb)

    _safe_connect(dome, prev)
    return dome


# ------------------------------------------------------------
def _create_area_light(stage, prev, intensity, log_callback, name="area_light", pos=(3.0, 4.0, 3.0), rot=(-45.0, 30.0, 0.0)):
    is_new = stage.node(name) is None
    area = _get_or_create_node(stage, "light", name)
    _set_usd_input(area, "intensity", float(intensity), log_callback)
    # size and placement only at creation: a light moved by hand must stay where it was put
    if is_new:
        _set_usd_input(area, "width", 1.5, log_callback)
        _set_usd_input(area, "height", 1.5, log_callback)
        _pset(area, "tx", pos[0], log_callback); _pset(area, "ty", pos[1], log_callback); _pset(area, "tz", pos[2], log_callback)
        _pset(area, "rx", rot[0], log_callback); _pset(area, "ry", rot[1], log_callback); _pset(area, "rz", rot[2], log_callback)
    _safe_connect(area, prev)
    return area


def _create_physical_sky(stage, prev, cfg, log_callback):
    try:
        sky = _get_or_create_node(stage, "karmaphysicalsky", "physical_sky")
        
        if "sky_mode" in cfg:
            _pset(sky, "skymode", int(cfg["sky_mode"]), log_callback, quiet=True)
            
        # one name per Houdini generation: a parm that none of them matches is reported, not skipped silently
        missing = []
        for label, names, value in (
            ("sun altitude", ("solar_altitude", "sunelevation"), float(cfg["sky_elev"])),
            ("sun azimuth", ("solar_azimuth", "sunazimuth"), float(cfg["sky_azim"])),
            ("sun intensity", ("sun_intensity", "sunintensity"), float(cfg["sky_sun_int"])),
            ("sun size", ("angle", "sunsize"), float(cfg["sky_sun_size"])),
        ):
            if not _set_first_existing_parm(sky, names, value, log_callback):
                missing.append(label)
        if missing:
            log_callback("[WARN] Physical Sky: no matching parameter for {} on {} (this Houdini version?).".format(
                ", ".join(missing), sky.type().nameWithCategory()))
        
        sun_temp = float(cfg.get("sky_sun_temp", 5500.0))
        sun_color = _kelvin_to_rgb(sun_temp)
        _set_first_existing_parm_tuple(sky, ("sun_color", "suncolor"), sun_color, log_callback)

        _pset(sky, "turbidity",    float(cfg["sky_turbidity"]), log_callback, quiet=True)
        
        # volumes absorb sky light, boost it when fog or clouds are on
        sky_int = float(cfg["sky_int"])
        if cfg.get("enable_fog") or cfg.get("enable_clouds"):
            sky_int *= 4.0

        if not _set_first_existing_parm(sky, ("sky_intensity", "skyintensity"), sky_int, log_callback):
            log_callback("[WARN] Physical Sky: no matching parameter for sky intensity on {}.".format(
                sky.type().nameWithCategory()))
        
        _set_first_existing_parm(sky, ("horizon_blur", "horizonblurfalloff"), float(cfg["sky_hz_blur"]), log_callback)

        # H22 has scale parms, the sliders multiply their defaults
        if "sky_atm_rayleigh" in cfg:
            rayleigh = float(cfg["sky_atm_rayleigh"])
            mie = float(cfg["sky_atm_mie"])
            if sky.parm("rayleighscale") is not None:
                _pset(sky, "rayleighscale", 3e-05 * rayleigh, log_callback, quiet=True)
                _pset(sky, "miescatterscale", 5e-06 * mie, log_callback, quiet=True)
            else:
                _set_first_existing_parm(sky, ("atmosphere_rayleigh", "rayleigh"), rayleigh, log_callback)
                _set_first_existing_parm(sky, ("atmosphere_mie", "mie", "haze"), mie, log_callback)
        _pset(sky, "enablesun", 1, log_callback, quiet=True)

        _safe_connect(sky, prev)

        if cfg.get("sky_mode", 0) == 1:
            linker = _get_or_create_node(stage, "lightlinker", "sky_atmosphere_linker")
            _pset(linker, "num_links", 1, log_callback, quiet=True)

            # Fix erreur = lightlinker recevait des chemins de node, il veut des chemins de prim USD: <primpath du sky>/<nom du sun>
            sky_root = sky.parm("primpath").evalAsString().rstrip("/") if sky.parm("primpath") else "/lights/physical_sky"
            sun_name = sky.parm("sunprim").evalAsString() if sky.parm("sunprim") else "sun"
            atmo_name = sky.parm("atmoprim").evalAsString() if sky.parm("atmoprim") else "atmosphere"

            _pset(linker, "link_type_1", "light", log_callback, quiet=True)
            _pset(linker, "link_prim_1", "{}/{}".format(sky_root, sun_name), log_callback, quiet=True)
            _pset(linker, "link_includes_1", "{}/{}".format(sky_root, atmo_name), log_callback, quiet=True)
            _safe_connect(linker, sky)
            return linker
            
        return sky
    except hou.OperationFailed as exc:
        _remove_tool_node(stage, "sky_atmosphere_linker", log_callback)
        _remove_tool_node(stage, "physical_sky", log_callback)
        log_callback("[WARN] Physical sky could not be built: {}".format(exc))
        return prev


# ------------------------------------------------------------
def _create_fog_branch(stage, prev, cfg, log_callback):
    fog_geo = _get_or_create_node(stage, "karmafogbox", "atmosphere_fog")
    
    fog_radius = max(5.0, float(cfg.get("fog_radius", 120.0))) * 20.0
    fog_height = float(cfg.get("fog_height", 30.0))
    fog_density = float(cfg.get("fog_density", 0.05))
    fog_phase = float(cfg.get("fog_phase", 0.4))
    
    _pset(fog_geo, "primpath", "/World/Environment/Fog", log_callback, quiet=True)
    _pset(fog_geo, "shape", 0, log_callback, quiet=True) # 0 = Box
    
    _pset(fog_geo, "density", fog_density, log_callback, quiet=True)
    _pset(fog_geo, "shadow", fog_density * 0.8, log_callback, quiet=True)
    _pset(fog_geo, "phase", fog_phase, log_callback, quiet=True)
    
    amb_color = (
        float(cfg.get("sky_amb_r", 1.0)),
        float(cfg.get("sky_amb_g", 1.0)),
        float(cfg.get("sky_amb_b", 1.0))
    )
    _set_first_existing_parm_tuple(fog_geo, ("color",), amb_color, log_callback)

    _pset(fog_geo, "sx", fog_radius, log_callback, quiet=True)
    _pset(fog_geo, "sy", fog_height * 2.0, log_callback, quiet=True)
    _pset(fog_geo, "sz", fog_radius, log_callback, quiet=True)
    
    _pset(fog_geo, "ty", fog_height, log_callback, quiet=True)
    
    _pset(fog_geo, "addnoise", 1, log_callback, quiet=True)
    _pset(fog_geo, "amplitude", float(cfg.get("fog_noise_amp", 0.5)), log_callback, quiet=True)
    _pset(fog_geo, "noisescale", float(cfg.get("fog_noise_scale", 0.1)), log_callback, quiet=True)

    _safe_connect(fog_geo, prev)
    return fog_geo

DEFAULT_CLOUD_MATERIAL_PATH = "/World/Materials/KarmaCloud"
QUICK_CLOUD_NAME = "quickcloudmaterial"

# ------------------------------------------------------------
# SideFX's Quick Cloud Material (an Edit Material Properties LOP). Returns the node, or None.
def _create_quick_cloud_material(stage, prev, cfg, log_callback):
    try:
        from husd import quickmaterials
    except ImportError:
        log_callback("[WARN] husd.quickmaterials is not available in this Houdini: no Quick Cloud Material.")
        return None

    node = stage.node(QUICK_CLOUD_NAME)
    if node is None:
        node = stage.createNode("editmaterialproperties", QUICK_CLOUD_NAME)
        try:
            quickmaterials.createQuickCloudMaterial(quick_material_node=node)
        except (hou.Error, AttributeError, KeyError, TypeError) as exc:
            node.destroy()
            log_callback("[WARN] Could not set up the Quick Cloud Material: {}".format(exc))
            return None
    _mark_tool_node(node)

    # 0.2 on the slider is SideFX's default density scale (1)
    _pset(node, "densityscale", max(0.0, float(cfg.get("cloud_density", 0.20)) * 5.0), log_callback, quiet=True)
    _safe_connect(node, prev)
    return node

# ------------------------------------------------------------
def _create_cloud_branch(stage, prev, cfg, log_callback):
    cloud_geo = _get_or_create_node(stage, "sopcreate", "cloud_geo")
    if cloud_geo.isLockedHDA():
        cloud_geo.allowEditingOfContents()
    _set_first_existing_parm(cloud_geo, ("primpath", "destpath"), "/World/Environment/Clouds", log_callback)
    _pset(cloud_geo, "pathprefix", "/World/Environment/Clouds", log_callback, quiet=True)

    sopnet = cloud_geo.node("sopnet")
    if sopnet:
        skybox = sopnet.node("cloud_base")
        if not skybox:
            try:
                for n in sopnet.children():
                    if n.name() not in ["OUT", "output"]:
                        n.destroy()
            except Exception as e:
                log_callback(f"[WARN] Failed to destroy nodes in cloud sopnet: {e}")
            
            skybox = sopnet.createNode("skybox", "cloud_base")
            _mark_tool_node(skybox)
            _pset(skybox, "sizex", 1000, log_callback, quiet=True)
            _pset(skybox, "sizey", 200, log_callback, quiet=True)
            _pset(skybox, "sizez", 1000, log_callback, quiet=True)
            _pset(skybox, "divsize", float(cfg.get("cloud_precision", 5.0)), log_callback, quiet=True)

            billowy = sopnet.createNode("cloudbillowynoise", "add_detail")
            _mark_tool_node(billowy)
            billowy.setInput(0, skybox)
            _set_first_existing_parm(billowy, ("niters", "iterations"), 4, log_callback)
            _set_first_existing_parm(billowy, ("doworleydetails", "useworley"), 1, log_callback)
            _pset(billowy, "offset", float(cfg.get("cloud_clip", 0.35)), log_callback, quiet=True)

            adjust = sopnet.createNode("cloudadjustdensityprofile", "adjust_density")
            _mark_tool_node(adjust)
            adjust.setInput(0, billowy)

            out_node = sopnet.node("OUT")
            if out_node is None:
                out_node = sopnet.createNode("output", "OUT_CLOUD")
                _mark_tool_node(out_node)
            out_node.setInput(0, adjust)
            out_node.setDisplayFlag(True)
            out_node.setRenderFlag(True)

            sopnet.layoutChildren()

    _safe_connect(cloud_geo, prev)

    cloud_xform = _get_or_create_node(stage, "xform", "cloud_xform")
    _set_first_existing_parm(
        cloud_xform,
        ("primpattern", "primpath", "prims", "primpattern1"),
        "/World/Environment/Clouds*",
        log_callback,
    )
    cloud_altitude = float(cfg.get("cloud_altitude", 140.0))
    cloud_scale = max(5.0, float(cfg.get("cloud_scale", 180.0)))
    _set_first_existing_parm_tuple(
        cloud_xform,
        ("t", "translate", "trans"),
        (0.0, cloud_altitude, 0.0),
        log_callback,
    )
    scale_c = cloud_scale / 100.0
    _set_first_existing_parm_tuple(
        cloud_xform,
        ("s", "scale", "scales"),
        (scale_c, scale_c * 0.5, scale_c),
        log_callback,
    )
    _safe_connect(cloud_xform, cloud_geo)

    assign = _get_or_create_node(stage, "assignmaterial", "assign_cloud_shader")
    _pset(assign, "primpattern1", "/World/Environment/Clouds*", log_callback, quiet=True)

    cloud_mat_path = (cfg.get("cloud_material_path") or "").strip()
    upstream = cloud_xform
    if not cloud_mat_path or cloud_mat_path == DEFAULT_CLOUD_MATERIAL_PATH:
        quick = _create_quick_cloud_material(stage, cloud_xform, cfg, log_callback)
        if quick is not None:
            upstream = quick
            cloud_mat_path = quick.parm("primpath").evalAsString()
    else:
        _remove_tool_node(stage, QUICK_CLOUD_NAME, log_callback, "a custom cloud material is used")
    if not cloud_mat_path or cloud_mat_path == DEFAULT_CLOUD_MATERIAL_PATH:
        log_callback("[WARN] No cloud material available: clouds will render with the default volume.")

    _pset(assign, "matspecpath1", cloud_mat_path, log_callback, quiet=True)
    _safe_connect(assign, upstream)
    return assign


# ------------------------------------------------------------
def _create_environment_merge(stage, env_base, fog=None, cloud=None):
    merge = _get_or_create_node(stage, "merge", "env_merge")
    inputs = [env_base]
    if fog: inputs.append(fog)
    if cloud: inputs.append(cloud)
    for i in range(len(merge.inputs())): merge.setInput(i, None)
    for i, node in enumerate(inputs): merge.setInput(i, node)
    return merge


# --------------------------------------------------------
def _create_material_library(stage, prev, cfg, log_callback):
    mat_lib = _get_or_create_node(stage, "materiallibrary", "mtlx_materials")
    _safe_connect(mat_lib, prev)

    _set_first_existing_parm(
        mat_lib,
        ("matpathprefix", "materialpathprefix", "pathprefix"),
        "/World/Materials",
        log_callback,
    )

    def _ensure_shader_material(subnet_name, shader_name, shader_types, output_kind="surface"):
        subnet = mat_lib.node(subnet_name)
        if subnet is None:
            subnet = mat_lib.createNode("subnet", subnet_name)
            _mark_tool_node(subnet)

        shader = subnet.node(shader_name)
        if shader is None:
            for shader_type in shader_types:
                try:
                    shader = subnet.createNode(shader_type, shader_name)
                    _mark_tool_node(shader)
                    break
                except hou.OperationFailed:
                    shader = None
                except Exception:
                    shader = None

        if shader is None:
            # Last resort keeps build from failing if a shader node is unavailable.
            try:
                shader = subnet.createNode("mtlxstandard_surface", shader_name)
                _mark_tool_node(shader)
            except Exception:
                shader = None

        out = subnet.node("surface_out")
        if out is None:
            for out_name in ("OUT", "output", "suboutput1"):
                out = subnet.node(out_name)
                if out is not None:
                    break

        if out is None:
            for out_type in ("suboutput", "suboutput1", "subnetconnector", "output"):
                try:
                    out = subnet.createNode(out_type, "surface_out")
                    _mark_tool_node(out)
                    break
                except hou.OperationFailed:
                    out = None
                except Exception:
                    out = None

        if out is not None:
            try:
                kind_values = [output_kind]
                if output_kind == "surface":
                    kind_values.extend(["surface", "output", 0])
                elif output_kind == "volume":
                    kind_values.extend(["volume", "output", 1])

                for kind_val in kind_values:
                    if _set_first_existing_parm(
                        out,
                        ("connectorkind", "kind", "parmtype", "signature"),
                        kind_val,
                        log_callback,
                    ):
                        break
            except Exception:
                pass

            try:
                if shader is not None:
                    out.setInput(0, shader)
            except Exception:
                pass

        try:
            subnet.layoutChildren()
        except Exception:
            pass

        return shader

    is_new_pbr = mat_lib.node("pbr_standard") is None or mat_lib.node("pbr_standard").node("pbr_surface") is None
    pbr_surf = _ensure_shader_material(
        "pbr_standard",
        "pbr_surface",
        ("mtlxstandard_surface",),
        "surface",
    )
    if pbr_surf is not None and is_new_pbr:
        _pset(pbr_surf, "base", 1.0, log_callback)
        _pset(pbr_surf, "base_colorr", 0.8, log_callback)
        _pset(pbr_surf, "base_colorg", 0.8, log_callback)
        _pset(pbr_surf, "base_colorb", 0.8, log_callback)
        _pset(pbr_surf, "specular", 1.0, log_callback)
        _pset(pbr_surf, "specular_roughness", 0.4, log_callback)
        _pset(pbr_surf, "specular_IOR", 1.5, log_callback)

    try:
        mat_lib.layoutChildren()
    except Exception:
        pass

    return mat_lib

# ------------------------------------------------------------
def _apply_aov_precision(aovs, beauty_half, other_half, log_callback):
    pattern = re.compile(r"^(color[34])([hf])$")
    changed = 0
    for parm in aovs.parms():
        name = parm.name()
        if not name.endswith("precision"):
            continue
        match = pattern.match(parm.evalAsString())
        if not match:
            continue
        half = beauty_half if name == "beautyprecision" else other_half
        wanted = match.group(1) + ("h" if half else "f")
        if wanted != parm.evalAsString() and _menu_has_value(parm, wanted):
            if _pset(aovs, name, wanted, log_callback, quiet=True):
                changed += 1
    return changed


# ------------------------------------------------------------
# Fix erreur = aucun des anciens noms de toggles n'existait sur H22, les AOV étaient ignorés en silence
def _create_aov_chain(stage, prev, cfg, log_callback):
    aovs = _get_or_create_node(stage, "karmastandardrendervars", "standard_aovs")
    _safe_connect(aovs, prev)

    aov_flag_map = {
        "aov_ao": (("ambientocclusion",), ("format_ao", "format_ambientocclusion", "aov_ao")),
        "aov_depth": (("hitPz",), ("format_depth", "format_z", "format_pz", "aov_depth")),
        "aov_normal": (("hitN",), ("format_normal", "format_n", "aov_normal")),
        "aov_position": (("hitP",), ("format_position", "format_p", "aov_position")),
        "aov_albedo": (("albedo",), ("format_albedo", "format_basecolor", "format_base_color", "aov_albedo")),
        "aov_emission": (("combinedemission",), ("format_emission", "format_emit", "aov_emission")),
        "aov_diffuse": (("combineddiffuse",), ("format_diffuse", "format_diff", "aov_diffuse")),
        "aov_specular": (("combinedglossyreflection",), ("format_specular", "format_spec", "aov_specular")),
        "aov_motion": (("motionvectors",), ("format_motionvector", "format_motion", "format_mv", "aov_motion")),
        "aov_shadow": (("shadow",), ("format_shadow", "format_shadowmask", "aov_shadow")),
        "aov_id": (("primid", "element"), ("format_id", "format_objectid", "format_cryptomatte", "aov_id")),
    }

    for cfg_key, (names, legacy_names) in aov_flag_map.items():
        if cfg_key == "aov_ao":
            enabled = bool(cfg.get("aov_ao", cfg.get("enable_ao", False)))
        else:
            enabled = bool(cfg.get(cfg_key, False))
        value = 1 if enabled else 0
        applied = False
        for name in names:
            if aovs.parm(name) is not None:
                applied = _pset(aovs, name, value, log_callback, quiet=True) or applied
        if not applied:
            _set_first_existing_parm(aovs, legacy_names, value, log_callback)

    # Beauty follows the EXR precision of the Export tab; the other passes follow the AOV option.
    beauty_half = (cfg.get("exr_precision", "16-bit float") == "16-bit float")
    other_half = bool(cfg.get("aov_half_precision", False))
    if not _apply_aov_precision(aovs, beauty_half, other_half, log_callback):
        _set_first_existing_parm(
            aovs,
            ("halfprecision", "half", "half_float", "halfFloat"),
            1 if other_half else 0,
            log_callback,
        )

    return aovs


# --------------------------------------------------
def _set_menu_token(node, parm_names, token, log_callback, label=None):
    for name in parm_names:
        parm = node.parm(name)
        if parm is None:
            continue
        if not _menu_has_value(parm, token):
            log_callback("[WARN] {}: '{}' is not available on {}.{}".format(label or name, token, node.name(), name))
            return False
        return _pset(node, name, token, log_callback, quiet=True)
    return False


# ------------------------------------------------------------
def _create_render_settings(stage, cam_path, prev, cfg, log_callback):
    ks = _get_or_create_node(stage, "karmarendersettings", "karma_settings")
    engine = cfg["engine"]
    _pset(ks, "engine", engine, log_callback, quiet=True)
    _pset(ks, "camera", cam_path, log_callback)

    # CPU uses path traced samples too (see convergence_mode below)
    if ks.parm("pathtracedsamples") is not None:
        _pset(ks, "pathtracedsamples", cfg["samples"], log_callback)
        if engine == "cpu":
            _set_menu_token(ks, ("convergence_mode",), "Path Traced", log_callback, label="Convergence")
    elif engine == "xpu":
        _set_first_existing_parm(ks, ("pathtracesamples",), cfg["samples"], log_callback)
    else:
        _set_first_existing_parm(ks, ("primarysamples", "samplesperpixel"), cfg["samples"], log_callback)

    if not _set_menu_token(ks, ("res_mode",), "manual", log_callback, label="Resolution mode"):
        _pset(ks, "resolutionmode", "manual", log_callback, quiet=True)
        _pset(ks, "resMenu", "specific", log_callback, quiet=True)
    res_parm = ks.parmTuple("resolution")
    if res_parm is not None:
        for p in res_parm:
            if p.isLocked(): p.lock(False)
            p.deleteAllKeyframes()
        try: res_parm.set((cfg["res_x"], cfg["res_y"]))
        except hou.Error: pass

    denoise_tokens = {"None": "off", "Optix (GPU)": "optix", "OIDN (CPU)": "oidn"}
    denoiser = ks.parm("denoiser")
    if denoiser is not None:
        token = denoise_tokens.get(cfg["denoiser"], "off")
        if not _menu_has_value(denoiser, token):
            token = {"off": "0", "optix": "1", "oidn": "2"}[token]
        _pset(ks, "denoiser", token, log_callback, quiet=True)

    pixel_filter = str(cfg["pixel_filter"])
    pf_parm = ks.parm("pixelfilter")
    if pf_parm is not None:
        if _menu_has_value(pf_parm, pixel_filter):
            _pset(ks, "pixelfilter", pixel_filter, log_callback, quiet=True)
        else:
            try:
                has_menu = bool(pf_parm.menuItems())
            except hou.OperationFailed:
                has_menu = False
            if has_menu:
                log_callback("[WARN] Pixel filter '{}' not available in this Houdini, keeping '{}'.".format(
                    pixel_filter, pf_parm.evalAsString()))
            else:
                _pset(ks, "pixelfilter", '["{}", {{}}]'.format(pixel_filter), log_callback, quiet=True)

    _set_first_existing_parm(ks, ("diffuselimit", "diffuse_limit"), float(cfg["diffuse_limit"]), log_callback)
    _set_first_existing_parm(ks, ("reflectionlimit", "reflectlimit", "specularlimit"), float(cfg["reflection_limit"]), log_callback)
    _set_first_existing_parm(
        ks,
        ("refractionlimit", "transmissionlimit", "transmitlimit", "refractlimit"),
        float(cfg["transmission_limit"]),
        log_callback,
    )
    _set_first_existing_parm(ks, ("colorlimit", "indirectlimit"), float(cfg.get("color_limit", 10.0)), log_callback)

    noise_lvl = float(cfg.get("noise_level", 0.01))
    _set_first_existing_parm(ks, ("varianceaa_thresh", "oracle_variance", "adaptivethreshold", "noiselevel", "variancethreshold"), noise_lvl, log_callback)

    vol_limit = int(cfg.get("volume_limit", 8))
    if cfg.get("enable_clouds") and cfg.get("enable_fog") and vol_limit < 8:
        vol_limit = max(vol_limit, 8)
    _set_first_existing_parm(ks, ("volumelimit", "volume_limit", "volumeraylimit"), float(vol_limit), log_callback)

    out_path = _normalize_output_path_extension(cfg["out_path"], cfg["output_format"])
    _set_first_existing_parm(ks, ("picture",), out_path, log_callback)
    if cfg.get("enable_aovs", False):
        _set_first_existing_parm(ks, ("splitrendervars",), 0 if cfg.get("aov_multilayer", True) else 1, log_callback)

    _safe_connect(ks, prev)
    return ks


# ------------------------------------------------------------------------
def _create_render_rop(stage, lop_input, cfg, log_callback):
    rp = _get_or_create_node(stage, "usdrender_rop", "render_to_disk")
    out_path = _normalize_output_path_extension(cfg["out_path"], cfg["output_format"])

    _pset(rp, "loppath", lop_input.path(), log_callback)
    _pset(rp, "outputimage", out_path, log_callback)
    _pset(rp, "trange", cfg["trange"], log_callback)
    _pset(rp, "f1", float(cfg["f_start"]), log_callback)
    _pset(rp, "f2", float(cfg["f_end"]), log_callback)

    delegate = "BRAY_HdKarmaXPU" if cfg["engine"] == "xpu" else "BRAY_HdKarma"
    renderer = rp.parm("renderer")
    if renderer is not None and _menu_has_value(renderer, delegate):
        _pset(rp, "renderer", delegate, log_callback, quiet=True)
    ks_node = stage.node("karma_settings")
    if ks_node is not None and ks_node.parm("primpath") is not None:
        _pset(rp, "rendersettings", ks_node.parm("primpath").evalAsString(), log_callback, quiet=True)

    _set_first_existing_parm(rp, ("pictureformat", "outputformat", "imageformat"), str(cfg["output_format"]).lower(), log_callback)
    if str(cfg["output_format"]).upper() == "EXR":
        exr_is_half = (cfg.get("exr_precision", "16-bit float") == "16-bit float")
        _set_first_existing_parm(rp, ("halfprecision", "half", "exrhalf"), 1 if exr_is_half else 0, log_callback)
        _set_first_existing_parm(
            rp,
            ("exrdatatype", "exr_pixeltype", "exrprecision", "datatype"),
            "half" if exr_is_half else "float",
            log_callback,
        )

    _safe_connect(rp, lop_input)
    return rp


# ----- Material Linker ----------------------------------------
# Data lives in two multiparms: files (enabled_#, createprims_#, primpath_#, filepath_#, filerefprimpath_#)
# and links (link_enabled_#, link_id_#, link_prim_# = the material, link_includes_# = its prims, one per line).
# Written directly, so SideFX's UI module stays out of it.

MATERIAL_LINK_TYPE = "materialdirect"
MATERIAL_DEFAULT_ROOT = "/materials"


# --------------------------------------------------
def _material_linker_node(stage):
    if stage is None:
        return None
    node = stage.node("material_linker")
    if node is not None and _base_node_type_name(node) == "materiallinker":
        return node
    return None

# ----------------------------------------------------------------------
def _get_or_create_material_linker(stage):
    node = _material_linker_node(stage)
    if node is None:
        node = stage.createNode("materiallinker", "material_linker")
    _mark_tool_node(node)
    return node


# ----------------------------------------------------------------
def _insert_material_linker_in_chain(stage, linker, log_callback):
    matlib = stage.node("mtlx_materials")
    if matlib is None:
        log_callback("[WARN] No material library found: build the environment first.")
        return False

    if linker.input(0) != matlib:
        for node in matlib.outputs():
            if node == linker:
                continue
            for index, source in enumerate(node.inputs()):
                if source == matlib:
                    node.setInput(index, linker)
        linker.setInput(0, matlib)
    return True


# ----------------------------------------
# (index, dst_prim_path, file_path, file_prim_path) per reference.
# The multiparm layout is read and written by name: another Houdini version may rename it.
def _linker_set(linker, pattern, index, value):
    parm = linker.parm(pattern.format(index))
    if parm is None:
        raise ValueError("the Material Linker of this Houdini has no '{}' parameter (found on {})".format(
            pattern.format(index), linker.type().nameWithCategory()))
    parm.set(value)


# ----------------------------------------
def _linker_references(linker):
    refs = []
    count = linker.parm("num_files").evalAsInt() if linker.parm("num_files") is not None else 0
    for i in range(1, count + 1):
        dst = linker.parm("primpath_{}".format(i))
        src = linker.parm("filepath_{}".format(i))
        ref_prim = linker.parm("filerefprimpath_{}".format(i))
        if dst is None or src is None or ref_prim is None:
            continue
        refs.append((i, dst.evalAsString(), src.evalAsString(), ref_prim.evalAsString()))
    return refs


# ----------------------------------------
# (index, material_path, [prims]) per rule.
def _linker_rules(linker):
    rules = []
    count = linker.parm("num_links").evalAsInt() if linker.parm("num_links") is not None else 0
    for i in range(1, count + 1):
        owner = linker.parm("link_prim_{}".format(i))
        includes_parm = linker.parm("link_includes_{}".format(i))
        if owner is None or includes_parm is None:
            continue
        includes = [p.strip() for p in includes_parm.evalAsString().splitlines() if p.strip()]
        rules.append((i, owner.evalAsString().strip(), includes))
    return rules


# ------------------------------------------------------------
def _unique_material_path(linker, wanted):
    taken = set(dst for _, dst, _, _ in _linker_references(linker))
    try:
        stage = linker.stage()
    except hou.Error:
        stage = None

    def is_free(path):
        if path in taken:
            return False
        if stage is not None and stage.GetPrimAtPath(path):
            return False
        return True

    if is_free(wanted):
        return wanted
    match = re.search(r"(\d+)$", wanted)
    stem = wanted[:match.start()] if match else wanted
    number = int(match.group(1)) + 1 if match else 2
    while not is_free("{}{}".format(stem, number)):
        number += 1
    return "{}{}".format(stem, number)


# ----------------------------------------
# Reference a material from a file and return its prim path. Same file and source prim reuses the reference.
def _linker_add_reference(linker, file_path, file_prim_path, label):
    if any(_has_expression(text) for text in (file_path, file_prim_path, label)):
        raise ValueError("refusing a material path that contains an expression")
    for _, dst, ref_file, ref_prim in _linker_references(linker):
        if ref_file == file_path and ref_prim == file_prim_path:
            return dst

    wanted = hou.lop.makeValidPrimPath("{}/{}".format(MATERIAL_DEFAULT_ROOT, label))
    dst_path = _unique_material_path(linker, wanted)

    folder = linker.parm("num_files")
    if folder is None:
        raise ValueError("the Material Linker of this Houdini has no 'num_files' parameter")
    folder.insertMultiParmInstance(folder.evalAsInt())
    index = folder.evalAsInt()
    _linker_set(linker, "enabled_{}", index, 1)
    _linker_set(linker, "createprims_{}", index, 1)
    _linker_set(linker, "filepath_{}", index, file_path)
    _linker_set(linker, "filerefprimpath_{}", index, file_prim_path)
    _linker_set(linker, "primpath_{}", index, dst_path)
    return dst_path


# ------------------------------------
def _linker_unassign(linker, prim_paths):
    prim_set = set(prim_paths)
    removed = 0
    folder = linker.parm("num_links")
    # Walk backwards so deleting a rule does not shift the indices still to visit.
    for index, owner, includes in reversed(_linker_rules(linker)):
        kept = [p for p in includes if p not in prim_set]
        if len(kept) == len(includes):
            continue
        removed += len(includes) - len(kept)
        if kept:
            linker.parm("link_includes_{}".format(index)).set("\n".join(kept))
        else:
            folder.removeMultiParmInstance(index - 1)
    return removed


# ------------------------------------------------------------
# Bind the material to the prims. A prim has one material, so it leaves its previous rule.
def _linker_assign(linker, material_path, prim_paths):
    prim_paths = [p for p in prim_paths if p]
    if not prim_paths:
        return 0
    _linker_unassign(linker, prim_paths)

    for index, owner, includes in _linker_rules(linker):
        if owner == material_path:
            merged = includes + [p for p in prim_paths if p not in includes]
            linker.parm("link_includes_{}".format(index)).set("\n".join(merged))
            return len(prim_paths)

    folder = linker.parm("num_links")
    if folder is None:
        raise ValueError("the Material Linker of this Houdini has no 'num_links' parameter")
    folder.insertMultiParmInstance(folder.evalAsInt())
    index = folder.evalAsInt()
    _linker_set(linker, "link_enabled_{}", index, 1)
    _linker_set(linker, "link_id_{}", index, str(uuid.uuid4()))
    _linker_set(linker, "link_type_{}", index, MATERIAL_LINK_TYPE)
    _linker_set(linker, "link_prim_{}", index, material_path)
    _linker_set(linker, "link_includes_{}", index, "\n".join(prim_paths))
    _linker_set(linker, "link_excludes_{}", index, "")
    _linker_set(linker, "link_reversed_{}", index, 0)
    _linker_set(linker, "link_ispathexpression_{}", index, 0)
    return len(prim_paths)

AMD_LIBRARY_URL = "https://api.matlib.gpuopen.com/api"


# ------------------------------------------------------------
# ATTENTION -> la source AMD de Houdini fait ses requêtes sans timeout (et sa liste sans vérification TLS),
# on teste donc la connexion avant, sinon une machine hors ligne gèle l'interface. Renvoie (ok, reason).
def _amd_library_reachable(timeout=6.0):
    try:
        import requests
    except ImportError:
        return True, ""  # cannot check: let Houdini try
    try:
        response = requests.get(AMD_LIBRARY_URL + "/materials/count/", timeout=timeout)
        response.raise_for_status()
        return True, ""
    except requests.RequestException as exc:
        return False, str(exc).splitlines()[0][:140]


# ----- Trust checks ----------------------------------------
# ATTENTION -> expandString exécute les backticks (`system("...")`) et un parm aussi quand son node calcule.
# Tout ce que l'utilisateur n'a pas tapé (drop, métadonnées de catalogue) est refusé s'il en contient.


# --------------------------------------------------
def _has_expression(text):
    return "`" in str(text)

_PRIM_PATH_RE = re.compile(r"^/[A-Za-z0-9_/]*$")

_private_temp = None


# ------------------------------------------------------------
# ATTENTION -> des noms prévisibles dans le temp partagé permettent à un autre utilisateur de pré-créer un lien,
# d'où un dossier privé par session
def _private_temp_dir():
    global _private_temp
    if _private_temp is None or not os.path.isdir(_private_temp):
        _private_temp = tempfile.mkdtemp(prefix="bsm_karma_")
        atexit.register(shutil.rmtree, _private_temp, True)
    return _private_temp

CATALOG_SOURCE_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".usd", ".usda", ".usdc", ".usdz")
AMD_SOURCE_ID = "AMD MaterialX Library"


# --------------------------------------------------
def _is_inside(folder, path):
    folder = os.path.normcase(os.path.realpath(folder))
    path = os.path.normcase(os.path.realpath(path))
    try:
        return os.path.commonpath([folder, path]) == folder
    except ValueError:  # different drives
        return False


# ------------------------------------------------------------
# Reason a payload's source must not be built, or "". An AMD source with a payload-supplied folder would
# extract a package wherever the payload says, so it must be the folder connected in the Materials tab.
def _catalog_source_problem(identifier, args, amd_folder):
    if _has_expression(identifier) or _has_expression(args):
        return "the source contains an expression"
    if identifier == AMD_SOURCE_ID:
        if not amd_folder:
            return "connect the AMD MaterialX Library from this tab first"
        if os.path.normcase(os.path.realpath(hou.text.expandString(str(args)))) != os.path.normcase(os.path.realpath(amd_folder)):
            return "the download folder is not the one connected in this tab"
        return ""
    path = hou.text.expandString(str(identifier))
    if path.lower().endswith(CATALOG_SOURCE_SUFFIXES) and os.path.isfile(path):
        return ""
    return "unsupported material source"

# wrapper layer -> the .mtlx it stands for, so a drop references the real file
_CATALOG_WRAPPERS = {}

#----------------------------------------------------------------------
def _normalized_path(path):
    return os.path.normcase(os.path.normpath(hou.text.expandString(path)))

# --------------------------------------------------------------------------------
# The gallery only takes USD stages: wrap a .mtlx in a layer that sublayers it.
def _material_catalog_file(path):
    if os.path.splitext(path)[1].lower() != ".mtlx":
        return path
    if "@" in path or "\n" in path or "\r" in path:
        raise ValueError("the path contains a character that cannot be written in a USD asset reference")
    key = hashlib.md5(path.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    wrapper = os.path.join(_private_temp_dir(), "catalog_{}.usda".format(key)).replace("\\", "/")
    with open(wrapper, "w", encoding="utf-8") as handle:
        handle.write("#usda 1.0\n(\n    subLayers = [@{}@]\n)\n".format(path.replace("\\", "/")))
    _CATALOG_WRAPPERS[_normalized_path(wrapper)] = path
    return wrapper


# ------------------------------------------------------------------------------------------
# Drag payload to material descriptors (label, file_path, prim_path, id). The payload is untrusted, any
# application can start a drag, and so is remote catalog metadata: see the trust checks. `source_factory` is for
# tests.
def _parse_catalog_drop(json_text, amd_folder=None, source_factory=None):
    factory = source_factory or hou.AssetGalleryDataSource
    data = json.loads(json_text)
    assets = []
    failures = []
    fields = zip(
        data.get("ids", []), data.get("assettypes", []), data.get("labels", []),
        data.get("filepaths", []), data.get("asset_data", []), data.get("sources", []),
    )
    for ident, asset_type, label, file_path, asset_data, source in fields:
        if asset_type != "material":
            continue
        try:
            blind = json.loads(asset_data) if asset_data else {}
        except ValueError:
            blind = {}
        texts = (ident, label, file_path, blind.get("name", ""), blind.get("refprimpath", ""))
        if any(_has_expression(text) for text in texts):
            failures.append("{}: refused, a value contains an expression".format(label))
            continue
        problem = _catalog_source_problem(source[0], source[1], amd_folder)
        if problem:
            failures.append("{}: {}".format(label, problem))
            continue
        try:
            source_obj = factory(source[0], source[1])
            if source[0] == AMD_SOURCE_ID:
                # The remote metadata decides where the package is written: it must stay in the download folder.
                target = source_obj.filePath(ident)
                if not target or _has_expression(target) or not _is_inside(amd_folder, hou.text.expandString(target)) \
                        or not _is_inside(amd_folder, hou.text.expandString(file_path)):
                    failures.append("{}: the material path is outside the download folder".format(label))
                    continue
            error = source_obj.prepareItemForUse(ident)
        except hou.Error as exc:
            error = str(exc)
        if error:
            failures.append("{}: {}".format(label, error))
            continue
        assets.append({
            "label": blind.get("name", label),
            "file_path": _CATALOG_WRAPPERS.get(_normalized_path(file_path), file_path),
            "prim_path": blind.get("refprimpath", ""),
            "id": ident,
        })
    return assets, failures


# ------------------------------------
def _list_materials_in_file(file_path):
    from pxr import Usd, UsdShade
    stage = Usd.Stage.Open(hou.text.expandString(file_path))
    if stage is None:
        return []
    return [(prim.GetName(), str(prim.GetPath())) for prim in stage.Traverse() if prim.IsA(UsdShade.Material)]

STAGE_TARGET_LIMIT = 5000


# --------------------------------------------------
def _stage_target_prims(stage, limit=STAGE_TARGET_LIMIT):
    from pxr import UsdGeom, UsdShade
    # /World/Environment is the tool's own fog and clouds
    skip_roots = ("/Render", "/lights", "/cameras", "/World/Environment", MATERIAL_DEFAULT_ROOT)
    result = []
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if any(path == root or path.startswith(root + "/") for root in skip_roots):
            continue
        if prim.IsA(UsdShade.Material) or prim.IsA(UsdShade.Shader):
            continue
        if not (prim.IsA(UsdGeom.Gprim) or prim.IsA(UsdGeom.Xform) or prim.IsA(UsdGeom.Scope)
                or prim.IsA(UsdGeom.PointInstancer)):
            continue
        result.append((path, str(prim.GetPath().GetParentPath()), prim.GetTypeName()))
        if len(result) >= limit:
            break
    return result


# ------------------------------------------------------------
def _bound_material_name(stage, prim_path):
    from pxr import UsdShade
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        return ""
    material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    return material.GetPath().name if material else ""

#--------------------------------------------------------
def _cleanup_environment_nodes(stage, cfg, log_callback):
    all_env_nodes = {
        "physical_sky", "sky_atmosphere_linker", "env_hdri", "atmosphere_fog", "fog_xform", "assign_fog_shader",
        "cloud_geo", "cloud_xform", "quickcloudmaterial", "assign_cloud_shader", "cloud_volume", "env_merge",
        "studio_hdri", "studio_key", "fill_hdri", "key_light", "fill_light", "rim_light", "window_portal",
    }

    mode = cfg.get("scene_mode", "Environment")
    env_type = cfg.get("env_type", "Physical Sky")
    keep = set()

    if mode == "Environment":
        if env_type == "Physical Sky":
            keep.add("physical_sky")
            if cfg.get("sky_mode", 0) == 1:
                keep.add("sky_atmosphere_linker")
        else:
            keep.add("env_hdri")
        keep.add("env_merge")
        if cfg.get("enable_fog"):
            keep.add("atmosphere_fog")
        if cfg.get("enable_clouds"):
            keep.update({"cloud_geo", "cloud_xform", "quickcloudmaterial", "assign_cloud_shader"})
    elif mode == "Studio":
        keep.update({"studio_hdri", "studio_key"})
    elif mode == "3 Points":
        keep.update({"fill_hdri", "key_light", "fill_light", "rim_light"})
    elif mode == "Interior":
        if env_type == "Physical Sky":
            keep.add("physical_sky")
            if cfg.get("sky_mode", 0) == 1:
                keep.add("sky_atmosphere_linker")
        else:
            keep.add("env_hdri")
        keep.add("window_portal")

    removed = 0
    # delete in the listed order so Houdini does not warn about stranded connections
    candidates_to_remove = []
    
    for node_name in TOOL_STAGE_DELETE_ORDER:
        if node_name in all_env_nodes and node_name not in keep:
            candidates_to_remove.append(node_name)
            
    for node_name in all_env_nodes:
        if node_name not in keep and node_name not in candidates_to_remove:
            candidates_to_remove.append(node_name)

    for node_name in candidates_to_remove:
        node = stage.node(node_name)
        if node is None or not _is_tool_node_candidate(node, node_name):
            continue
        try:
            node.destroy()
            removed += 1
        except hou.OperationFailed:
            log_callback(f"[WARN] Could not remove previous node: {node_name}")

    if removed:
        log_callback(f"[INFO] Cleanup: removed {removed} obsolete environment node(s).")


# ----------------------------------------
# bug trouvé et fixé: layoutChildren() sur tout /stage déplaçait aussi les nodes de l'utilisateur,
# on ne range plus que ceux de l'outil
def _layout_tool_nodes(stage):
    nodes = [node for node in stage.children() if _is_tool_node_candidate(node, node.name())]
    if nodes:
        stage.layoutChildren(nodes)


# --------------------------------------------------------------------------------
# Merge the geometry LOP with the environment so materials can bind to it.
# No source selected: the chain is left as it was and an old merge is removed.
def _merge_geometry_source(stage, env_tip, cfg, log_callback):
    geo_path = (cfg.get("geo_source") or "").strip()
    geo_node = hou.node(geo_path) if geo_path else None

    usable = (
        geo_node is not None
        and geo_node.type().category() == hou.lopNodeTypeCategory()
        and geo_node.parent() == stage
        and not _is_tool_node_candidate(geo_node, geo_node.name())
    )
    if not usable:
        if geo_path:
            log_callback("[WARN] Geometry source not usable: {}".format(geo_path))
        _remove_tool_node(stage, "geo_merge", log_callback)
        return env_tip

    merge = _get_or_create_node(stage, "merge", "geo_merge")
    try:
        for i in range(len(merge.inputs())):
            merge.setInput(i, None)
        merge.setInput(0, env_tip)
        merge.setInput(1, geo_node)
    except hou.OperationFailed as exc:
        log_callback("[WARN] Could not merge geometry source {}: {}".format(geo_path, exc))
        return env_tip
    return merge


# --------------------------------------------------------------------------------
def setup_karma_environment(cfg, log_callback):
    log_callback(f"--- Building: {cfg['scene_mode']} (Houdini {hou.applicationVersionString()}) ---")
    try:
        if hou.applicationVersion()[0] < 21:
            log_callback("[WARN] Written for Houdini 21 and 22: some Karma parameters may be missing in this version.")
    except (hou.Error, TypeError, IndexError):
        pass
    stage = _get_or_create_stage()
    cam, cam_path = _resolve_render_camera(stage, cfg, log_callback)

    mode = cfg.get("scene_mode", "Environment")
    env_type = cfg.get("env_type", "Physical Sky")
    _cleanup_environment_nodes(stage, cfg, log_callback)
    
    if mode == "Environment":
        if env_type == "Physical Sky":
            env_base = _create_physical_sky(stage, cam, cfg, log_callback)
        else:
            env_base = _create_dome_light(stage, cam, cfg["hdri_int"], cfg["hdri_path"], log_callback, name="env_hdri", hdri_opts=cfg)
            
        fog = cloud = None
        if cfg["enable_fog"]:
            try:
                fog = _create_fog_branch(stage, cam, cfg, log_callback)
            except hou.OperationFailed as exc:
                log_callback("[WARN] Fog skipped: {}".format(exc))
        if cfg["enable_clouds"]:
            try:
                cloud = _create_cloud_branch(stage, cam, cfg, log_callback)
            except hou.OperationFailed as exc:
                log_callback("[WARN] Clouds skipped (a node type may be missing in this Houdini): {}".format(exc))
        env_tip = _create_environment_merge(stage, env_base, fog, cloud)
        
    elif mode == "Studio":
        dome = _create_dome_light(stage, cam, cfg["hdri_int"], cfg["hdri_path"], log_callback, name="studio_hdri", hdri_opts=cfg)
        key = _create_area_light(stage, dome, cfg["area_int"], log_callback, name="studio_key", pos=(3, 4, 3), rot=(-45, 30, 0))
        env_tip = key
        
    elif mode == "3 Points":
        dome = _create_dome_light(stage, cam, float(cfg["hdri_int"])*0.2, cfg["hdri_path"], log_callback, name="fill_hdri", hdri_opts=cfg)
        key = _create_area_light(stage, dome, float(cfg["area_int"]), log_callback, name="key_light", pos=(3, 4, 3), rot=(-45, 30, 0))
        fill = _create_area_light(stage, key, float(cfg["area_int"])*0.4, log_callback, name="fill_light", pos=(-4, 2, 2), rot=(-20, -45, 0))
        rim = _create_area_light(stage, fill, float(cfg["area_int"])*1.5, log_callback, name="rim_light", pos=(-2, 3, -4), rot=(-30, -150, 0))
        env_tip = rim
        
    elif mode == "Interior":
        if env_type == "Physical Sky":
            env_base = _create_physical_sky(stage, cam, cfg, log_callback)
        else:
            env_base = _create_dome_light(stage, cam, cfg["hdri_int"], cfg["hdri_path"], log_callback, name="env_hdri", hdri_opts=cfg)
        window = _create_area_light(stage, env_base, float(cfg["area_int"]), log_callback, name="window_portal", pos=(5, 2, 0), rot=(0, 90, 0))
        env_tip = window
        
    else:
        env_tip = cam

    env_tip = _merge_geometry_source(stage, env_tip, cfg, log_callback)

    mat = _create_material_library(stage, env_tip, cfg, log_callback)

    linker = _material_linker_node(stage)
    if linker is not None:
        _safe_connect(linker, mat)
        mat = linker

    if cfg["enable_aovs"]:
        upstream = _create_aov_chain(stage, mat, cfg, log_callback)
    else:
        _remove_tool_node(stage, "standard_aovs", log_callback, "AOVs disabled")
        upstream = mat
    ks = _create_render_settings(stage, cam_path, upstream, cfg, log_callback)
    _create_render_rop(stage, ks, cfg, log_callback)

    _layout_tool_nodes(stage)
    _debug_stage_dump(stage)

    # le node karma settings reste le node actif et sélectionné après un build
    if ks:
        ks.setDisplayFlag(True)
        ks.setSelected(True, True)
        
    log_callback(f"[OK] Karma Ready. Engine: {cfg['engine'].upper()} | Env: {env_type}")


# ==========================================================
# INTERFACE GRAPHIQUE
# ==========================================================


# --------------------------------------------------------
# bug trouvé et fixé: super(Classe, self) casse après importlib.reload (TypeError sur l'ancien dialogue),
# d'où super() sans argument partout 🙂
class KarmaBuilderUI(QtWidgets.QDialog):
    CAMERA_CREATE_LABEL = "Create New Camera"
    MATERIAL_SOURCES = ["AMD MaterialX Library", "Houdini Default Catalog", "USD / MaterialX File..."]
    NO_GEO_SOURCE_LABEL = "(none)"

    # --------------------------------------------------
    def __init__(self, parent=None):
        # Fix erreur = hou.qt.mainWindow() en argument par défaut était évalué à l'import, on le résout à l'appel
        if parent is None:
            parent = hou.qt.mainWindow()
        super().__init__(parent)
        self.setWindowTitle("BSM Karma Builder {}".format(SCRIPT_VERSION))
        self.resize(720, 840)
        self.setMinimumSize(600, 750)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        self.setStyleSheet(BSM_STYLE)
        # child of the main window: without this a closed dialog lives until Houdini exits
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

        _debug_session_header()
        self._released = False
        self._pending_logs = []
        self._amd_folder = None
        self._release_errors = []
        self._karma_scene_viewer = None
        self._parm_pane_tab = None
        self._material_source_changed = False
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
        
        sky_preset_names = ["-- Custom --"] + list(self.sky_presets.keys())
        
        main_layout = QtWidgets.QVBoxLayout()
        tabs = QtWidgets.QTabWidget()

        def _wrap_tab(widget):
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            scroll.setWidget(widget)
            return scroll
        
        # --- TAB 1: MAIN ---
        tab_main = QtWidgets.QWidget()
        form_main = QtWidgets.QFormLayout(tab_main)

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
        self.combo_time_preset.addItems(sky_preset_names)
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
        self.spin_resX.setFixedWidth(55)
        self.spin_resY.setFixedWidth(55)
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
        self.btn_refresh_cameras.setFixedWidth(92)
        self.btn_refresh_cameras.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.btn_refresh_cameras.clicked.connect(self.refresh_stage_cameras)
        self.btn_look_through = QtWidgets.QPushButton("Look Through")
        self.btn_look_through.setFixedWidth(100)
        self.btn_look_through.setToolTip("Lock a viewport to the render camera (builds first if needed).")
        self.btn_look_through.clicked.connect(self.on_look_through_camera)
        lay_camera_select.addWidget(self.combo_camera)
        lay_camera_select.addWidget(self.btn_refresh_cameras)
        lay_camera_select.addWidget(self.btn_look_through)
        lay_camera_select.setStretch(0, 1)
        form_main.addRow("Render Camera:", self.w_camera_select)

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
        self.chk_cam_from_viewport = QtWidgets.QCheckBox("Match current viewport")
        self.chk_cam_from_viewport.setToolTip(
            "Copy the position and rotation of the active viewport onto the new camera at each build.\n"
            "Left off, the camera keeps the position it was given the first time.")
        lay_new_camera.addWidget(self.spin_cam_focal)
        lay_new_camera.addWidget(self.chk_cam_from_viewport)
        lay_new_camera.addStretch(1)
        form_main.addRow("New Camera:", self.w_new_camera)

        self.btn_clear_all_main = QtWidgets.QPushButton("Clear All Tool Nodes")
        self.btn_clear_all_main.setStyleSheet(_btn_style(_C["danger"]))
        self.btn_clear_all_main.clicked.connect(self.on_clear_all)
        form_main.addRow("", self.btn_clear_all_main)

        tabs.addTab(_wrap_tab(tab_main), "Scene")
        
        # --- TAB 2: LIGHTING & SKY ---
        tab_lights = QtWidgets.QWidget()
        layout_lights = QtWidgets.QVBoxLayout(tab_lights)
        
        grp_base = QtWidgets.QGroupBox("General Lights / HDRI")
        grp_base.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        self.form_base = QtWidgets.QFormLayout(grp_base)
        self.sld_hdri_int = FloatSlider(0.0, 20.0, 1.0)
        self.sld_area_int = FloatSlider(0.0, 100.0, 10.0)
        self.form_base.addRow("HDRI / Dome Intensity:", self.sld_hdri_int)
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
        self.form_base.addRow("HDRI Texture Path:", self.w_hdri_path)

        self.sld_hdri_ev = FloatSlider(-8.0, 8.0, 0.0)
        self.form_base.addRow("HDRI Exposure (EV):", self.sld_hdri_ev)

        self.sld_hdri_rot = FloatSlider(-180.0, 180.0, 0.0)
        self.form_base.addRow("HDRI Rotation Y:", self.sld_hdri_rot)

        self.sld_hdri_sat = FloatSlider(0.0, 2.0, 1.0)
        self.form_base.addRow("HDRI Saturation:", self.sld_hdri_sat)

        self.spin_hdri_temp = QtWidgets.QSpinBox()
        self.spin_hdri_temp.setRange(2500, 12000)
        self.spin_hdri_temp.setSingleStep(100)
        self.spin_hdri_temp.setValue(6500)
        self.form_base.addRow("HDRI Temperature (K):", self.spin_hdri_temp)

        self.sld_hdri_tint = FloatSlider(-1.0, 1.0, 0.0)
        self.form_base.addRow("HDRI Tint:", self.sld_hdri_tint)

        self.lbl_hdri_preview = QtWidgets.QLabel("HDRI preview")
        self.lbl_hdri_preview.setMinimumHeight(160)
        self.lbl_hdri_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_hdri_preview.setScaledContents(True)
        self.lbl_hdri_preview.setObjectName("hdriPreview")
        self.form_base.addRow("HDRI Preview:", self.lbl_hdri_preview)

        layout_lights.addWidget(grp_base)
        
        self.grp_sky = QtWidgets.QGroupBox("Karma Physical Sky")
        self.grp_sky.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        form_sky = QtWidgets.QFormLayout(self.grp_sky)
        self.form_sky = form_sky
        
        self.combo_sky_preset = QtWidgets.QComboBox()
        self.combo_sky_preset.addItems(sky_preset_names)
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
        lay_azim_compass.addWidget(self.compass_widget)
        lay_azim_compass.addWidget(self.altitude_widget)
        lay_azim_compass.addStretch(1)
        
        form_sky.addRow("Solar Altitude:", self.sld_sky_elev)
        form_sky.addRow("Solar Direction:", self.sld_sky_azim)
        self.chk_sky_follow_view = QtWidgets.QCheckBox("Add the viewport heading to the direction at each build")
        self.chk_sky_follow_view.setToolTip(
            "Off: the sun sits at the Solar Direction shown by the compass.\n"
            "On: the Y rotation of the active Scene Viewer is added, so the sun turns with the view.")
        form_sky.addRow("Align to View:", self.chk_sky_follow_view)
        form_sky.addRow("", lay_azim_compass)

        self.sld_sun_int = FloatSlider(0.0, 50.0, 1.0)
        self.sld_sun_size = FloatSlider(0.01, 10.0, 0.53)
        form_sky.addRow("Sun Intensity:", self.sld_sun_int)
        form_sky.addRow("Angular Size:", self.sld_sun_size)
        
        self.spin_sun_temp = QtWidgets.QSpinBox()
        self.spin_sun_temp.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.spin_sun_temp.setRange(1500, 20000)
        self.spin_sun_temp.setSingleStep(100)
        self.spin_sun_temp.setValue(5500)
        self.spin_sun_temp.setStyleSheet(_slider_stylesheet())
        
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
        form_sky.addRow("Ambient Tint (Sky/Fog):", lay_rgb_amb)

        self.sld_turbidity = FloatSlider(1.0, 10.0, 3.0)
        self.sld_sky_int = FloatSlider(0.0, 30.0, 1.0)
        form_sky.addRow("Turbidity (Classic):", self.sld_turbidity)
        form_sky.addRow("Sky Intensity:", self.sld_sky_int)
        self.sld_hz_blur = FloatSlider(0.0, 45.0, 5.0)
        form_sky.addRow("Horizon Blur (Classic):", self.sld_hz_blur)
        
        self.sld_atm_rayleigh = FloatSlider(0.0, 5.0, 1.0)
        self.sld_atm_mie = FloatSlider(0.0, 5.0, 1.0)
        form_sky.addRow("Atmosphere Blue (Rayleigh):", self.sld_atm_rayleigh)
        form_sky.addRow("Atmosphere Haze (Mie):", self.sld_atm_mie)

        layout_lights.addWidget(self.grp_sky)
        layout_lights.addStretch(1)
        tabs.addTab(_wrap_tab(tab_lights), "Lighting")
        
        # --- TAB VOLUMETRICS ---
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
        self.combo_cloud_preset = QtWidgets.QComboBox()
        self.combo_cloud_preset.addItems(["-- Custom --"] + list(self.cloud_presets.keys()))
        self.combo_cloud_preset.currentIndexChanged.connect(self.apply_cloud_preset)
        form_cloud.addRow("Cloud Preset:", self.combo_cloud_preset)
        self.sld_cloud_density = FloatSlider(0.0, 10.0, 0.20)
        self.sld_cloud_density.valueChanged.connect(
            lambda val: self.atm_widget.update_cloud(self.atm_widget.cloud_alt, val)
        )
        form_cloud.addRow("Cloud Base Density:", self.sld_cloud_density)
        self.sld_cloud_altitude = FloatSlider(10.0, 13000.0, 140.0)
        self.sld_cloud_altitude.valueChanged.connect(
            lambda val: self.atm_widget.update_cloud(val, self.atm_widget.cloud_density)
        )
        form_cloud.addRow("Cloud Altitude:", self.sld_cloud_altitude)
        self.sld_cloud_scale = FloatSlider(10.0, 1000.0, 180.0)
        form_cloud.addRow("Cloud Scale:", self.sld_cloud_scale)
        self.sld_cloud_precision = IntSlider(2, 20, 5)
        form_cloud.addRow("Cloud Voxel Size (Prec):", self.sld_cloud_precision)
        self.sld_cloud_clip = FloatSlider(0.0, 1.0, 0.35)
        form_cloud.addRow("Cloud Edge Clip:", self.sld_cloud_clip)
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
        form_cloud.addRow("Cloud Material Path:", self.w_cloud_mat_path)
        
        layout_vol_main.addWidget(self.chk_enable_clouds)
        
        self.atm_widget = AtmosphereVisualWidget()
        lay_atm_vis = QtWidgets.QHBoxLayout()
        lay_atm_vis.addWidget(self.atm_widget)
        layout_vol_main.addLayout(lay_atm_vis, 1)

        tabs.addTab(_wrap_tab(tab_volumetrics), "Atmosphere")
        
        # --- TAB MATERIALS ---
        tab_materials = QtWidgets.QWidget()
        layout_materials = QtWidgets.QVBoxLayout(tab_materials)

        grp_catalog = QtWidgets.QGroupBox("MaterialX Catalog")
        lay_catalog = QtWidgets.QVBoxLayout(grp_catalog)

        row_source = QtWidgets.QHBoxLayout()
        self.combo_mat_source = QtWidgets.QComboBox()
        self.combo_mat_source.addItems(self.MATERIAL_SOURCES)
        # the gallery opens on the shared catalog, so start on the matching entry
        self.combo_mat_source.setCurrentIndex(1)
        self.combo_mat_source.currentIndexChanged.connect(self.update_material_source_ui)
        self.btn_mat_connect = QtWidgets.QPushButton("Connect")
        self.btn_mat_connect.clicked.connect(self.on_connect_material_library)
        row_source.addWidget(QtWidgets.QLabel("Source:"))
        row_source.addWidget(self.combo_mat_source, 1)
        row_source.addWidget(self.btn_mat_connect)
        lay_catalog.addLayout(row_source)

        self.w_mat_download = QtWidgets.QWidget()
        row_download = QtWidgets.QHBoxLayout(self.w_mat_download)
        row_download.setContentsMargins(0, 0, 0, 0)
        self.line_mat_download = QtWidgets.QLineEdit(self._default_material_download_dir())
        self.line_mat_download.setToolTip("Folder where the AMD MaterialX packages are downloaded when a material is used.")
        btn_browse_mat_download = QtWidgets.QPushButton("...")
        btn_browse_mat_download.setMaximumWidth(40)
        btn_browse_mat_download.clicked.connect(self.browse_material_download_dir)
        row_download.addWidget(QtWidgets.QLabel("Download to:"))
        row_download.addWidget(self.line_mat_download, 1)
        row_download.addWidget(btn_browse_mat_download)
        lay_catalog.addWidget(self.w_mat_download)

        self.mat_gallery = self._create_material_gallery()
        if self.mat_gallery is not None:
            self.mat_gallery.setMinimumHeight(260)
            lay_catalog.addWidget(self.mat_gallery, 1)
        else:
            lbl_no_gallery = QtWidgets.QLabel(
                "The material catalog widget is not available in this Houdini build.\n"
                "Use 'Assign MaterialX / USD File...' below instead.")
            lbl_no_gallery.setAlignment(QtCore.Qt.AlignCenter)
            lay_catalog.addWidget(lbl_no_gallery)

        self.lbl_mat_status = QtWidgets.QLabel(
            "Showing Houdini's current material catalog. Pick another source and press Connect to switch.")
        self.lbl_mat_status.setWordWrap(True)
        self.lbl_mat_status.setStyleSheet("color: {};".format(_C["text_muted"]))
        lay_catalog.addWidget(self.lbl_mat_status)
        layout_materials.addWidget(grp_catalog, 3)

        grp_targets = QtWidgets.QGroupBox("Assign to Geometry (drag a material onto a prim)")
        lay_targets = QtWidgets.QVBoxLayout(grp_targets)

        row_geo = QtWidgets.QHBoxLayout()
        self.combo_geo_source = PopupRefreshComboBox()
        self.combo_geo_source.popupAboutToShow.connect(self._fill_geo_source_combo)
        self.combo_geo_source.setToolTip(
            "LOP node merged with the environment so materials can be bound to its prims. "
            "Applied on the next Build.")
        self.combo_geo_source.currentIndexChanged.connect(self.on_geo_source_changed)
        self.btn_refresh_geo = QtWidgets.QPushButton("Refresh")
        self.btn_refresh_geo.clicked.connect(self.refresh_geo_sources)
        row_geo.addWidget(QtWidgets.QLabel("Geometry Source:"))
        row_geo.addWidget(self.combo_geo_source, 1)
        row_geo.addWidget(self.btn_refresh_geo)
        lay_targets.addLayout(row_geo)

        self.tree_mat_targets = MaterialTargetTree()
        self.tree_mat_targets.setMinimumHeight(170)
        self.tree_mat_targets.assetDropped.connect(self.on_material_asset_dropped)
        lay_targets.addWidget(self.tree_mat_targets, 1)

        row_mat_buttons = QtWidgets.QHBoxLayout()
        self.btn_assign_file = QtWidgets.QPushButton("Assign MaterialX / USD File...")
        self.btn_assign_file.setToolTip("Pick a .mtlx or USD file and bind its material to the selected prims.")
        self.btn_assign_file.clicked.connect(self.on_assign_material_file)
        self.btn_unassign = QtWidgets.QPushButton("Remove Assignment")
        self.btn_unassign.clicked.connect(self.on_unassign_material)
        self.btn_open_linker = QtWidgets.QPushButton("Open Material Linker")
        self.btn_open_linker.setToolTip("Select the Material Linker node to edit the rules in Houdini's own panel.")
        self.btn_open_linker.clicked.connect(self.on_open_material_linker)
        row_mat_buttons.addWidget(self.btn_assign_file)
        row_mat_buttons.addWidget(self.btn_unassign)
        row_mat_buttons.addWidget(self.btn_open_linker)
        lay_targets.addLayout(row_mat_buttons)
        layout_materials.addWidget(grp_targets, 2)

        tabs.addTab(_wrap_tab(tab_materials), "Materials")

        # --- TAB 3: QUALITY & FILTERS ---
        tab_filters = QtWidgets.QWidget()
        form_filters = QtWidgets.QFormLayout(tab_filters)
        
        self.combo_denoiser = QtWidgets.QComboBox()
        self.combo_denoiser.addItems(["None", "Optix (GPU)", "OIDN (CPU)"])
        self.combo_denoiser.setCurrentText("Optix (GPU)")
        form_filters.addRow("Image Denoiser:", self.combo_denoiser)
        
        self.combo_pixel_filter = QtWidgets.QComboBox()
        self.combo_pixel_filter.addItems(["gauss", "box", "blackman", "blackmanharris"])
        self.combo_pixel_filter.setCurrentText("gauss")
        form_filters.addRow("Pixel Filter (AA):", self.combo_pixel_filter)

        self.sld_diffuse_limit = IntSlider(0, 16, 3)
        form_filters.addRow("Diffuse Limit:", self.sld_diffuse_limit)

        self.sld_reflection_limit = IntSlider(0, 16, 3)
        form_filters.addRow("Reflection Limit:", self.sld_reflection_limit)

        self.sld_transmission_limit = IntSlider(0, 16, 4)
        form_filters.addRow("Transmission Limit:", self.sld_transmission_limit)

        self.sld_vol_limit = IntSlider(0, 32, 8)
        form_filters.addRow("Volume Limit:", self.sld_vol_limit)

        self.sld_color_limit = FloatSlider(0.0, 100.0, 10.0)
        form_filters.addRow("Color Limit (Clamp):", self.sld_color_limit)

        self.sld_noise_level = FloatSlider(0.0, 1.0, 0.01)
        form_filters.addRow("Noise Level (Variance):", self.sld_noise_level)
        
        tabs.addTab(_wrap_tab(tab_filters), "Render")

        # --- TAB 4: AOV ---
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

        self.chk_aov_multilayer = QtWidgets.QCheckBox("Store AOVs in one multilayer EXR when possible")
        self.chk_aov_multilayer.setChecked(True)
        self.form_aov_output.addRow("Combine:", self.chk_aov_multilayer)

        self.chk_aov_half_precision = QtWidgets.QCheckBox("Use 16-bit (half) when supported")
        self.chk_aov_half_precision.setChecked(False)
        self.form_aov_output.addRow("Precision:", self.chk_aov_half_precision)

        layout_aov.addWidget(self.grp_aov_output)
        layout_aov.addStretch(1)

        tabs.addTab(_wrap_tab(tab_aov), "Passes")
        
        # --- TAB 5: OUTPUT ---
        tab_out = QtWidgets.QWidget()
        self.form_out = QtWidgets.QFormLayout(tab_out)
        self.form_out.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        self.combo_output_format = QtWidgets.QComboBox()
        self.combo_output_format.addItems(["EXR", "PNG"])
        self.combo_output_format.currentIndexChanged.connect(self.update_output_format_ui)
        self.form_out.addRow("Format:", self.combo_output_format)

        self.combo_exr_precision = QtWidgets.QComboBox()
        self.combo_exr_precision.addItems(["16-bit float", "32-bit float"])
        self.form_out.addRow("Precision:", self.combo_exr_precision)
        
        self.combo_trange = QtWidgets.QComboBox()
        self.combo_trange.addItems(["Single Frame", "Frame Range"])
        self.combo_trange.setCurrentText("Single Frame")
        self.combo_trange.currentIndexChanged.connect(self.toggle_frame_range)
        self.form_out.addRow("Render Mode:", self.combo_trange)

        frames_layout = QtWidgets.QHBoxLayout()
        self.spin_fStart = QtWidgets.QSpinBox()
        self.spin_fStart.setRange(-1000, 10000)
        self.spin_fStart.setValue(1)
        self.spin_fStart.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.spin_fStart.setAlignment(QtCore.Qt.AlignCenter)
        
        self.spin_fEnd = QtWidgets.QSpinBox()
        self.spin_fEnd.setRange(-1000, 10000)
        self.spin_fEnd.setValue(100)
        self.spin_fEnd.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.spin_fEnd.setAlignment(QtCore.Qt.AlignCenter)
        
        self.lbl_to = QtWidgets.QLabel("to")
        self.lbl_to.setAlignment(QtCore.Qt.AlignCenter)
        
        frames_layout.addWidget(self.spin_fStart)
        frames_layout.addWidget(self.lbl_to)
        frames_layout.addWidget(self.spin_fEnd)
        self.form_out.addRow("Frame Range:", frames_layout)
        
        layout_out = QtWidgets.QHBoxLayout()
        self.line_out = QtWidgets.QLineEdit("$HIP/render/beauty/frame_$F4.exr")
        btn_browse_out = QtWidgets.QPushButton("...")
        btn_browse_out.setMaximumWidth(40)
        btn_browse_out.clicked.connect(self.browse_output)
        layout_out.addWidget(self.line_out)
        layout_out.addWidget(btn_browse_out)
        self.form_out.addRow("Output Path:", layout_out)
        
        lay_render_btns = QtWidgets.QHBoxLayout()
        
        self.btn_render_mplay = QtWidgets.QPushButton("Render to MPlay")
        self.btn_render_mplay.setStyleSheet(_btn_style(_C["accent_green"]))
        self.btn_render_mplay.clicked.connect(self.on_render_mplay)
        
        self.btn_render_disk = QtWidgets.QPushButton("Render to Disk")
        self.btn_render_disk.setStyleSheet(_btn_style(_C["accent_brown"]))
        self.btn_render_disk.clicked.connect(self.on_render_disk)

        self.btn_open_karma_settings = QtWidgets.QPushButton("Karma Settings")
        self.btn_open_karma_settings.setStyleSheet(_btn_style(_C["accent_teal"]))
        self.btn_open_karma_settings.clicked.connect(self.on_open_karma_settings)

        self.btn_open_viewport = QtWidgets.QPushButton("Karma Viewport")
        self.btn_open_viewport.setStyleSheet(_btn_style(_C["accent_blue"]))
        self.btn_open_viewport.clicked.connect(self.on_open_viewport)
        
        lay_render_btns.addWidget(self.btn_render_mplay)
        lay_render_btns.addWidget(self.btn_render_disk)
        lay_render_btns.addWidget(self.btn_open_karma_settings)
        lay_render_btns.addWidget(self.btn_open_viewport)

        self.w_render_btns = QtWidgets.QWidget()
        self.w_render_btns.setLayout(lay_render_btns)
        
        grp_viewport_tools = QtWidgets.QGroupBox("Viewport Tools")
        lay_viewport_tools = QtWidgets.QVBoxLayout(grp_viewport_tools)

        row_engine = QtWidgets.QHBoxLayout()
        row_engine.addWidget(QtWidgets.QLabel("Viewport Engine:"))
        self.combo_viewport_engine = QtWidgets.QComboBox()
        self.combo_viewport_engine.addItems(["xpu", "cpu"])
        self.combo_viewport_engine.setCurrentText(self.combo_engine.currentText())
        row_engine.addWidget(self.combo_viewport_engine, 1)
        self.btn_apply_viewport_engine = QtWidgets.QPushButton("Apply Renderer")
        self.btn_apply_viewport_engine.clicked.connect(self.on_apply_viewport_engine)
        row_engine.addWidget(self.btn_apply_viewport_engine)
        lay_viewport_tools.addLayout(row_engine)

        row_snapshot = QtWidgets.QHBoxLayout()
        self.btn_capture_snapshot = QtWidgets.QPushButton("Snapshot")
        self.btn_capture_snapshot.clicked.connect(self.on_capture_viewport_snapshot)
        self.btn_save_snapshot = QtWidgets.QPushButton("Save Snapshot")
        self.btn_save_snapshot.clicked.connect(self.on_save_viewport_snapshot)
        self.btn_save_snapshot.setEnabled(False)
        self.btn_clear_snapshot_slots = QtWidgets.QPushButton("Clear Slots")
        self.btn_clear_snapshot_slots.clicked.connect(self.on_clear_snapshot_slots)
        row_snapshot.addWidget(self.btn_capture_snapshot)
        row_snapshot.addWidget(self.btn_save_snapshot)
        row_snapshot.addWidget(self.btn_clear_snapshot_slots)
        lay_viewport_tools.addLayout(row_snapshot)

        row_slots = QtWidgets.QHBoxLayout()
        row_slots.addWidget(QtWidgets.QLabel("Captured Slots:"))
        self.btn_snapshot_slot_a = QtWidgets.QToolButton()
        self.btn_snapshot_slot_a.setCheckable(True)
        self.btn_snapshot_slot_a.clicked.connect(lambda *_: self._set_snapshot_slot_target("A"))
        self.btn_snapshot_slot_a.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
        self.btn_snapshot_slot_a.setFixedSize(130, 86)
        self.btn_snapshot_slot_a.setIconSize(QtCore.QSize(118, 62))
        row_slots.addWidget(self.btn_snapshot_slot_a)

        self.btn_snapshot_slot_b = QtWidgets.QToolButton()
        self.btn_snapshot_slot_b.setCheckable(True)
        self.btn_snapshot_slot_b.clicked.connect(lambda *_: self._set_snapshot_slot_target("B"))
        self.btn_snapshot_slot_b.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
        self.btn_snapshot_slot_b.setFixedSize(130, 86)
        self.btn_snapshot_slot_b.setIconSize(QtCore.QSize(118, 62))
        row_slots.addWidget(self.btn_snapshot_slot_b)
        row_slots.addStretch(1)
        lay_viewport_tools.addLayout(row_slots)

        row_safe = QtWidgets.QHBoxLayout()
        self.chk_snapshot_safe = QtWidgets.QCheckBox("Safe Frame")
        self.chk_snapshot_safe.stateChanged.connect(lambda *_: self._update_snapshot_preview())
        row_safe.addWidget(self.chk_snapshot_safe)

        self.combo_snapshot_safe_type = QtWidgets.QComboBox()
        self.combo_snapshot_safe_type.addItems(["Action Safe", "Text Safe", "Both"])
        self.combo_snapshot_safe_type.setMinimumWidth(130)
        self.combo_snapshot_safe_type.currentIndexChanged.connect(lambda *_: self._update_snapshot_preview())
        row_safe.addWidget(self.combo_snapshot_safe_type)
        row_safe.addStretch(1)
        lay_viewport_tools.addLayout(row_safe)

        row_compare = QtWidgets.QHBoxLayout()
        self.chk_snapshot_compare = QtWidgets.QCheckBox("Compare A/B")
        self.chk_snapshot_compare.setEnabled(False)
        self.chk_snapshot_compare.stateChanged.connect(lambda *_: self._update_snapshot_preview())
        row_compare.addWidget(self.chk_snapshot_compare)
        row_compare.addWidget(QtWidgets.QLabel("A"))

        self.sld_snapshot_compare = ClickSlider(QtCore.Qt.Horizontal)
        self.sld_snapshot_compare.setRange(1, 99)
        self.sld_snapshot_compare.setValue(50)
        self.sld_snapshot_compare.setMinimumHeight(22)
        self.sld_snapshot_compare.setStyleSheet(_slider_stylesheet())
        self.sld_snapshot_compare.setEnabled(False)
        self.sld_snapshot_compare.valueChanged.connect(lambda *_: self._update_snapshot_preview())
        row_compare.addWidget(self.sld_snapshot_compare, 1)
        row_compare.addWidget(QtWidgets.QLabel("B"))
        lay_viewport_tools.addLayout(row_compare)

        self.w_snapshot_preview = QtWidgets.QWidget()
        self.w_snapshot_preview.setMinimumHeight(220)
        self.w_snapshot_preview.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        lay_snapshot_stack = QtWidgets.QVBoxLayout(self.w_snapshot_preview)
        lay_snapshot_stack.setContentsMargins(0, 0, 0, 0)

        self.lbl_snapshot_preview = QtWidgets.QLabel("No snapshot yet.")
        self.lbl_snapshot_preview.setMinimumHeight(220)
        self.lbl_snapshot_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_snapshot_preview.setScaledContents(False)
        self.lbl_snapshot_preview.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.lbl_snapshot_preview.setObjectName("snapshotPreview")
        lay_snapshot_stack.addWidget(self.lbl_snapshot_preview)
        lay_viewport_tools.addWidget(self.w_snapshot_preview)
        
        self.form_out.addRow(self.w_render_btns)
        self.form_out.addRow(grp_viewport_tools)
        
        tabs.addTab(_wrap_tab(tab_out), "Export")

        # --- TAB 6: LOGS ---
        tab_logs = QtWidgets.QWidget()
        layout_logs = QtWidgets.QVBoxLayout(tab_logs)
        self.txt_log = QtWidgets.QTextEdit()
        self.txt_log.setReadOnly(True)
        layout_logs.addWidget(self.txt_log)

        btn_clear_log = QtWidgets.QPushButton("Clear Logs")
        btn_clear_log.clicked.connect(self.txt_log.clear)
        layout_logs.addWidget(btn_clear_log)

        row_debug = QtWidgets.QHBoxLayout()
        self.chk_debug_file = QtWidgets.QCheckBox("Write a debug log file")
        self.chk_debug_file.setToolTip(
            "Writes every message, the build settings, the missing parameters and the errors with their\n"
            "traceback to bsm_karma_debug.log. Send this file when something fails.")
        self.chk_debug_file.setChecked(_debug_state["enabled"])
        self.chk_debug_file.toggled.connect(self.on_debug_toggled)
        self.btn_open_log_folder = QtWidgets.QPushButton("Open Folder")
        self.btn_open_log_folder.setToolTip("Show the folder of the debug log file.")
        self.btn_open_log_folder.clicked.connect(self.on_open_log_folder)
        row_debug.addWidget(self.chk_debug_file, 1)
        row_debug.addWidget(self.btn_open_log_folder)
        layout_logs.addLayout(row_debug)
        self.lbl_debug_path = QtWidgets.QLabel()
        self.lbl_debug_path.setWordWrap(True)
        self.lbl_debug_path.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.lbl_debug_path.setStyleSheet("color: {};".format(_C["text_muted"]))
        layout_logs.addWidget(self.lbl_debug_path)

        tabs.addTab(_wrap_tab(tab_logs), "Log")

        # --- TAB ABOUT ---
        tab_about = QtWidgets.QWidget()
        layout_about = QtWidgets.QVBoxLayout(tab_about)
        layout_about.setAlignment(QtCore.Qt.AlignTop)
        layout_about.setSpacing(12)
        layout_about.setContentsMargins(16, 20, 16, 16)

        lbl_title = QtWidgets.QLabel(f"BSM Karma Builder {SCRIPT_VERSION}")
        title_font = lbl_title.font()
        title_font.setPointSize(16)
        title_font.setBold(True)
        lbl_title.setFont(title_font)
        lbl_title.setAlignment(QtCore.Qt.AlignCenter)
        layout_about.addWidget(lbl_title)

        lbl_sub = QtWidgets.QLabel("Procedural Environment & Render Setup\nfor SideFX Houdini")
        lbl_sub.setAlignment(QtCore.Qt.AlignCenter)
        lbl_sub.setStyleSheet("color: #aaa;")
        layout_about.addWidget(lbl_sub)

        sep1 = QtWidgets.QFrame()
        sep1.setFrameShape(QtWidgets.QFrame.HLine)
        sep1.setFrameShadow(QtWidgets.QFrame.Sunken)
        layout_about.addWidget(sep1)

        lbl_cred = QtWidgets.QLabel(
            "<b>Programming & Design</b><br>"
            "BSM<br>"
            'BSM3D'
        )
        lbl_cred.setAlignment(QtCore.Qt.AlignCenter)
        lbl_cred.setOpenExternalLinks(True)
        lbl_cred.setStyleSheet("line-height: 1.6;")
        layout_about.addWidget(lbl_cred)

        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.HLine)
        sep2.setFrameShadow(QtWidgets.QFrame.Sunken)
        layout_about.addWidget(sep2)

        lbl_sch = QtWidgets.QLabel("PolyForm Noncommercial License 1.0.0")
        lbl_sch.setAlignment(QtCore.Qt.AlignCenter)
        lbl_sch.setStyleSheet("color: #aaa; font-size: 12px;")
        layout_about.addWidget(lbl_sch)

        layout_about.addStretch(1)

        tabs.addTab(_wrap_tab(tab_about), "About")
        
        main_layout.addWidget(tabs)
        
        self.btn_build = QtWidgets.QPushButton("Build Environment Only")
        self.btn_build.setStyleSheet(_btn_style(_C["primary"]))
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

    # ----------------------------------------
    # LIFECYCLE
    # ----------------------------------------

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

        step("viewport panel", lambda: self._close_pane_tab(self._karma_scene_viewer))
        step("parameter panel", lambda: self._close_pane_tab(self._parm_pane_tab))
        self._karma_scene_viewer = None
        self._parm_pane_tab = None

        step("catalog source", self._restore_material_source)
        step("snapshots", self._clear_snapshot_images)
        step("target list", lambda: self.tree_mat_targets.set_prims([], {}))
        step("temp files", self._remove_temp_files)

    # --------------------------------------------------
    # Houdini shares one catalog source per session. If this dialog switched it, put the default back (a replaced
    # source object is invalid, so it cannot be restored).
    def _restore_material_source(self):
        if not self._material_source_changed:
            return
        self._material_source_changed = False
        catalog = hou.text.expandString("$HH/materialCatalog.db")
        if os.path.isfile(catalog):
            hou.ui.setSharedAssetGalleryDataSource(hou.AssetGalleryDataSource(catalog), "material")

    # --------------------------------------------------
    def _clear_snapshot_images(self):
        self._snapshot_source_image = QtGui.QImage()
        self._snapshot_compare_image = QtGui.QImage()

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
        # Esc and reject() end the dialog without a close event.
        self._release_resources()
        super().done(result)

    # ------------------------------------------------------------
    def closeEvent(self, event):
        self._release_resources()
        super().closeEvent(event)

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
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "lbl_snapshot_preview"):
            return
        if self._snapshot_source_image.isNull():
            return

        cur_size = self.lbl_snapshot_preview.size()
        if cur_size == self._last_snapshot_preview_size:
            return
        self._last_snapshot_preview_size = cur_size
        self._update_snapshot_preview()

    # ------------------------------------------------------------
    def _sync_viewport_engine_combo(self, engine):
        if hasattr(self, "combo_viewport_engine") and self.combo_viewport_engine is not None:
            if self.combo_viewport_engine.currentText() != engine:
                self.combo_viewport_engine.blockSignals(True)
                self.combo_viewport_engine.setCurrentText(engine)
                self.combo_viewport_engine.blockSignals(False)

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

    # ------------------------------------------------------------------------
    def browse_hdri(self):
        path = hou.ui.selectFile(start_directory="$HIP", title="Select HDRI", pattern="*.exr *.hdr *.rat", chooser_mode=hou.fileChooserMode.Read)
        if path:
            self.line_hdri_path.setText(hou.text.expandString(path))
            self._do_hdri_preview()

    # ------------------------------------------------------------
    def browse_output(self):
        pattern = "*.exr" if self.combo_output_format.currentText() == "EXR" else "*.png"
        path = hou.ui.selectFile(start_directory="$HIP", title="Output Path", pattern=pattern, chooser_mode=hou.fileChooserMode.Write)
        if path:
            self.line_out.setText(hou.text.expandString(path))
            self.sync_output_extension()

    # ------------------------------------------------------------
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

    # ------------------------------------------------
    # MATERIALS TAB
    # ------------------------------------------------

    def _default_material_download_dir(self):
        pref_dir = hou.text.expandString("$HOUDINI_USER_PREF_DIR")
        if not pref_dir or pref_dir.startswith("$"):
            pref_dir = tempfile.gettempdir()
        return os.path.join(pref_dir, "bsm_karma", "materials").replace("\\", "/")


    # --------------------------------------------------
    def _create_material_gallery(self):
        # HACK: hou.qt._createAssetGallery is private. It is what the Material Linker panel calls,
        # there is no public way to get this widget
        try:
            return hou.qt._createAssetGallery("material")
        except Exception as exc:
            self._pending_logs.append("Material catalog widget unavailable: {}".format(exc))
            return None

    #------------------------------------------------------------------------------------------
    def update_material_source_ui(self):
        self.w_mat_download.setVisible(self.combo_mat_source.currentText() == self.MATERIAL_SOURCES[0])
        self.btn_mat_connect.setEnabled(self.mat_gallery is not None)

    def browse_material_download_dir(self):
        path = hou.ui.selectFile(start_directory=self.line_mat_download.text(), title="Material Download Folder",
                                 file_type=hou.fileType.Directory, chooser_mode=hou.fileChooserMode.Read)
        if path:
            self.line_mat_download.setText(hou.text.expandString(path).rstrip("/\\"))

    # --------------------------------------------------
    def _set_material_status(self, text):
        self.lbl_mat_status.setText(text)

    # ------------------------------------------------------------
    @_guarded_slot
    def on_connect_material_library(self):
        source = self.combo_mat_source.currentText()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            if source == self.MATERIAL_SOURCES[0]:
                folder = hou.text.expandString(self.line_mat_download.text().strip())
                if not folder:
                    self._set_material_status("Choose a download folder first.")
                    return
                os.makedirs(folder, exist_ok=True)
                # building the source fetches the list with requests (no timeout, inside Houdini):
                # check reachability first so an offline machine does not freeze the UI
                reachable, reason = _amd_library_reachable()
                if not reachable:
                    self._set_material_status("AMD MaterialX Library unreachable: {}".format(reason))
                    self.log_message("[WARN] AMD MaterialX Library unreachable: {}".format(reason))
                    return
                data_source = hou.AssetGalleryDataSource("AMD MaterialX Library", folder)
                hint = "AMD MaterialX Library. Materials download to {} when first used.".format(folder)
            elif source == self.MATERIAL_SOURCES[1]:
                catalog = hou.text.expandString("$HH/materialCatalog.db")
                if not os.path.isfile(catalog):
                    self._set_material_status("Default catalog not found: {}".format(catalog))
                    return
                data_source = hou.AssetGalleryDataSource(catalog)
                hint = "Houdini default material catalog."
            else:
                path = hou.ui.selectFile(
                    start_directory="$HIP", title="Material File", chooser_mode=hou.fileChooserMode.Read,
                    pattern="*.mtlx *.usd *.usda *.usdc *.usdz")
                if not path:
                    return
                path = hou.text.expandString(path)
                source_file = _material_catalog_file(path)
                if source_file != path:
                    self._hdri_temp_files.append(source_file)  # removed when the dialog is released
                data_source = hou.AssetGalleryDataSource(source_file, "%type:Material")
                if not data_source.isValid():
                    self._set_material_status("Houdini could not open {} as a material source.".format(path))
                    return
                hint = "Materials found in {}".format(path)
            hou.ui.setSharedAssetGalleryDataSource(data_source, "material")
            self._material_source_changed = True
            self._amd_folder = folder if source == self.MATERIAL_SOURCES[0] else None
            self._set_material_status(hint)
            self.log_message("[OK] Material catalog connected: {}".format(source))
        except Exception as exc:
            self._set_material_status("Could not connect: {}".format(exc))
            self.log_message("[WARN] Material catalog connection failed ({}): {}".format(source, exc))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    # ------------------------------------------------------------
    def _geo_source_candidates(self):
        stage = hou.node("/stage")
        if stage is None:
            return []
        return [
            node.path() for node in stage.children()
            if node.type().category() == hou.lopNodeTypeCategory()
            and not _is_tool_node_candidate(node, node.name())
        ]

    def on_geo_source_changed(self, *_):
        self.refresh_stage_cameras()
        self.refresh_material_targets()

    # ------------------------------------------------------------
    def _fill_geo_source_combo(self):
        current = self._current_geo_source()
        self.combo_geo_source.blockSignals(True)
        self.combo_geo_source.clear()
        self.combo_geo_source.addItem(self.NO_GEO_SOURCE_LABEL)
        for path in self._geo_source_candidates():
            self.combo_geo_source.addItem(path)
        index = self.combo_geo_source.findText(current) if current else 0
        self.combo_geo_source.setCurrentIndex(max(0, index))
        self.combo_geo_source.blockSignals(False)

    # ------------------------------------------------------------
    def refresh_geo_sources(self):
        self._fill_geo_source_combo()
        self.refresh_stage_cameras()
        self.refresh_material_targets()

    # ----------------------------------------------------------------------
    def _current_geo_source(self):
        combo = getattr(self, "combo_geo_source", None)
        if combo is None:
            return ""
        text = combo.currentText()
        return "" if text == self.NO_GEO_SOURCE_LABEL else text

    # ------------------------------------------------------------------------
    def _material_stage(self):
        stage_net = hou.node("/stage")
        node = None
        linker = _material_linker_node(stage_net)
        if linker is not None and linker.input(0) is not None:
            node = linker
        elif self._current_geo_source():
            node = hou.node(self._current_geo_source())
        if node is None:
            return None
        try:
            return node.stage()
        except hou.Error as exc:
            self.log_message("[WARN] Could not read the stage of {}: {}".format(node.path(), exc))
            return None

    # --------------------------------------------------------
    def refresh_material_targets(self, *_):
        stage = self._material_stage()
        if stage is None:
            self.tree_mat_targets.set_prims([], {})
            return
        prims = _stage_target_prims(stage)
        if len(prims) >= STAGE_TARGET_LIMIT:
            self.log_message("[INFO] The prim list is limited to the first {} prims.".format(STAGE_TARGET_LIMIT))
        materials = {path: _bound_material_name(stage, path) for path, _, _ in prims}
        self.tree_mat_targets.set_prims(prims, materials)

    # ------------------------------------------------------------
    def _chain_matches_geo_source(self):
        stage = hou.node("/stage")
        if stage is None or stage.node("mtlx_materials") is None:
            return False
        geo_path = self._current_geo_source()
        merge = stage.node("geo_merge")
        if not geo_path:
            return merge is None
        return merge is not None and any(n is not None and n.path() == geo_path for n in merge.inputs())

    # ------------------------------------------------------------
    def _ensure_material_linker(self):
        if not self._chain_matches_geo_source():
            self.log_message("[INFO] Building the environment before assigning materials.")
            self.on_build()
        stage = hou.node("/stage")
        linker = _get_or_create_material_linker(stage)
        if not _insert_material_linker_in_chain(stage, linker, self.log_message):
            return None
        return linker


    # ------------------------------------------------------------
    def _assign_material_assets(self, assets, prim_paths):
        prim_paths = [p for p in prim_paths if p]
        if not assets or not prim_paths:
            return
        with hou.undos.group("BSM Karma - Assign Material"):
            linker = self._ensure_material_linker()
            if linker is None:
                return
            for asset in assets:
                try:
                    material_path = _linker_add_reference(linker, asset["file_path"], asset["prim_path"], asset["label"])
                except ValueError as exc:
                    self.log_message("[WARN] Material not assigned: {}".format(exc))
                    continue
                try:
                    count = _linker_assign(linker, material_path, prim_paths)
                except ValueError as exc:
                    self.log_message("[WARN] Material not assigned: {}".format(exc))
                    continue
                self.log_message("[OK] {} -> {} prim(s): {}".format(material_path, count, ", ".join(prim_paths[:3])
                                                                    + (" ..." if len(prim_paths) > 3 else "")))
        self.refresh_material_targets()

    # ------------------------------------------------------------------------
    @_guarded_slot
    def on_material_asset_dropped(self, payload, paths_text):
        prim_paths = [p for p in paths_text.splitlines() if p]
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            # TODO: an AMD package downloads here on the UI thread (Houdini's own code), the window freezes while it runs
            assets, failures = _parse_catalog_drop(payload, amd_folder=self._amd_folder)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, hou.Error) as exc:
            self.log_message("[WARN] Unreadable material drop: {}".format(exc))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        for failure in failures:
            self.log_message("[WARN] Material not available: {}".format(failure))
        if not assets:
            self.log_message("[INFO] Nothing to assign: drop a material (not a folder) from the catalog.")
            return
        self._assign_material_assets(assets, prim_paths)

    # ------------------------------------------------------------
    @_guarded_slot
    def on_assign_material_file(self):
        prim_paths = self.tree_mat_targets.selected_paths()
        if not prim_paths:
            self.log_message("[INFO] Select one or more prims in the list first.")
            return
        path = hou.ui.selectFile(
            start_directory="$HIP", title="MaterialX / USD Material File", chooser_mode=hou.fileChooserMode.Read,
            pattern="*.mtlx *.usd *.usda *.usdc *.usdz")
        if not path:
            return
        path = hou.text.expandString(path)
        try:
            materials = _list_materials_in_file(path)
        except Exception as exc:
            self.log_message("[WARN] Could not read {}: {}".format(path, exc))
            return
        if not materials:
            self.log_message("[WARN] No material found in {}".format(path))
            return
        if len(materials) == 1:
            chosen = materials
        else:
            picked = hou.ui.selectFromList([name for name, _ in materials], exclusive=True,
                                           title="Materials in file", message="Pick the material to assign:")
            if not picked:
                return
            chosen = [materials[picked[0]]]
        assets = [{"label": name, "file_path": path, "prim_path": prim, "id": prim} for name, prim in chosen]
        self._assign_material_assets(assets, prim_paths)

    # --------------------------------------------------------------------------------
    @_guarded_slot
    def on_unassign_material(self):
        prim_paths = self.tree_mat_targets.selected_paths()
        linker = _material_linker_node(hou.node("/stage"))
        if linker is None or not prim_paths:
            self.log_message("[INFO] Nothing to remove: select assigned prims in the list.")
            return
        with hou.undos.group("BSM Karma - Remove Material Assignment"):
            removed = _linker_unassign(linker, prim_paths)
        self.log_message("[OK] Removed the assignment on {} prim(s).".format(removed))
        self.refresh_material_targets()

    # ------------------------------------------------------------
    @_guarded_slot
    def on_open_material_linker(self):
        linker = _material_linker_node(hou.node("/stage"))
        if linker is None:
            self.log_message("[INFO] No Material Linker yet: drop a material on a prim first.")
            return
        linker.setSelected(True, clear_all_selected=True)
        try:
            linker.setCurrent(True, clear_all_selected=True)
        except hou.Error:
            pass

    #----------------------------------------------------------------
    def log_message(self, message):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        self.txt_log.append(f"[{now}] {message}")
        _debug(message, "LOG")

    # ------------------------------------------------------------
    def _update_debug_path_label(self):
        path = debug_log_path() if _debug_state["enabled"] else None
        if not _debug_state["enabled"]:
            self.lbl_debug_path.setText("Debug log file: off.")
        elif path is None or _debug_state["broken"]:
            self.lbl_debug_path.setText("Debug log file: no writable folder found, nothing is written.")
        else:
            self.lbl_debug_path.setText("Debug log file: {}".format(path))

    # ------------------------------------------------------------
    def on_debug_toggled(self, enabled):
        if enabled:
            _debug_state["broken"] = False
            _debug_state["enabled"] = True
            _debug_session_header()
            _debug("debug log switched on")
        else:
            _debug("debug log switched off")
            _debug_state["enabled"] = False
        self._update_debug_path_label()

    # ------------------------------------------------------------
    def on_open_log_folder(self):
        path = debug_log_path()
        if path is None:
            self.log_message("[WARN] No writable folder for the debug log.")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(path)))

    # --------------------------------------------------------
    # Presets: texte embarqué par l'HDA, sinon le JSON à côté du script, sinon un jeu minimal.
    # bug trouvé et fixé: le log n'existait pas encore quand les presets échouaient, le message est gardé pour plus
    # tard
    def _load_presets(self):
        try:
            data = None
            embedded = globals().get("EMBEDDED_PRESETS")
            if embedded:
                data = json.loads(embedded)
            else:
                preset_file = os.path.join(os.path.dirname(globals().get("__file__") or ""), "bsm_karma_presets.json")
                if os.path.isfile(preset_file):
                    with open(preset_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
            if data is not None:
                self.presets = data.get("render_qualities", {})
                self.sky_presets = data.get("sky_presets", {})
                self.fog_presets = data.get("fog_presets", {})
                self.cloud_presets = data.get("cloud_presets", {})
                return
        except (OSError, ValueError, AttributeError) as e:
            # The log tab does not exist yet while the dialog is being built: keep the message for later.
            self._pending_logs.append("Failed to load the presets: {}".format(e))

        self.presets = {"Mid (1080p / 256s)": {"rx": 1920, "ry": 1080, "spl": 256}}
        self.sky_presets = {"Clear Sky (Midday)": {"elv": 60.0, "s_int": 3.0, "turb": 2.8, "sk_int": 2.0, "hz": 2.0, "sun_t": 5500, "amb_r": 1.0, "amb_g": 1.0, "amb_b": 1.0, "atm_r": 1.0, "atm_m": 0.5}}
        self.fog_presets = {"Light Mist": {"dens": 0.05, "h": 20.0, "rad": 150.0, "phase": 0.2, "ns": 0.1, "na": 0.2}}
        self.cloud_presets = {"Low Cumulus": {"dens": 0.20, "alt": 80.0, "scale": 150.0, "div": 5, "clip": 0.45}}

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
    def _set_form_field_visible(self, form_layout, field, visible):
        try:
            form_layout.setRowVisible(field, visible)
            return
        except Exception:
            pass

        label = form_layout.labelForField(field)
        if label is not None:
            label.setVisible(visible)
        field.setVisible(visible)

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
                except hou.OperationFailed as exc:
                    self.log_message("[WARN] Could not remove {}: {}".format(path, exc))
                    skipped.append(path)
                except Exception as exc:
                    self.log_message("[WARN] Failed to remove {}: {}".format(path, exc))
                    skipped.append(path)

        try:
            with hou.undos.group("BSM Karma - Clear Tool Nodes"):
                _delete_impl()
        except Exception:
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
        lbl = self.form_out.labelForField(self.combo_exr_precision)
        if lbl is not None:
            lbl.setVisible(is_exr)
        self.combo_exr_precision.setVisible(is_exr)
        self.sync_output_extension()


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


    # ------------------------------------------------------------
    def update_environment_tab(self):
        mode = self.combo_scene_mode.currentText()
        is_env_mode = (mode == "Environment")
        env_type = self.combo_env_type.currentText()

        self.combo_env_type.setEnabled(mode in ["Environment", "Interior"])

        is_hdri = (mode in ["Studio", "3 Points"]) or (mode in ["Environment", "Interior"] and env_type == "HDRI Image")
        is_physical = (mode in ["Environment", "Interior"] and env_type == "Physical Sky")
        
        self.lbl_hdri_preview.setMinimumHeight(160 if is_hdri else 0)

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
    def _do_hdri_preview(self):
        source_path = self.line_hdri_path.text().strip()
        if not source_path:
            self._set_hdri_preview_message("No HDRI path")
            return

        source_path = os.path.abspath(hou.text.expandString(source_path))
        if not os.path.isfile(source_path):
            self._set_hdri_preview_message("HDRI file not found")
            return

        pixmap = self._load_hdri_preview_pixmap(source_path)
        if pixmap is None:
            self._set_hdri_preview_message("Preview unavailable for this format")
            return

        self.lbl_hdri_preview.setText("")
        self.lbl_hdri_preview.setPixmap(pixmap)

    # --------------------------------------------------------
    def toggle_frame_range(self):
        is_range = (self.combo_trange.currentText() == "Frame Range")
        self.spin_fStart.setEnabled(is_range)
        self.spin_fEnd.setEnabled(is_range)
        self.lbl_to.setEnabled(is_range)

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
            "out_path": self.line_out.text()
        }

    # ------------------------------------------------------------------------
    @_guarded_slot
    def on_build(self):
        self.sync_output_extension()
        config = self._collect_config()
        _debug("build settings: " + json.dumps(config, sort_keys=True, default=str))
        try:
            with hou.undos.group("BSM Karma - Build"):
                setup_karma_environment(config, self.log_message)
        except hou.OperationFailed as exc:
            self.log_message("[ERROR] Build stopped: {}".format(exc))
            return False
        self.refresh_stage_cameras()
        self.refresh_material_targets()
        return True

    # ------------------------------------
    @_guarded_slot
    def on_render_disk(self):
        if not self.on_build():
            return
        rp = hou.node("/stage/render_to_disk")
        if rp:
            out_dir = os.path.dirname(hou.text.expandString(self.line_out.text()))
            if out_dir: os.makedirs(out_dir, exist_ok=True)
            self.log_message("▶ Launching Render to Disk...")
            rp.parm("execute").pressButton()

    # ------------------------------------------------------------
    @_guarded_slot
    def on_render_mplay(self):
        if not self.on_build():
            return
        rp = hou.node("/stage/render_to_disk")
        if rp:
            self.log_message("▶ Launching Render to MPlay...")
            old_path = rp.parm("outputimage").unexpandedString()
            rp.parm("outputimage").set("ip")
            try:
                rp.parm("execute").pressButton()
            finally:
                rp.parm("outputimage").set(old_path)

    # ----------------------------------------------------------------------
    def _call_method_if_available(self, obj, method_name, *args):
        method = getattr(obj, method_name, None)
        if callable(method):
            try:
                method(*args)
                return True
            except Exception:
                return False
        return False

    # ----------------------------------------
    def _set_karma_viewport_minimal_ui(self, scene_viewer, viewport):
        scene_toggles = [
            ("showOperationBar", True),
            ("showSelectionBar", False),
            ("showDisplayOptionsBar", False),
            ("showColorCorrectionBar", False),
            ("showMemoryBar", False),
            ("setIncludeColorCorrectionBar", False),
            ("setIncludeMemoryBar", False),
            ("setGroupListVisible", False),
            ("setShowNetworkControls", False),
            ("showNetworkControls", False),
            ("showRenderStats", False),
            ("showRenderTime", False),
        ]
        for name, value in scene_toggles:
            self._call_method_if_available(scene_viewer, name, value)

        self._call_method_if_available(scene_viewer, "enterViewState")

        try:
            scene_viewer.setViewportLayout(hou.geometryViewportLayout.Single)
        except Exception:
            pass

        pane = None
        try:
            pane = scene_viewer.pane()
        except Exception:
            pane = None

        if pane is not None:
            self._call_method_if_available(pane, "setShowPaneTabs", False)
            self._call_method_if_available(pane, "showPaneTabs", False)
            self._call_method_if_available(pane, "showPaneTabsStow", False)
            self._call_method_if_available(pane, "setIsMaximized", True)
            self._call_method_if_available(pane, "setIsSplitMaximized", True)

        floating_panel = None
        try:
            floating_panel = scene_viewer.floatingPanel()
        except Exception:
            floating_panel = None

        if floating_panel is not None:
            self._call_method_if_available(floating_panel, "setContainsShelf", False)
            self._call_method_if_available(floating_panel, "setContainsStatusBar", False)
            self._call_method_if_available(floating_panel, "setContainsMenuBar", False)
            self._call_method_if_available(floating_panel, "setContainsPlaybar", False)

        if viewport is not None:
            settings = None
            try:
                settings = viewport.settings()
            except Exception:
                settings = None

            if settings is not None:
                view_toggles_off = [
                    "setShowGrid",
                    "setShowCompass",
                    "setShowOriginGnomon",
                    "setShowViewName",
                    "setShowCameraName",
                    "setShowFPS",
                    "setShowMemory",
                    "setShowTime",
                    "setShowViewerHandle",
                ]
                for name in view_toggles_off:
                    self._call_method_if_available(settings, name, False)

    # --------------------------------------------------------
    def _open_karma_render_options_panel(self, desktop):
        target_node = hou.node("/stage/render_to_disk") or hou.node("/stage/karma_settings")
        if desktop is None or target_node is None:
            return

        parm_tab = self._parm_pane_tab
        if parm_tab is not None:
            try:
                parm_tab.floatingPanel()
            except hou.Error:
                parm_tab = None
        if parm_tab is None:
            parm_tab = desktop.createFloatingPaneTab(hou.paneTabType.Parm)
            if parm_tab is None:
                return
            self._parm_pane_tab = parm_tab

        self._call_method_if_available(parm_tab, "setCurrentNode", target_node)
        self._call_method_if_available(parm_tab, "setNode", target_node)
        self._call_method_if_available(parm_tab, "setPin", True)

    # --------------------------------------------------------------------------------
    def _set_viewport_renderer(self, scene_viewer, viewport, engine):
        renderer_candidates = ["Karma XPU", "Karma"] if engine == "xpu" else ["Karma CPU", "Karma"]

        renderer_set = False
        for renderer_name in renderer_candidates:
            for obj in (scene_viewer, viewport):
                if obj is None:
                    continue
                for method_name in ("setHydraRenderer", "setCurrentHydraRenderer", "setRenderer"):
                    method = getattr(obj, method_name, None)
                    if callable(method):
                        try:
                            method(renderer_name)
                            renderer_set = True
                            break
                        except Exception:
                            pass
                if renderer_set:
                    break
            if renderer_set:
                break

        if not renderer_set and viewport is not None:
            for renderer_name in renderer_candidates:
                try:
                    hou.hscript('viewrenderer -V "{}" "{}"'.format(viewport.name(), renderer_name))
                    renderer_set = True
                    break
                except Exception:
                    pass

        return renderer_set

    # ------------------------------------------------------------------------
    def _is_stage_viewer(self, viewer):
        try:
            return viewer.pwd().path() == "/stage"
        except hou.Error:
            return False

    # ------------------------------------------------------------
    # The tool's Karma viewport, else a Scene Viewer already on /stage, else any Scene Viewer.
    def _get_active_scene_viewer(self):
        viewer = self._karma_scene_viewer
        if viewer is not None:
            try:
                viewer.curViewport()
                return viewer
            except hou.Error:
                self._karma_scene_viewer = None

        for tab in hou.ui.paneTabs():
            if tab.type() == hou.paneTabType.SceneViewer and self._is_stage_viewer(tab):
                return tab

        desktop = hou.ui.curDesktop()
        if desktop is None:
            return None
        return desktop.paneTabOfType(hou.paneTabType.SceneViewer)

    # ------------------------------------------------------------
    @_guarded_slot
    def on_apply_viewport_engine(self):
        engine = self.combo_viewport_engine.currentText().strip().lower()
        self.combo_engine.setCurrentText(engine)
        self.on_build()

        scene_viewer = self._get_active_scene_viewer()
        if scene_viewer is None:
            self.log_message("[WARN] Karma viewport not found.")
            return

        vp = None
        try:
            vp = scene_viewer.curViewport()
        except Exception:
            vp = None

        if self._set_viewport_renderer(scene_viewer, vp, engine):
            self.log_message("[OK] Karma viewport renderer set to {}.".format(engine.upper()))
        else:
            self.log_message("[WARN] Could not switch Karma viewport renderer to {}.".format(engine.upper()))

    def _capture_with_viewport_methods(self, viewport, output_path):
        for method_name in ("saveViewToImage", "saveViewToFile", "saveViewImage"):
            method = getattr(viewport, method_name, None)
            if not callable(method):
                continue
            try:
                method(output_path)
                if os.path.isfile(output_path):
                    return True
            except Exception:
                pass
        return False

    # ------------------------------------------------------------
    def _capture_with_flipbook(self, viewer, viewport, stamp, ext="png"):
        frame = int(round(hou.frame()))
        pattern = os.path.join(_private_temp_dir(), "snapshot_{}.$F4.{}".format(stamp, ext))

        settings = viewer.flipbookSettings().stash()
        try:
            settings.outputToMPlay(False)
        except Exception:
            pass
        try:
            settings.output(pattern)
        except Exception:
            return None
        try:
            settings.frameRange((frame, frame))
        except Exception:
            pass
        try:
            settings.frameIncrement(1)
        except Exception:
            pass
        try:
            settings.useResolution(False)
        except Exception:
            pass

        viewer.flipbook(viewport, settings)

        expected = pattern.replace("$F4", "{:04d}".format(frame))
        if os.path.isfile(expected):
            return expected
        return None

    # ------------------------------------------------------------
    def _render_camera_prim_path(self):
        ks = hou.node("/stage/karma_settings")
        if ks is not None and ks.parm("camera") is not None:
            value = ks.parm("camera").evalAsString().strip()
            if value.startswith("/"):
                return value
        choice = self._current_camera_choice()
        if choice.startswith(USD_CAMERA_PREFIX):
            return choice[len(USD_CAMERA_PREFIX):]
        if choice != CAMERA_CREATE_LABEL:
            node = hou.node(choice)
            if node is not None:
                return _camera_prim_path(node)
        return ""

    # ------------------------------------------------------------------------
    # Fix erreur = setCamera(node) lève TypeError sur H22, Solaris veut le chemin de prim USD en chaîne
    def _lock_viewport_to_camera(self, scene_viewer, viewport, prim_path):
        if viewport is None or not prim_path:
            return False
        try:
            viewport.setCamera(prim_path)
            return True
        except (hou.Error, TypeError):
            pass
        # older builds: node path through hscript. The path comes from the scene (a .hip can hold anything),
        # so only a plain USD path may go into a command line
        if not _PRIM_PATH_RE.match(prim_path):
            return False
        for cmd in (
            'viewcamera "{}" "{}"'.format(prim_path, viewport.name()),
            'viewcamera -c "{}" "{}"'.format(prim_path, viewport.name()),
        ):
            try:
                hou.hscript(cmd)
                return True
            except hou.Error:
                pass
        return False

    def _apply_camera_to_viewport(self, scene_viewer, viewport):
        self._lock_viewport_to_camera(scene_viewer, viewport, self._render_camera_prim_path())

    @_guarded_slot
    def on_look_through_camera(self):
        stage = hou.node("/stage")
        if self._current_camera_choice() == CAMERA_CREATE_LABEL and (stage is None or stage.node(GENERATED_CAMERA_NAME) is None):
            self.on_build()
        scene_viewer = self._get_active_scene_viewer()
        if scene_viewer is None or not self._is_stage_viewer(scene_viewer):
            # Solaris cameras only exist in a viewer on /stage: open the Karma viewport, which locks the camera
            self.log_message("[INFO] No Scene Viewer on /stage: opening the Karma viewport.")
            self.on_open_viewport()
            return
        try:
            viewport = scene_viewer.curViewport()
        except hou.Error:
            viewport = None
        prim_path = self._render_camera_prim_path()
        if self._lock_viewport_to_camera(scene_viewer, viewport, prim_path):
            self.log_message("[OK] Viewport locked to {}.".format(prim_path))
        else:
            self.log_message("[WARN] Could not lock the viewport to {}.".format(prim_path or "the render camera"))

    # ------------------------------------------------------------
    @_guarded_slot
    def on_capture_viewport_snapshot(self):
        img = self._capture_viewport_snapshot_image()
        if img is None:
            return

        slot = self._snapshot_slot_target
        if slot == "B":
            self._snapshot_compare_image = img
            self._set_snapshot_slot_target("A")
        else:
            self._snapshot_source_image = img
            self._set_snapshot_slot_target("B")

        self.btn_save_snapshot.setEnabled(True)
        self._update_snapshot_slots_ui()
        self._update_snapshot_preview()
        self.log_message("[OK] Snapshot {} updated ({}x{}).".format(slot, img.width(), img.height()))

    # --------------------------------------------------------
    def on_capture_viewport_snapshot_compare(self):
        self._set_snapshot_slot_target("B")
        self.on_capture_viewport_snapshot()

    # --------------------------------------------------------
    def _set_snapshot_slot_target(self, slot_name):
        slot = "A" if slot_name not in ("A", "B") else slot_name
        self._snapshot_slot_target = slot
        if hasattr(self, "btn_snapshot_slot_a"):
            self.btn_snapshot_slot_a.setChecked(slot == "A")
        if hasattr(self, "btn_snapshot_slot_b"):
            self.btn_snapshot_slot_b.setChecked(slot == "B")
        self._update_snapshot_slots_ui()

    def _snapshot_has_compare(self):
        return (
            self._snapshot_source_image is not None
            and not self._snapshot_source_image.isNull()
            and self._snapshot_compare_image is not None
            and not self._snapshot_compare_image.isNull()
        )

    # --------------------------------------------------------
    def _snapshot_any_image(self):
        return (
            self._snapshot_source_image is not None
            and not self._snapshot_source_image.isNull()
        ) or (
            self._snapshot_compare_image is not None
            and not self._snapshot_compare_image.isNull()
        )

    # ----------------------------------------------------------------
    def _update_snapshot_slot_button(self, btn, slot_name, img):
        is_target = (self._snapshot_slot_target == slot_name)
        label = "Slot {}{}".format(slot_name, " [Target]" if is_target else "")
        btn.setText(label)
        btn.setChecked(is_target)

        if img is None or img.isNull():
            btn.setIcon(QtGui.QIcon())
            btn.setStyleSheet("QToolButton {border: 1px solid #505050; background-color: #2a2a2a;}")
            return

        px = QtGui.QPixmap.fromImage(img)
        if not px.isNull():
            thumb = px.scaled(
                btn.iconSize(),
                QtCore.Qt.KeepAspectRatioByExpanding,
                QtCore.Qt.SmoothTransformation,
            )
            if thumb.width() > btn.iconSize().width() or thumb.height() > btn.iconSize().height():
                x = max(0, int((thumb.width() - btn.iconSize().width()) * 0.5))
                y = max(0, int((thumb.height() - btn.iconSize().height()) * 0.5))
                thumb = thumb.copy(x, y, btn.iconSize().width(), btn.iconSize().height())
            btn.setIcon(QtGui.QIcon(thumb))
        btn.setStyleSheet("QToolButton {border: 1px solid #5e738b; background-color: #2b3440;}")

    # ------------------------------------------------------------
    def _update_snapshot_slots_ui(self):
        if not hasattr(self, "btn_snapshot_slot_a"):
            return

        self._update_snapshot_slot_button(self.btn_snapshot_slot_a, "A", self._snapshot_source_image)
        self._update_snapshot_slot_button(self.btn_snapshot_slot_b, "B", self._snapshot_compare_image)

        has_compare = self._snapshot_has_compare()
        if hasattr(self, "chk_snapshot_compare"):
            self.chk_snapshot_compare.setEnabled(has_compare)
            if has_compare and not self.chk_snapshot_compare.isChecked():
                self.chk_snapshot_compare.setChecked(True)
            if not has_compare:
                self.chk_snapshot_compare.setChecked(False)
        if hasattr(self, "sld_snapshot_compare"):
            self.sld_snapshot_compare.setEnabled(has_compare and self.chk_snapshot_compare.isChecked())
        if hasattr(self, "btn_save_snapshot"):
            self.btn_save_snapshot.setEnabled(self._snapshot_any_image())

    # ------------------------------------------------------------
    def on_clear_snapshot_slots(self):
        self._snapshot_source_image = QtGui.QImage()
        self._snapshot_compare_image = QtGui.QImage()
        self._set_snapshot_slot_target("A")
        self._update_snapshot_slots_ui()
        self._update_snapshot_preview()
        self.log_message("[OK] Snapshot slots cleared.")

    # ----------------------------------------------------------------------
    def _capture_viewport_snapshot_image(self):
        scene_viewer = self._get_active_scene_viewer()
        if scene_viewer is None:
            self.log_message("[WARN] No Scene Viewer found for snapshot.")
            return None

        vp = None
        try:
            vp = scene_viewer.curViewport()
        except Exception:
            vp = None

        if vp is None:
            self.log_message("[WARN] No active viewport to capture.")
            return None

        self._apply_camera_to_viewport(scene_viewer, vp)

        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        tmp_path = os.path.join(_private_temp_dir(), "snapshot_{}.png".format(stamp))
        captured_path = None

        try:
            if self._capture_with_viewport_methods(vp, tmp_path):
                captured_path = tmp_path
            else:
                captured_path = self._capture_with_flipbook(scene_viewer, vp, stamp, ext="png")

            if not captured_path:
                self.log_message("[WARN] Snapshot capture failed.")
                return None

            img = QtGui.QImage(captured_path)
            if img.isNull():
                self.log_message("[WARN] Snapshot captured but image is invalid.")
                return None
            return img
        except Exception as exc:
            self.log_message("[WARN] Snapshot capture failed: {}".format(exc))
            return None
        finally:
            import glob
            cleanup_pattern = os.path.join(_private_temp_dir(), "snapshot_{}*".format(stamp))
            for p in glob.glob(cleanup_pattern):
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass

    # ------------------------------------------------------------
    def _pixmap_with_safe_overlay(self, pixmap):
        if not self.chk_snapshot_safe.isChecked():
            return pixmap

        safe_type = self.combo_snapshot_safe_type.currentText()
        overlays = []
        if safe_type in ("Action Safe", "Both"):
            overlays.append((0.10, QtGui.QColor("#ff6b6b")))
        if safe_type in ("Text Safe", "Both"):
            overlays.append((0.05, QtGui.QColor("#ffe066")))

        painter = QtGui.QPainter(pixmap)
        rect = QtCore.QRectF(pixmap.rect())
        for margin, color in overlays:
            painter.setPen(QtGui.QPen(color, 1))
            safe_rect = QtCore.QRectF(
                rect.left() + rect.width() * margin,
                rect.top() + rect.height() * margin,
                rect.width() * (1.0 - margin * 2.0),
                rect.height() * (1.0 - margin * 2.0),
            )
            painter.drawRect(safe_rect)
        painter.end()
        return pixmap

    # ------------------------------------------------------------------------
    def _build_centered_pixmap(self, source_image, target_size):
        if source_image is None or source_image.isNull():
            return QtGui.QPixmap()

        src = QtGui.QPixmap.fromImage(source_image)
        if src.isNull():
            return QtGui.QPixmap()

        scaled = src.scaled(target_size, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
        if scaled.isNull():
            return QtGui.QPixmap()

        x = max(0, int((scaled.width() - target_size.width()) * 0.5))
        y = max(0, int((scaled.height() - target_size.height()) * 0.5))
        return scaled.copy(x, y, target_size.width(), target_size.height())

    # ----------------------------------------------------------------
    def _build_compare_pixmap(self, img_a, img_b, target_size, split_percent):
        px_a = self._build_centered_pixmap(img_a, target_size)
        px_b = self._build_centered_pixmap(img_b, target_size)
        if px_a.isNull() or px_b.isNull():
            return px_a if not px_a.isNull() else px_b

        result = QtGui.QPixmap(px_a)
        split_x = int(target_size.width() * (_clamp(split_percent, 0.0, 100.0) / 100.0))
        split_x = max(1, min(target_size.width() - 1, split_x))

        painter = QtGui.QPainter(result)
        painter.setClipRect(QtCore.QRect(0, 0, split_x, target_size.height()))
        painter.drawPixmap(0, 0, px_b)
        painter.setClipping(False)
        painter.setPen(QtGui.QPen(QtGui.QColor("#ffd166"), 2))
        painter.drawLine(split_x, 0, split_x, target_size.height())
        painter.end()
        return result

    # ------------------------------------------------------------
    def _update_snapshot_preview(self, rebuild=False):
        if not self._snapshot_any_image():
            self.lbl_snapshot_preview.setPixmap(QtGui.QPixmap())
            self.lbl_snapshot_preview.setText("No snapshot yet.")
            return

        target_size = self.lbl_snapshot_preview.size()
        if target_size.width() < 2 or target_size.height() < 2:
            return
        self._last_snapshot_preview_size = target_size

        source_img = self._snapshot_source_image
        if source_img is None or source_img.isNull():
            source_img = self._snapshot_compare_image

        compare_ready = self._snapshot_has_compare() and (
            (not hasattr(self, "chk_snapshot_compare")) or self.chk_snapshot_compare.isChecked()
        )

        if compare_ready:
            pixmap = self._build_compare_pixmap(
                self._snapshot_source_image,
                self._snapshot_compare_image,
                target_size,
                float(self.sld_snapshot_compare.value()),
            )
        else:
            pixmap = self._build_centered_pixmap(source_img, target_size)

        pixmap = self._pixmap_with_safe_overlay(pixmap)

        self.lbl_snapshot_preview.setText("")
        self.lbl_snapshot_preview.setPixmap(pixmap)

    # ------------------------------------------------------------
    @_guarded_slot
    def on_save_viewport_snapshot(self):
        if not self._snapshot_any_image():
            self.log_message("[WARN] No snapshot to save.")
            return

        path = hou.ui.selectFile(
            start_directory="$HIP",
            title="Save Viewport Snapshot",
            pattern="*.png *.jpg",
            chooser_mode=hou.fileChooserMode.Write,
        )
        if not path:
            return

        path = hou.text.expandString(path)
        root, ext = os.path.splitext(path)
        if ext.lower() not in (".png", ".jpg", ".jpeg"):
            path = root + ".png"

        source_img = self._snapshot_source_image
        if source_img is None or source_img.isNull():
            source_img = self._snapshot_compare_image

        img_to_save = source_img.copy()
        if self.chk_snapshot_safe.isChecked():
            safe_type = self.combo_snapshot_safe_type.currentText()
            overlays = []
            if safe_type in ("Action Safe", "Both"):
                overlays.append((0.10, QtGui.QColor("#ff6b6b")))
            if safe_type in ("Text Safe", "Both"):
                overlays.append((0.05, QtGui.QColor("#ffe066")))

            painter = QtGui.QPainter(img_to_save)
            rect = QtCore.QRectF(img_to_save.rect())
            pen_w = max(1, int(round(min(img_to_save.width(), img_to_save.height()) * 0.002)))
            for margin, color in overlays:
                painter.setPen(QtGui.QPen(color, pen_w))
                safe_rect = QtCore.QRectF(
                    rect.left() + rect.width() * margin,
                    rect.top() + rect.height() * margin,
                    rect.width() * (1.0 - margin * 2.0),
                    rect.height() * (1.0 - margin * 2.0),
                )
                painter.drawRect(safe_rect)
            painter.end()

        if img_to_save.save(path):
            self.log_message("[OK] Snapshot saved: {}".format(path))
        else:
            self.log_message("[WARN] Failed to save snapshot: {}".format(path))

    # ----------------------------------------------------------------------
    @_guarded_slot
    def on_open_karma_settings(self):
        self.on_build()
        desktop = hou.ui.curDesktop()
        if desktop is None:
            self.log_message("[WARN] Cannot access current Houdini desktop.")
            return
        self._open_karma_render_options_panel(desktop)
        self.log_message("[OK] Karma settings panel opened.")

    # ------------------------------------------------------------
    @_guarded_slot
    def on_open_viewport(self):
        self.on_build()

        stage = hou.node("/stage")
        cam_prim_path = self._render_camera_prim_path()

        desktop = hou.ui.curDesktop()
        if desktop is None:
            self.log_message("[WARN] Cannot access current Houdini desktop.")
            return

        scene_viewer = self._karma_scene_viewer
        is_new_viewer = False

        if scene_viewer is not None:
            try:
                scene_viewer.curViewport()
            except Exception:
                scene_viewer = None
                self._karma_scene_viewer = None

        if scene_viewer is None:
            scene_viewer = desktop.createFloatingPaneTab(hou.paneTabType.SceneViewer)
            if scene_viewer is None:
                self.log_message("[WARN] Failed to create floating Scene Viewer.")
                return
            self._karma_scene_viewer = scene_viewer
            is_new_viewer = True

        vp = None
        renderer_set = False
        if stage is not None:
            try:
                scene_viewer.setPwd(stage)
            except Exception:
                pass

        try:
            vp = scene_viewer.curViewport()
        except Exception:
            vp = None

        engine = self.combo_engine.currentText().strip().lower()
        renderer_set = self._set_viewport_renderer(scene_viewer, vp, engine)

        if vp is not None and cam_prim_path:
            if not self._lock_viewport_to_camera(scene_viewer, vp, cam_prim_path):
                self.log_message("[WARN] Viewport opened, but camera lock to {} could not be set.".format(cam_prim_path))

        self._set_karma_viewport_minimal_ui(scene_viewer, vp)

        if renderer_set:
            if is_new_viewer:
                self.log_message("[OK] Karma viewport opened.")
            else:
                self.log_message("[OK] Karma viewport updated.")
        else:
            self.log_message("[WARN] Viewport opened, but Karma renderer switch could not be confirmed.")


# ========================================
# LANCEMENT DE L'UI
# ========================================
# le dialogue est gardé en global pour qu'un second lancement ferme le premier;
# le `if not in globals()` garde la référence quand le shelf tool recharge le module (importlib.reload avant main)
if "bsm_karma_ui_dialog" not in globals():
    bsm_karma_ui_dialog = None


# --------------------------------------------------------
# Forget the dialog once it is destroyed, unless a newer one already replaced it.
def _forget_dialog(dialog_id):
    global bsm_karma_ui_dialog
    if bsm_karma_ui_dialog is not None and id(bsm_karma_ui_dialog) == dialog_id:
        bsm_karma_ui_dialog = None


# ------------------------------------------------------------
def main(kwargs=None):
    global bsm_karma_ui_dialog
    if bsm_karma_ui_dialog is not None:
        try:
            bsm_karma_ui_dialog.close()
        except RuntimeError:
            pass  # the Qt object was already deleted

    dialog = KarmaBuilderUI(hou.qt.mainWindow())
    dialog.destroyed.connect(lambda *_, dialog_id=id(dialog): _forget_dialog(dialog_id))
    bsm_karma_ui_dialog = dialog
    dialog.show()
