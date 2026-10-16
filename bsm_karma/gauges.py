# gauges.py - BSM Karma Builder - gauge fields and the sliders built on them
# Version : 1.0.0 | Revision : 15-10-2026 | Auteur : BSM

from hutil.Qt import QtWidgets, QtCore, QtGui
from .util import _clamp
from .widgets import _drop_event_pos


# ------------------------------------------------------------
class ClickSlider(QtWidgets.QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)

    # --------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            if self.orientation() == QtCore.Qt.Horizontal:
                pos = _drop_event_pos(event).x()
                span = max(1, self.width() - 1)
            else:
                pos = _drop_event_pos(event).y()
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
            # same mapping as the gauge above, kept inside the widget so the end labels are not cut
            x = int(_clamp(ratio * self.width(), 15, max(15, self.width() - 15)))
            painter.drawText(x - 15, 0, 30, 18, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, str(label))
        painter.end()


# ----------------------------------------------------------------------
# Hybrid field: a dark bar filled with an amber gauge, the value written in the middle. Drag to set the value
# (it follows the mouse position), click without dragging to type a number, arrows for fine steps. The wheel is
# left alone so that it keeps scrolling the tab. Snap points only act while dragging, a typed value stays exact.
class GaugeBar(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(float)

    TRACK = QtGui.QColor("#1f2123")
    FILL = QtGui.QColor(214, 140, 20, 205)
    EDGE = QtGui.QColor("#3f4246")
    EDGE_ACTIVE = QtGui.QColor("#e8a317")
    TEXT = QtGui.QColor("#f2f2f2")

    # ----------------------------------------------------------------------
    def __init__(self, min_val, max_val, default_val, decimals=2, snap_points=None, parent=None):
        super().__init__(parent)
        self._min = float(min_val)
        self._max = float(max_val)
        self._decimals = int(decimals)
        self._snap_points = list(snap_points or [])
        self._value = self._clean(default_val)
        self._hover = False
        self._press_x = None
        self._dragging = False
        self._editor = None
        self.setMinimumHeight(20)
        self.setMinimumWidth(70)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setCursor(QtCore.Qt.SizeHorCursor)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

    # ----------------------------------------------------------------------
    def _clean(self, value):
        return round(_clamp(float(value), self._min, self._max), self._decimals)

    # ----------------------------------------------------------------------
    def value(self):
        return self._value

    # ----------------------------------------------------------------------
    def setValue(self, value):
        value = self._clean(value)
        if value == self._value:
            return
        self._value = value
        self.update()
        self.valueChanged.emit(value)

    # ----------------------------------------------------------------------
    def _snap(self, value):
        threshold = (self._max - self._min) * 0.05
        for point in self._snap_points:
            if abs(value - point) < threshold:
                return float(point)
        return value

    # ----------------------------------------------------------------------
    def _value_at(self, x):
        ratio = _clamp(float(x) / max(1.0, self.width() - 1.0), 0.0, 1.0)
        return self._snap(self._min + (self._max - self._min) * ratio)

    # ----------------------------------------------------------------------
    def format_value(self, value):
        return "{:.{}f}".format(value, self._decimals)

    # ----------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._press_x = _drop_event_pos(event).x()
            self._dragging = False
            self.setFocus()
            event.accept()
        else:
            super().mousePressEvent(event)

    # ----------------------------------------------------------------------
    def mouseMoveEvent(self, event):
        if self._press_x is None:
            return
        x = _drop_event_pos(event).x()
        if not self._dragging and abs(x - self._press_x) >= 3:
            self._dragging = True
        if self._dragging:
            self.setValue(self._value_at(x))

    # ----------------------------------------------------------------------
    def mouseReleaseEvent(self, event):
        was_click = self._press_x is not None and not self._dragging
        self._press_x = None
        self._dragging = False
        if event.button() == QtCore.Qt.LeftButton and was_click:
            self._begin_edit()

    # ----------------------------------------------------------------------
    def _begin_edit(self):
        if self._editor is not None:
            return
        editor = QtWidgets.QLineEdit(self)
        editor.setAlignment(QtCore.Qt.AlignCenter)
        editor.setText(self.format_value(self._value))
        editor.setGeometry(self.rect().adjusted(1, 1, -1, -1))
        editor.selectAll()
        editor.editingFinished.connect(lambda: self._end_edit(True))
        editor.installEventFilter(self)
        self._editor = editor
        editor.show()
        editor.setFocus()

    # ----------------------------------------------------------------------
    def _end_edit(self, commit):
        editor, self._editor = self._editor, None
        if editor is None:
            return
        text = editor.text().strip().replace(",", ".")
        editor.removeEventFilter(self)
        editor.hide()
        editor.deleteLater()
        if commit:
            try:
                self.setValue(float(text))
            except ValueError:
                pass
        self.update()

    # ----------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self._editor and event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            self._end_edit(False)
            return True
        return super().eventFilter(obj, event)

    # ----------------------------------------------------------------------
    def keyPressEvent(self, event):
        step = 10.0 ** (-self._decimals)
        if event.modifiers() & QtCore.Qt.ShiftModifier:
            step *= 10.0
        if event.key() == QtCore.Qt.Key_Left:
            self.setValue(self._value - step)
        elif event.key() == QtCore.Qt.Key_Right:
            self.setValue(self._value + step)
        else:
            super().keyPressEvent(event)

    # ----------------------------------------------------------------------
    def wheelEvent(self, event):
        event.ignore()

    # ----------------------------------------------------------------------
    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    # ----------------------------------------------------------------------
    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    # ----------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        shape = QtGui.QPainterPath()
        shape.addRoundedRect(rect, 4, 4)
        enabled = self.isEnabled()

        painter.fillPath(shape, self.TRACK)
        span = self._max - self._min
        ratio = (self._value - self._min) / span if span > 0 else 0.0
        if ratio > 0:
            painter.save()
            painter.setClipPath(shape)
            fill = self.FILL if enabled else QtGui.QColor(110, 110, 110, 150)
            painter.fillRect(QtCore.QRectF(rect.left(), rect.top(), rect.width() * ratio, rect.height()), fill)
            painter.restore()

        active = enabled and (self._hover or self.hasFocus() or self._editor is not None)
        painter.setPen(QtGui.QPen(self.EDGE_ACTIVE if active else self.EDGE, 1))
        painter.drawPath(shape)

        if self._editor is None:
            painter.setPen(self.TEXT if enabled else QtGui.QColor("#8a8a8a"))
            painter.drawText(rect, QtCore.Qt.AlignCenter, self.format_value(self._value))
        painter.end()


# ----------------------------------------------------------------------
# Float field with the amber gauge, optionally with tick labels (sun altitude and direction) under it.
class FloatSlider(QtWidgets.QWidget):
    # real value, whether it came from dragging, typing, the arrow keys or setValue()
    valueChanged = QtCore.Signal(float)

    def __init__(self, min_val, max_val, default_val, decimals=2, tick_points=None, snap_points=None):
        super().__init__()
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.gauge = GaugeBar(min_val, max_val, default_val, decimals, snap_points)
        self.layout.addWidget(self.gauge)
        self.gauge.valueChanged.connect(self.valueChanged)

        self.tick_labels = None
        if tick_points:
            self.tick_labels = _SliderTickLabels(tick_points, self)
            self.layout.addWidget(self.tick_labels)

    # ----------------------------------------------------------------------
    def value(self): return self.gauge.value()

    # ----------------------------------------------------------------------
    def setValue(self, val): self.gauge.setValue(val)


# ----------------------------------------
# Integer field with the same gauge.
class IntSlider(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(int)

    def __init__(self, min_val, max_val, default_val):
        super().__init__()
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.gauge = GaugeBar(min_val, max_val, default_val, decimals=0)
        self.layout.addWidget(self.gauge)
        self.gauge.valueChanged.connect(lambda v: self.valueChanged.emit(int(round(v))))

    # ------------------------------------------------------------
    def value(self): return int(round(self.gauge.value()))

    # ----------------------------------------------------------------
    def setValue(self, val): self.gauge.setValue(val)
