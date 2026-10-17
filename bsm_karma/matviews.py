# Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Thumbnails, list and category views of the material catalog
# Houdini : 21 and 22 (PySide6 only, no hou calls)
# Version : 1.0.0

from hutil.Qt import QtWidgets, QtCore
from .config import MATERIAL_VIEW_DEPTH, MATERIAL_VIEW_LIMIT
from .debuglog import _debug
from .widgets import _asset_mime_type, _drop_event_pos

VIEW_MODES = ("Thumbnails", "List", "Categories")


# ------------------------------------------------------------
def find_gallery_view(gallery):
    if gallery is None:
        return None
    views = gallery.findChildren(QtWidgets.QAbstractItemView)
    if isinstance(gallery, QtWidgets.QAbstractItemView):
        views.insert(0, gallery)
    for view in views:
        if view.model() is not None:
            return view
    return None


# ------------------------------------------------------------
def payload_from_indexes(model, indexes):
    mime_type = _asset_mime_type()
    if model is None or not mime_type or not indexes:
        return ""
    try:
        data = _model_call(model, "mimeData", indexes)
        if data is None or not data.hasFormat(mime_type):
            return ""
        return bytes(data.data(mime_type)).decode("utf-8")
    except (UnicodeDecodeError, TypeError, ValueError, RuntimeError):
        return ""


# ------------------------------------------------------------
def selected_payload(view):
    if view is None or view.selectionModel() is None:
        return ""
    rows = {}
    for index in view.selectionModel().selectedIndexes():
        rows.setdefault((index.parent(), index.row()), index.sibling(index.row(), 0))
    return payload_from_indexes(view.model(), list(rows.values()))


# ------------------------------------------------------------
# Houdini's gallery model is a QAbstractListModel: PySide refuses hasChildren, parent and columnCount on it ("is a
# private method"). The same call through QAbstractItemModel goes to the C++ object and is allowed.
def _model_call(model, name, *args):
    try:
        return getattr(model, name)(*args)
    except TypeError:
        return getattr(QtCore.QAbstractItemModel, name)(model, *args)


# ------------------------------------------------------------
def _is_folder(model, index):
    try:
        return bool(_model_call(model, "hasChildren", index) or _model_call(model, "canFetchMore", index))
    except (TypeError, AttributeError, RuntimeError):
        return model.rowCount(index) > 0


# ------------------------------------------------------------
def describe_model(model):
    try:
        kind = " > ".join(klass.__name__ for klass in type(model).__mro__ if klass.__name__ not in ("object", "Object", "Shiboken"))
        parts = ["material model: {} | rows {}".format(kind, model.rowCount())]
        if model.rowCount():
            index = model.index(0, 0)
            roles = {}
            for role in list(range(0, 12)) + list(range(int(QtCore.Qt.UserRole), int(QtCore.Qt.UserRole) + 24)):
                value = index.data(role)
                if value not in (None, "", 0):
                    roles[role] = str(value)[:60]
            parts.append("row 0 roles {}".format(roles))
        return " | ".join(parts)
    except (TypeError, AttributeError, RuntimeError, ValueError) as exc:
        return "material model: could not be described ({}: {})".format(type(exc).__name__, exc)


# ------------------------------------------------------------
# Leaves of the gallery model with the folder names above them. Only rows already loaded are read: asking a
# lazy model for more could start a download.
def walk_model(model, limit=MATERIAL_VIEW_LIMIT):
    found = []

    def visit(parent, trail):
        for row in range(model.rowCount(parent)):
            if len(found) >= limit:
                return
            index = model.index(row, 0, parent)
            text = str(index.data(QtCore.Qt.DisplayRole) or "")
            # a model that ignores the parent in rowCount would make every row a folder of itself: stop at a depth
            if len(trail) < MATERIAL_VIEW_DEPTH and _is_folder(model, index):
                # a folder; one that is not loaded yet shows nothing here, opening it in Thumbnails loads it
                visit(index, trail + [text])
            else:
                found.append((text, list(trail), QtCore.QPersistentModelIndex(index)))

    visit(QtCore.QModelIndex(), [])
    return found


# --------------------------------------------------
def _to_index(persistent):
    if persistent is None or not persistent.isValid():
        return None
    return persistent.model().index(persistent.row(), persistent.column(), persistent.parent())


# --------------------------------------------------
# QTreeWidgetItem.data takes a column, QListWidgetItem.data does not
def _item_persistent(item):
    if isinstance(item, QtWidgets.QTreeWidgetItem):
        return item.data(0, QtCore.Qt.UserRole)
    return item.data(QtCore.Qt.UserRole)


# --------------------------------------------------
class _ModelItemsMixin:
    def _indexes(self, items):
        indexes = [_to_index(_item_persistent(item)) for item in items]
        return [index for index in indexes if index is not None]

    def mimeData(self, items):
        indexes = self._indexes(items)
        try:
            data = _model_call(self._source_model, "mimeData", indexes) if indexes and self._source_model is not None else None
        except (TypeError, RuntimeError):
            data = None
        return data if data is not None else QtCore.QMimeData()

    def selected_payload(self):
        return payload_from_indexes(self._source_model, self._indexes(self.selectedItems()))


class MaterialListWidget(_ModelItemsMixin, QtWidgets.QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_model = None
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAlternatingRowColors(True)
        self.setUniformItemSizes(True)

    def fill(self, model, rows):
        self._source_model = model
        self.setUpdatesEnabled(False)
        self.clear()
        for text, trail, persistent in sorted(rows, key=lambda row: (row[0].lower(), row[1])):
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, persistent)
            if trail:
                item.setToolTip(" / ".join(trail + [text]))
            self.addItem(item)
        self.setUpdatesEnabled(True)


class MaterialCategoryTree(_ModelItemsMixin, QtWidgets.QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_model = None
        self.setHeaderHidden(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAlternatingRowColors(True)

    def fill(self, model, rows):
        self._source_model = model
        self.setUpdatesEnabled(False)
        self.clear()
        groups = {}
        for text, trail, persistent in sorted(rows, key=lambda row: (row[1], row[0].lower())):
            parent = None
            key = ()
            for name in trail or ["All materials"]:
                key = key + (name,)
                node = groups.get(key)
                if node is None:
                    node = QtWidgets.QTreeWidgetItem([name])
                    node.setFlags(node.flags() & ~QtCore.Qt.ItemIsDragEnabled)
                    node.setData(0, QtCore.Qt.UserRole, None)
                    (parent.addChild if parent is not None else self.addTopLevelItem)(node)
                    groups[key] = node
                parent = node
            leaf = QtWidgets.QTreeWidgetItem([text])
            leaf.setData(0, QtCore.Qt.UserRole, persistent)
            parent.addChild(leaf)
        for key, node in groups.items():
            node.setText(0, "{} ({})".format(key[-1], node.childCount()))
        self.expandToDepth(0)
        self.setUpdatesEnabled(True)


# ------------------------------------------------------------
# Switch between Houdini's thumbnails and two plain lists of the same materials. A right click on a material
# emits contextRequested(global position) after selecting it; a left press followed by a move of a drag's length emits
# dragStarted (once per press), just before the view starts its own drag.
class MaterialBrowser(QtWidgets.QWidget):
    contextRequested = QtCore.Signal(QtCore.QPoint)
    dragStarted = QtCore.Signal()

    # ----------------------------------------------------------------------
    def __init__(self, gallery, parent=None):
        super().__init__(parent)
        self._gallery = gallery
        self._gallery_view = find_gallery_view(gallery)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        row = QtWidgets.QHBoxLayout()
        self.combo_view = QtWidgets.QComboBox()
        self.combo_view.addItems(VIEW_MODES)
        self.combo_view.setMinimumWidth(104)
        self.combo_view.setToolTip("Thumbnails: Houdini's gallery. List and Categories: the same materials as text.")
        self.combo_view.currentIndexChanged.connect(self._on_mode)
        row.addWidget(QtWidgets.QLabel("View:"))
        row.addWidget(self.combo_view)
        row.addStretch(1)
        layout.addLayout(row)

        self.stack = QtWidgets.QStackedWidget()
        self.list_view = MaterialListWidget()
        self.tree_view = MaterialCategoryTree()
        self.stack.addWidget(gallery)
        self.stack.addWidget(self.list_view)
        self.stack.addWidget(self.tree_view)
        layout.addWidget(self.stack, 1)

        self._events = _ViewEvents(self)
        for view in (self._gallery_view, self.list_view, self.tree_view):
            if view is not None:
                view.viewport().installEventFilter(self._events)

        self._refill = QtCore.QTimer(self)
        self._refill.setSingleShot(True)
        self._refill.setInterval(300)
        self._refill.timeout.connect(self._fill_text_views)
        self._bound_model = None
        self.rebind_model()
        if self._bound_model is None:
            _debug("material browser: no item view found inside the gallery, only thumbnails are available")
            self.combo_view.setEnabled(False)

    # ------------------------------------------------------------
    def rebind_model(self):
        model = self._gallery_view.model() if self._gallery_view is not None else None
        if model is self._bound_model:
            return
        if self._bound_model is not None:
            for signal in self._model_signals(self._bound_model):
                try:
                    signal.disconnect(self._refill_later)
                except (RuntimeError, TypeError):
                    pass   # the old model is already gone
        self._bound_model = model
        if model is not None:
            _debug(describe_model(model))
            for signal in self._model_signals(model):
                signal.connect(self._refill_later)
            self._refill_later()

    # ------------------------------------------------------------
    @staticmethod
    def _model_signals(model):
        return (model.modelReset, model.rowsInserted, model.rowsRemoved, model.layoutChanged)

    # ------------------------------------------------------------
    def _refill_later(self, *_):
        if self.stack.currentIndex() != 0:
            self._refill.start()

    # ------------------------------------------------------------
    def _on_mode(self, index):
        self.stack.setCurrentIndex(index)
        if index != 0:
            self._fill_text_views()

    # --------------------------------------------------
    def _fill_text_views(self):
        model = self._gallery_view.model() if self._gallery_view is not None else None
        if model is None:
            return
        try:
            rows = walk_model(model)
        except (TypeError, AttributeError, RuntimeError) as exc:
            _debug("material browser: the catalog model cannot be listed ({}: {})".format(type(exc).__name__, exc), "WARN")
            rows = []
        if self.stack.currentIndex() == 1:
            self.list_view.fill(model, rows)
        elif self.stack.currentIndex() == 2:
            self.tree_view.fill(model, rows)

    # ------------------------------------------------------------
    def refresh(self):
        self.rebind_model()
        self._fill_text_views()

    # ------------------------------------------------------------
    def current_view(self):
        return (self._gallery_view, self.list_view, self.tree_view)[self.stack.currentIndex()]

    # ------------------------------------------------------------
    def current_payload(self):
        view = self.current_view()
        if isinstance(view, _ModelItemsMixin):
            return view.selected_payload()
        return selected_payload(view)

    # ------------------------------------------------------------
    def _select_under(self, view, pos):
        if isinstance(view, QtWidgets.QTreeWidget):
            item = view.itemAt(pos)
            if item is None or _item_persistent(item) is None:
                return False
            if not item.isSelected():
                view.clearSelection()
                item.setSelected(True)
            return True
        if isinstance(view, QtWidgets.QListWidget):
            item = view.itemAt(pos)
            if item is None:
                return False
            if not item.isSelected():
                view.clearSelection()
                item.setSelected(True)
            return True
        index = view.indexAt(pos)
        if not index.isValid():
            return False
        if not view.selectionModel().isSelected(index):
            view.selectionModel().select(index, QtCore.QItemSelectionModel.ClearAndSelect)
        return True


# ------------------------------------------------------------
class _ViewEvents(QtCore.QObject):
    def __init__(self, browser):
        super().__init__(browser)
        self._browser = browser
        self._press_pos = None

    # --------------------------------------------------
    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            self._press_pos = _drop_event_pos(event)
            return False
        if kind == QtCore.QEvent.MouseButtonRelease:
            self._press_pos = None
            return False
        if kind == QtCore.QEvent.MouseMove and self._press_pos is not None and event.buttons() & QtCore.Qt.LeftButton:
            if (_drop_event_pos(event) - self._press_pos).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                self._press_pos = None
                self._browser.dragStarted.emit()
            return False
        if kind == QtCore.QEvent.ContextMenu:
            view = self._browser.current_view()
            if view is None or obj is not view.viewport():
                return False
            if self._browser._select_under(view, _drop_event_pos(event)):
                self._browser.contextRequested.emit(event.globalPos())
                return True
        return False
