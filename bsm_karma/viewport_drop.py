# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Drop of a catalog material onto a prim of the Solaris viewport, applied when the material is dropped there.

# Houdini : 21 and 22

import hou
from hutil.Qt import QtWidgets, QtCore
from .config import VIEWPORT_PICK_FLIP_Y
from .debuglog import _debug
from .widgets import _drop_accepted, _drop_text

# a drag lasts a few seconds: the filter lets go on its own after this
ARM_TIMEOUT_MS = 20000
_DRAG_TYPES = (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove, QtCore.QEvent.Drop)
_CLASS_HINTS = ("viewport", "viewer", "glwidget", "openglwidget")

# ------------------------------------------------------------
def viewer_selection(viewer):
    getter = getattr(viewer, "currentSceneGraphSelection", None)
    if getter is None:
        return []
    try:
        return [str(path) for path in getter() if path]
    except hou.Error as exc:
        _debug("viewport selection unreadable: {}".format(exc))
        return []

# ------------------------------------------------------------
def _viewport_size(viewer):
    try:
        size = tuple(viewer.curViewport().contentSize())
    except (hou.Error, AttributeError, TypeError):
        return None
    if len(size) >= 4:
        return size[-2], size[-1]
    return size if len(size) == 2 else None

# ------------------------------------------------------------
# locateSceneGraphPrim(x, y) returns (depth, path), or (-1, "") when nothing is under the pixel.
def pick_prim(viewer, x, y, height=None, flip=VIEWPORT_PICK_FLIP_Y):
    locate = getattr(viewer, "locateSceneGraphPrim", None)
    if locate is None:
        return ""
    ys = [(height - y) if (flip and height is not None) else y]
    # HACK: not sure of the origin of Y on every build, so the other one is tried when the first finds nothing
    if height is not None:
        ys.append(y if (flip and height is not None) else height - y)
    for py in ys:
        try:
            result = locate(int(x), int(py))
        except hou.Error as exc:
            _debug("locateSceneGraphPrim failed: {}".format(exc))
            return ""
        for item in (result if isinstance(result, (tuple, list)) else [result]):
            if isinstance(item, str) and item.startswith("/"):
                return item
    return ""

# ------------------------------------------------------------
# Qt only delivers a drag to a widget that accepts drops. Visible widgets of the main window with the size of the
# viewport are switched to accept them while a drag may run, and put back afterwards.
def _drop_site_candidates(root, viewer, limit=4):
    size = _viewport_size(viewer)
    if root is None or size is None:
        return []
    found = []
    for widget in root.findChildren(QtWidgets.QWidget):
        if not widget.isVisible() or widget.acceptDrops():
            continue
        dpr = widget.devicePixelRatioF() if hasattr(widget, "devicePixelRatioF") else 1.0
        if abs(widget.width() * dpr - size[0]) <= 2 and abs(widget.height() * dpr - size[1]) <= 2:
            found.append(widget)
            if len(found) >= limit:
                break
    return found

# ------------------------------------------------------------
# The widget under the cursor that is the viewport: its size equals the viewport's content size, or its class
# name says so. The widget classes seen are written to the debug log once, to tune this for a Houdini build.
def _find_viewport_widget(widget, viewer, log_once):
    size = _viewport_size(viewer)
    chain = []
    current = widget
    while current is not None and len(chain) < 6:
        chain.append(current)
        current = current.parentWidget()
    for candidate in chain:
        name = candidate.metaObject().className()
        dpr = candidate.devicePixelRatioF() if hasattr(candidate, "devicePixelRatioF") else 1.0
        if size is not None and abs(candidate.width() * dpr - size[0]) <= 2 and abs(candidate.height() * dpr - size[1]) <= 2:
            return candidate
        if any(hint in name.lower() for hint in _CLASS_HINTS):
            return candidate
    log_once("viewport drop: no viewport widget among {} (content size {})".format(
        [(c.metaObject().className(), c.width(), c.height()) for c in chain], size))
    return None

# ------------------------------------------------------------
# Application-wide filter, armed only while a drag may be running (a drag has started in the catalog) so the rest of
# the time Houdini's events never reach Python. A drop of a catalog material on the viewport emits dropped(payload, prim).
class ViewportDropFilter(QtCore.QObject):
    dropped = QtCore.Signal(str, str)

    # ----------------------------------------------------------------------
    def __init__(self, dialog, viewer_getter, root_getter=None, parent=None):
        super().__init__(parent)
        self._dialog = dialog
        self._viewer_getter = viewer_getter
        self._root_getter = root_getter
        self._opened_sites = []
        self._armed = False
        self._logged = set()
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.disarm)

    # ------------------------------------------------------------
    def arm(self):
        if self._armed:
            self._timer.start(ARM_TIMEOUT_MS)
            return
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._armed = True
        self._timer.start(ARM_TIMEOUT_MS)
        self._open_drop_sites()

    # ------------------------------------------------------------
    def disarm(self):
        if not self._armed:
            return
        self._armed = False
        self._timer.stop()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._close_drop_sites()

    # ------------------------------------------------------------
    def _open_drop_sites(self):
        try:
            viewer = self._viewer_getter()
            root = self._root_getter() if self._root_getter is not None else None
            sites = _drop_site_candidates(root, viewer) if viewer is not None else []
        except (RuntimeError, hou.Error) as exc:
            self._log_once("viewport drop sites not opened: {}".format(exc))
            return
        for widget in sites:
            widget.setAcceptDrops(True)
        self._opened_sites = sites
        self._log_once("viewport drop: {} widget(s) opened for drops: {}".format(
            len(sites), [(w.metaObject().className(), w.width(), w.height()) for w in sites]))

    # ------------------------------------------------------------
    def _close_drop_sites(self):
        sites, self._opened_sites = self._opened_sites, []
        for widget in sites:
            try:
                widget.setAcceptDrops(False)
            except RuntimeError:
                pass   # the widget was deleted meanwhile

    # ------------------------------------------------------------
    def _log_once(self, text):
        if text not in self._logged:
            self._logged.add(text)
            _debug(text)

    # ------------------------------------------------------------
    def _handle(self, obj, event):
        if not _drop_accepted(event.mimeData()):
            return False
        if not isinstance(obj, QtWidgets.QWidget) or obj is self._dialog or self._dialog.isAncestorOf(obj):
            return False
        viewer = self._viewer_getter()
        if viewer is None:
            return False
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        global_pos = obj.mapToGlobal(pos)
        target = _find_viewport_widget(obj, viewer, self._log_once)
        if target is None:
            return False
        if event.type() != QtCore.QEvent.Drop:
            event.acceptProposedAction()
            return True
        local = target.mapFromGlobal(global_pos)
        dpr = target.devicePixelRatioF() if hasattr(target, "devicePixelRatioF") else 1.0
        x, y, height = local.x() * dpr, local.y() * dpr, target.height() * dpr
        prim = pick_prim(viewer, x, y, height)
        _debug("viewport drop at ({:.0f}, {:.0f}) of {:.0f} high -> {!r}".format(x, y, height, prim))
        try:
            payload = _drop_text(event.mimeData())
        except (UnicodeDecodeError, TypeError, ValueError):
            return False
        if payload is None:
            return False
        event.acceptProposedAction()
        self.disarm()
        self.dropped.emit(payload, prim)
        return True

    # ------------------------------------------------------------
    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in _DRAG_TYPES:
            try:
                return self._handle(obj, event)
            except Exception as exc:   # an application-wide filter must never raise into Qt, whatever went wrong
                self._log_once("viewport drop filter failed: {}: {}".format(type(exc).__name__, exc))
                return False
        if kind == QtCore.QEvent.MouseButtonRelease:
            self.disarm()
        return False
