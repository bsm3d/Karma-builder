# widgets.py - BSM Karma Builder - combo box, prim tree and the tab scroll wrapper
# Version : 2026.10.15.1 | Revision : 15-10-2026 | Auteur : BSM

import hou
from hutil.Qt import QtWidgets, QtCore, QtGui
from .util import _clamp


# --------------------------------------------------------
class PopupRefreshComboBox(QtWidgets.QComboBox):
    popupAboutToShow = QtCore.Signal()

    # ------------------------------------------------------------
    def showPopup(self):
        self.popupAboutToShow.emit()
        super().showPopup()


# --------------------------------------------------------
# Small square showing an RGB value. Values above 1 (the sliders go up to 2) are clipped for display.
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


# ------------------------------------------------------------
def _asset_mime_type():
    try:
        return hou.qt.mimeType.asset
    except AttributeError:
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

    # ------------------------------------------------------------
    # Select the rows of these prims, return how many exist in the list.
    # The current selection is kept when none of them is listed.
    def select_paths(self, paths):
        items = [self._items[path] for path in paths if path in self._items]
        if not items:
            return 0
        self.clearSelection()
        for item in items:
            item.setSelected(True)
        self.scrollToItem(items[0])
        return len(items)

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


# ------------------------------------------------------------
def wrap_tab(widget):
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    scroll.setWidget(widget)
    return scroll
