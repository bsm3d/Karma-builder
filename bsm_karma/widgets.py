# Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Combo box, prim tree and the tab scroll wrapper
# Houdini : 21 and 22
# Version : 1.0.0

import hou
from hutil.Qt import QtWidgets, QtCore, QtGui
from .config import COLUMN_GAP, ROW_GAP
from .util import _clamp


# --------------------------------------------------------
# Never narrower than its text needs: a fixed width written for one font cuts the label in another one.
def fit_button(button, width=0, height=0):
    hint = button.sizeHint()
    button.setMinimumWidth(max(width, hint.width()))
    if height:
        button.setMinimumHeight(max(height, hint.height()))


# --------------------------------------------------------
def fit_spin(spin, widest_text, width=0):
    spin.setMinimumWidth(max(width, spin.fontMetrics().horizontalAdvance(widest_text) + 24))


# --------------------------------------------------------
def inside(widget, ancestor):
    while ancestor is not None and widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parentWidget()
    return False


# --------------------------------------------------------
# Raises the spacing of every row and column layout under root to the least the tool needs. The layouts of the
# gauges are left alone: they put a gauge and its tick labels at zero distance on purpose.
def space_layouts(root, skip=None):
    from .gauges import FloatSlider, IntSlider
    for layout in root.findChildren(QtWidgets.QBoxLayout):
        try:
            if isinstance(layout.parentWidget(), (FloatSlider, IntSlider)) or inside(layout.parentWidget(), skip):
                continue
            across = layout.direction() in (QtWidgets.QBoxLayout.LeftToRight, QtWidgets.QBoxLayout.RightToLeft)
            wanted = ROW_GAP if across else COLUMN_GAP
            if layout.spacing() < wanted:
                layout.setSpacing(wanted)
        except RuntimeError:
            # a wrapper of a layout Qt already deleted (a layout that was replaced while building)
            continue


# --------------------------------------------------------
class PopupRefreshComboBox(QtWidgets.QComboBox):
    popupAboutToShow = QtCore.Signal()

    # ------------------------------------------------------------
    def showPopup(self):
        self.popupAboutToShow.emit()
        super().showPopup()


# --------------------------------------------------------
class SnapshotPreview(QtWidgets.QLabel):
    EMPTY_HEIGHT = 110
    MIN_HEIGHT = 90
    MAX_HEIGHT = 340

    # ------------------------------------------------------------
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._ratio = None
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setScaledContents(False)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.setTextFormat(QtCore.Qt.PlainText)
        self.setFixedHeight(self.EMPTY_HEIGHT)

    # ------------------------------------------------------------
    def set_ratio(self, ratio):
        self._ratio = ratio if ratio and ratio > 0 else None
        self._fit_height()

    # ------------------------------------------------------------
    def target_height(self, width=None):
        if self._ratio is None:
            return self.EMPTY_HEIGHT
        width = self.width() if width is None else width
        return int(_clamp(round(width * self._ratio), self.MIN_HEIGHT, self.MAX_HEIGHT))

    # ------------------------------------------------------------
    def _fit_height(self):
        height = self.target_height()
        if height != self.height():
            self.setFixedHeight(height)

    # ------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()


# --------------------------------------------------------
class HdriPreview(SnapshotPreview):
    EMPTY_HEIGHT = 70
    MIN_HEIGHT = 60
    MAX_HEIGHT = 240

    # ------------------------------------------------------------
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._source = None

    # ------------------------------------------------------------
    def set_picture(self, image):
        self._source = QtGui.QPixmap.fromImage(image)
        self.set_ratio(image.height() / float(max(1, image.width())))
        self.setText("")
        self._draw()

    # ------------------------------------------------------------
    def set_message(self, text):
        self._source = None
        self.set_ratio(None)
        self.setPixmap(QtGui.QPixmap())
        self.setText(text)

    # ------------------------------------------------------------
    def _draw(self):
        if self._source is None or self._source.isNull():
            return
        size = QtCore.QSize(self.width(), self.target_height())
        if size.width() < 2 or size.height() < 2:
            return
        fitted = self._source.scaled(size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        frame = QtGui.QPixmap(size)
        frame.fill(QtGui.QColor("#1f1f1f"))
        painter = QtGui.QPainter(frame)
        painter.drawPixmap((size.width() - fitted.width()) // 2, (size.height() - fitted.height()) // 2, fitted)
        painter.end()
        self.setPixmap(frame)

    # ------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._draw()


# --------------------------------------------------------
class ColorSwatch(QtWidgets.QWidget):
    EDGE = QtGui.QColor("#3f4246")

    # ------------------------------------------------------------
    def __init__(self, width=44, height=16, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._rgb = (1.0, 1.0, 1.0)

    # ------------------------------------------------------------
    def set_rgb(self, r, g, b):
        self._rgb = (float(r), float(g), float(b))
        self.setToolTip("R {:.2f}  G {:.2f}  B {:.2f}{}".format(
            *self._rgb, "  (above 1: shown clipped)" if max(self._rgb) > 1.0 else ""))
        self.update()

    # ------------------------------------------------------------
    def shown_color(self):
        return QtGui.QColor(*[int(round(_clamp(c, 0.0, 1.0) * 255)) for c in self._rgb])

    # ------------------------------------------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setPen(QtGui.QPen(self.EDGE, 1))
        painter.setBrush(self.shown_color())
        painter.drawRoundedRect(QtCore.QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 3, 3)
        painter.end()


# --------------------------------------------------------
class FlowLayout(QtWidgets.QLayout):

    # ------------------------------------------------------------
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # ------------------------------------------------------------
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    # no direction: the row grows only with its width. The type of "none" depends on the Qt binding.
    def expandingDirections(self):
        for make in (lambda: QtCore.Qt.Orientations(0), lambda: QtCore.Qt.Orientation(0)):
            try:
                return make()
            except (AttributeError, TypeError, ValueError):
                continue
        return QtCore.Qt.Horizontal

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QtCore.QRect(0, 0, width, 0), False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QtCore.QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    # ------------------------------------------------------------
    def _arrange(self, rect, apply):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, row_height = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and row_height > 0:
                x = area.x()
                y += row_height + self._gap
                row_height = 0
            if apply:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x += hint.width() + self._gap
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + margins.bottom()


# --------------------------------------------------------
def linear_to_display(value):
    value = _clamp(float(value), 0.0, 1.0)
    return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1.0 / 2.4) - 0.055


def display_to_linear(value):
    value = _clamp(float(value), 0.0, 1.0)
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


# --------------------------------------------------------
class ColorButton(ColorSwatch):
    valueChanged = QtCore.Signal(float, float, float)

    # ------------------------------------------------------------
    def __init__(self, width=60, height=18, parent=None):
        super().__init__(width, height, parent)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    # ------------------------------------------------------------
    def shown_color(self):
        return QtGui.QColor(*[int(round(linear_to_display(c) * 255)) for c in self._rgb])

    # ------------------------------------------------------------
    def mouseReleaseEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton or not self.rect().contains(_drop_event_pos(event)):
            return
        chosen = QtWidgets.QColorDialog.getColor(self.shown_color(), self.window(), "Color")
        if chosen.isValid():
            rgb = [display_to_linear(chosen.redF()), display_to_linear(chosen.greenF()), display_to_linear(chosen.blueF())]
            self.set_rgb(*rgb)
            self.valueChanged.emit(*rgb)


# ------------------------------------------------------------
def _asset_mime_type():
    try:
        return hou.qt.mimeType.asset
    except AttributeError:
        return ""


# ------------------------------------------------------------
LOCAL_MATERIAL_MIME = "application/x-bsm-karma-materials"


# ------------------------------------------------------------
def _drop_accepted(mime_data):
    return any(mime and mime_data.hasFormat(mime) for mime in (_asset_mime_type(), LOCAL_MATERIAL_MIME))


# ------------------------------------------------------------
# The text of that drop (UnicodeDecodeError when it is not text), None when it holds neither.
def _drop_text(mime_data):
    for mime in (_asset_mime_type(), LOCAL_MATERIAL_MIME):
        if mime and mime_data.hasFormat(mime):
            return bytes(mime_data.data(mime)).decode("utf-8")
    return None


# ------------------------------------------------------------
def _drop_event_pos(event):
    # Qt6 has event.position(), Qt5 only event.pos()
    if hasattr(event, "position"):
        return event.position().toPoint()
    return event.pos()


# ------------------------------------------------------------
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

    # ------------------------------------------------------------
    def select_paths(self, paths):
        items = [self._items[path] for path in paths if path in self._items]
        if not items:
            return 0
        self.clearSelection()
        for item in items:
            item.setSelected(True)
        self.scrollToItem(items[0])
        return len(items)


    # ----------------------------------------------------------------
    def _accepts(self, event):
        return _drop_accepted(event.mimeData())

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
            payload = _drop_text(event.mimeData())
        except (UnicodeDecodeError, TypeError, ValueError):
            payload = None
        if payload is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.assetDropped.emit(payload, "\n".join(paths))


# ------------------------------------------------------------
def wrap_tab(widget):
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    scroll.setWidget(widget)
    return scroll
