# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Window to download MaterialX materials from ambientCG and Poly Haven
# Houdini : 21 and 22
# Version : 1.0.0

import hou
import os
import threading
import time
import zipfile
from hutil.Qt import QtWidgets, QtCore, QtGui
from .config import FORM_LABEL_GAP
from .debuglog import _debug, _guarded_slot
from .mxsources import (AMBIENTCG_RESOLUTIONS, POLYHAVEN_RESOLUTIONS, DownloadCancelled, DownloadError, ambientcg_catalog,
                        ambientcg_names, check_name, download_ambientcg, download_polyhaven, list_files, polyhaven_catalog,
                        polyhaven_names, safe_extract)
from .localmaterials import local_payload, preview_picture, thumbnail
from .styles import _C, _btn_style
from .util import _expand_plain_path
from .widgets import LOCAL_MATERIAL_MIME, space_layouts

SOURCE_AMBIENTCG = "ambientCG"
SOURCE_POLYHAVEN = "Poly Haven"
SOURCES = (SOURCE_AMBIENTCG, SOURCE_POLYHAVEN)
SOURCE_SITES = {SOURCE_AMBIENTCG: "https://ambientcg.com", SOURCE_POLYHAVEN: "https://polyhaven.com/textures"}

# a window closed while a download runs hands its thread over to this list until the thread ends
_ORPHANS = []

THUMBNAIL_EDGE = 48
THUMBNAILS_AT_ONCE = 3


# ------------------------------------------------------------
# A job runs in a thread: job(log, cancel) returns a result. The thread never raises into Qt: every failure comes
# back as text through done(result, error).
class _Worker(QtCore.QThread):
    message = QtCore.Signal(str)
    done = QtCore.Signal(object, str)

    # ------------------------------------------------------------
    def __init__(self, job, parent=None):
        super().__init__(parent)
        self._job = job
        self.cancel = threading.Event()

    # ------------------------------------------------------------
    def run(self):
        try:
            result = self._job(self.message.emit, self.cancel)
            self.done.emit(result, "")
        except DownloadCancelled:
            self.done.emit(None, "Stopped.")
        except (DownloadError, ValueError, OSError, zipfile.BadZipFile) as exc:
            self.done.emit(None, str(exc))
        except Exception as exc:   # a thread must not raise: whatever else went wrong is reported
            _debug("download thread failed: {}: {}".format(type(exc).__name__, exc))
            self.done.emit(None, "{}: {}".format(type(exc).__name__, exc))


# ------------------------------------------------------------
# The downloaded materials, one row each with a thumbnail. A drag carries the files (localmaterials.local_payload) for
# the prim list and the Solaris viewport of the tool, and tells the window that a drag has started.
class DownloadedMaterialList(QtWidgets.QListWidget):
    dragStarted = QtCore.Signal()

    # ------------------------------------------------------------
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)
        self.setIconSize(QtCore.QSize(THUMBNAIL_EDGE, THUMBNAIL_EDGE))
        self.setAlternatingRowColors(True)
        self.setUniformItemSizes(True)

    # ------------------------------------------------------------
    def mimeTypes(self):
        return [LOCAL_MATERIAL_MIME]

    # ------------------------------------------------------------
    def mimeData(self, items):
        data = QtCore.QMimeData()
        paths = [item.data(QtCore.Qt.UserRole) for item in items if item.data(QtCore.Qt.UserRole)]
        data.setData(LOCAL_MATERIAL_MIME, local_payload(paths).encode("utf-8"))
        return data

    # ------------------------------------------------------------
    def startDrag(self, supported_actions):
        self.dragStarted.emit()
        super().startDrag(QtCore.Qt.CopyAction)


# ------------------------------------------------------------
class MaterialDownloadDialog(QtWidgets.QDialog):
    fileChosen = QtCore.Signal(str)
    dragStarted = QtCore.Signal()
    assignRequested = QtCore.Signal(str)

    # ----------------------------------------------------------------------
    # session_factory is for tests: a function that returns an object with requests' get().
    def __init__(self, default_folder, settings=None, parent=None, session_factory=None):
        super().__init__(parent)
        self.setWindowTitle("Download MaterialX Materials")
        self.resize(560, 700)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self._settings = settings if settings is not None else self._make_settings()
        self._session_factory = session_factory or self._requests_session
        self._worker = None
        self._catalogs = {}
        self._started = 0.0
        self._build_ui(default_folder)
        self._load_settings()

    # ------------------------------------------------------------
    @staticmethod
    def _make_settings():
        try:
            return QtCore.QSettings("BSM", "KarmaBuilder")
        except RuntimeError:
            return None

    # ------------------------------------------------------------
    @staticmethod
    def _requests_session():
        import requests
        return requests.Session()

    # ------------------------------------------------------------
    def _build_ui(self, default_folder):
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.combo_source = QtWidgets.QComboBox()
        self.combo_source.addItems(SOURCES)
        self.combo_source.currentIndexChanged.connect(self._update_source_ui)
        form.addRow("Source:", self.combo_source)

        self.line_name = QtWidgets.QLineEdit()
        self.lbl_name = QtWidgets.QLabel("Material name:")
        form.addRow(self.lbl_name, self.line_name)
        self.combo_resolution = QtWidgets.QComboBox()
        form.addRow("Resolution:", self.combo_resolution)
        self.combo_format = QtWidgets.QComboBox()
        self.combo_format.addItems(["PNG", "JPG"])
        self.lbl_format = QtWidgets.QLabel("Image format:")
        form.addRow(self.lbl_format, self.combo_format)

        row_folder = QtWidgets.QHBoxLayout()
        self.line_folder = QtWidgets.QLineEdit(default_folder)
        btn_browse = QtWidgets.QPushButton("...")
        btn_browse.setMaximumWidth(40)
        btn_browse.clicked.connect(self.browse_folder)
        row_folder.addWidget(self.line_folder, 1)
        row_folder.addWidget(btn_browse)
        form.addRow("Download to:", row_folder)
        layout.addLayout(form)

        row_run = QtWidgets.QHBoxLayout()
        self.btn_download = QtWidgets.QPushButton("Download")
        self.btn_download.setStyleSheet(_btn_style(_C["amber"]))
        self.btn_download.clicked.connect(self.start_download)
        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_job)
        self.btn_site = QtWidgets.QPushButton("Open Website")
        self.btn_site.clicked.connect(self.open_site)
        row_run.addWidget(self.btn_download, 1)
        row_run.addWidget(self.btn_stop)
        row_run.addWidget(self.btn_site)
        layout.addLayout(row_run)

        row_browse = QtWidgets.QHBoxLayout()
        self.line_filter = QtWidgets.QLineEdit()
        self.line_filter.setPlaceholderText("Filter the list of names")
        self.line_filter.textChanged.connect(self._fill_names)
        self.btn_list = QtWidgets.QPushButton("Load List")
        self.btn_list.setToolTip("Ask the site for the names of its materials, to pick one.")
        self.btn_list.clicked.connect(self.load_catalog)
        row_browse.addWidget(self.line_filter, 1)
        row_browse.addWidget(self.btn_list)
        layout.addLayout(row_browse)
        self.list_names = QtWidgets.QListWidget()
        self.list_names.setMinimumHeight(90)
        self.list_names.currentItemChanged.connect(self._name_picked)
        layout.addWidget(self.list_names, 1)

        self.txt_output = QtWidgets.QPlainTextEdit()
        self.txt_output.setReadOnly(True)
        self.txt_output.setMinimumHeight(90)
        layout.addWidget(self.txt_output, 1)

        lbl_drag = QtWidgets.QLabel("Downloaded materials: drag one onto a prim of the Materials tab or onto the Solaris viewport.")
        lbl_drag.setWordWrap(True)
        layout.addWidget(lbl_drag)
        self.list_files = DownloadedMaterialList()
        self.list_files.setMinimumHeight(140)
        self.list_files.itemDoubleClicked.connect(lambda *_: self.assign_selected())
        self.list_files.dragStarted.connect(self.dragStarted)
        layout.addWidget(self.list_files, 2)

        self.chk_auto_assign = QtWidgets.QCheckBox("Assign to the selected prims when a download ends")
        self.chk_auto_assign.setToolTip("Select prims in the Materials tab (or in the Solaris viewport) first: the material you download "
                                        "is bound to them as soon as it is unpacked.")
        layout.addWidget(self.chk_auto_assign)

        row_use = QtWidgets.QHBoxLayout()
        self.btn_assign = QtWidgets.QPushButton("Assign to Selection")
        self.btn_assign.setToolTip("Bind the selected material to the prims selected in the Materials tab or in the Solaris viewport. "
                                   "A double click does the same.")
        self.btn_assign.clicked.connect(self.assign_selected)
        self.btn_use = QtWidgets.QPushButton("Use in Catalog")
        self.btn_use.setToolTip("Show the selected file's materials in the Materials tab.")
        self.btn_use.clicked.connect(self.use_selected)
        btn_open = QtWidgets.QPushButton("Open Folder")
        btn_open.clicked.connect(self.open_folder)
        btn_refresh = QtWidgets.QPushButton("Refresh")
        btn_refresh.clicked.connect(self.refresh_files)
        row_use.addWidget(self.btn_assign, 1)
        row_use.addWidget(self.btn_use)
        row_use.addWidget(btn_open)
        row_use.addWidget(btn_refresh)
        layout.addLayout(row_use)
        self._thumbnail_queue = []
        self._thumbnail_timer = QtCore.QTimer(self)
        self._thumbnail_timer.setSingleShot(True)
        self._thumbnail_timer.timeout.connect(self._next_thumbnails)
        for form in self.findChildren(QtWidgets.QFormLayout):
            form.setHorizontalSpacing(FORM_LABEL_GAP)
        space_layouts(self)
        self._update_source_ui()

    # ------------------------------------------------------------
    def _update_source_ui(self, *_):
        source = self.combo_source.currentText()
        self.combo_resolution.clear()
        if source == SOURCE_AMBIENTCG:
            self.combo_resolution.addItems(["{}K".format(r) for r in AMBIENTCG_RESOLUTIONS])
            self.line_name.setPlaceholderText("WoodFloor038")
            self.lbl_name.setText("Material name:")
        else:
            self.combo_resolution.addItems(list(POLYHAVEN_RESOLUTIONS))
            self.line_name.setPlaceholderText("polystyrene")
            self.lbl_name.setText("Asset id:")
        self.combo_resolution.setCurrentIndex(1)
        self.lbl_format.setVisible(source == SOURCE_AMBIENTCG)
        self.combo_format.setVisible(source == SOURCE_AMBIENTCG)
        self._fill_names()

    # ------------------------------------------------------------
    def _load_settings(self):
        if self._settings is None:
            return
        try:
            folder = self._settings.value("folder", "")
            source = self._settings.value("source", "")
        except (RuntimeError, TypeError):
            return
        try:
            self.chk_auto_assign.setChecked(str(self._settings.value("autoassign", "0")) == "1")
        except (RuntimeError, TypeError):
            pass
        if folder:
            self.line_folder.setText(str(folder))
        index = self.combo_source.findText(str(source))
        if index >= 0:
            self.combo_source.setCurrentIndex(index)

    # ------------------------------------------------------------
    def _save_settings(self):
        if self._settings is None:
            return
        try:
            self._settings.setValue("folder", self.line_folder.text().strip())
            self._settings.setValue("source", self.combo_source.currentText())
            self._settings.setValue("autoassign", "1" if self.chk_auto_assign.isChecked() else "0")
        except RuntimeError:
            pass

    # ------------------------------------------------------------
    def _log(self, text):
        self.txt_output.moveCursor(QtGui.QTextCursor.End)
        self.txt_output.insertPlainText(text if text.endswith("\n") else text + "\n")
        self.txt_output.ensureCursorVisible()

    # ------------------------------------------------------------
    @_guarded_slot
    def browse_folder(self):
        path = hou.ui.selectFile(start_directory=self.line_folder.text(), title="Download Folder",
                                 file_type=hou.fileType.Directory, chooser_mode=hou.fileChooserMode.Read)
        if path:
            try:
                self.line_folder.setText(_expand_plain_path(path).rstrip("/\\"))
            except ValueError as exc:
                self._log("Folder not changed: {}".format(exc))

    # ------------------------------------------------------------
    def _folder(self):
        folder = _expand_plain_path(self.line_folder.text().strip())
        if not folder or not os.path.isabs(folder):
            raise ValueError("choose a full path for the download folder")
        os.makedirs(folder, exist_ok=True)
        return folder.replace("\\", "/")

    # ------------------------------------------------------------
    def _busy(self, running):
        self.btn_download.setEnabled(not running)
        self.btn_list.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    # ------------------------------------------------------------
    def _start(self, job, on_done):
        if self._worker is not None:
            return
        worker = _Worker(job, self)
        worker.message.connect(self._log)
        worker.done.connect(lambda result, error: self._job_done(result, error, on_done))
        self._worker = worker
        self._started = time.time()
        self._busy(True)
        worker.start()

    # ------------------------------------------------------------
    @_guarded_slot
    def _job_done(self, result, error, on_done):
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.wait(2000)
            worker.deleteLater()
        self._busy(False)
        if error:
            self._log(error)
        on_done(result, error)

    # ------------------------------------------------------------
    @_guarded_slot
    def stop_job(self):
        if self._worker is not None:
            self._worker.cancel.set()
            self._log("Stopping ...")

    # ------------------------------------------------------------
    # Names of the source: kept in memory for the session, asked once.
    @_guarded_slot
    def load_catalog(self):
        source = self.combo_source.currentText()
        factory = self._session_factory

        def job(log, cancel):
            log("Asking {} for its list ...".format(source))
            session = factory()
            if source == SOURCE_AMBIENTCG:
                return ambientcg_catalog(session, cancel)
            return polyhaven_catalog(session, cancel)

        def done(result, error):
            if error or result is None:
                return
            self._catalogs[source] = result
            self._fill_names()
            self._log("{} names loaded.".format(self.list_names.count()))

        self._start(job, done)

    # ------------------------------------------------------------
    def _names(self):
        source = self.combo_source.currentText()
        data = self._catalogs.get(source)
        if data is None:
            return []
        return ambientcg_names(data) if source == SOURCE_AMBIENTCG else polyhaven_names(data)

    # ------------------------------------------------------------
    def _fill_names(self, *_):
        text = self.line_filter.text().strip().lower()
        self.list_names.blockSignals(True)
        self.list_names.clear()
        for name in self._names():
            if text in name.lower():
                self.list_names.addItem(name)
                if self.list_names.count() >= 400:
                    break
        self.list_names.blockSignals(False)

    # ------------------------------------------------------------
    def _name_picked(self, item, *_):
        if item is not None:
            self.line_name.setText(item.text())

    # ------------------------------------------------------------
    @_guarded_slot
    def start_download(self):
        source = self.combo_source.currentText()
        try:
            folder = self._folder()
            name = check_name(self.line_name.text())
        except (ValueError, OSError) as exc:
            self._log("Not started: {}".format(exc))
            return
        resolution = self.combo_resolution.currentText().rstrip("Kk") if source == SOURCE_AMBIENTCG else self.combo_resolution.currentText()
        fmt = self.combo_format.currentText()
        factory = self._session_factory
        catalog = self._catalogs.get(source)
        self._save_settings()

        def job(log, cancel):
            session = factory()
            if source == SOURCE_AMBIENTCG:
                rows = catalog if catalog is not None else ambientcg_catalog(session, cancel)
                path = download_ambientcg(session, rows, name, resolution, fmt, folder, log, cancel)
                target = safe_extract(path, folder)
                log("Unpacked to {}".format(target))
                return target
            path = download_polyhaven(session, name, resolution, folder, log, cancel)
            return os.path.dirname(path)

        def done(result, error):
            if not error:
                self._log("Done: {}".format(result))
            self.refresh_files()
            if not error and self.chk_auto_assign.isChecked():
                self._assign_new_files()

        self._start(job, done)

    # ------------------------------------------------------------
    @_guarded_slot
    def refresh_files(self):
        self._thumbnail_timer.stop()
        self._thumbnail_queue = []
        self.list_files.clear()
        try:
            folder = self._folder()
        except (ValueError, OSError):
            return
        files = sorted(list_files(folder, ".mtlx"), key=os.path.getmtime, reverse=True)
        for path in files[:300]:
            item = QtWidgets.QListWidgetItem(os.path.splitext(os.path.basename(path))[0])
            item.setData(QtCore.Qt.UserRole, path.replace("\\", "/"))
            item.setToolTip(path)
            self.list_files.addItem(item)
            self._thumbnail_queue.append(item)
            if os.path.getmtime(path) >= self._started - 1 and self._started:
                item.setSelected(True)
        if self.list_files.count() and not self.list_files.selectedItems():
            self.list_files.item(0).setSelected(True)
        self._thumbnail_timer.start(0)

    # ------------------------------------------------------------
    # Thumbnails a few at a time so that the window stays alive while 300 pictures are read.
    def _next_thumbnails(self):
        for _ in range(THUMBNAILS_AT_ONCE):
            if not self._thumbnail_queue:
                return
            item = self._thumbnail_queue.pop(0)
            try:
                item.setIcon(thumbnail(preview_picture(item.data(QtCore.Qt.UserRole)), THUMBNAIL_EDGE))
            except RuntimeError:
                return   # the list was cleared meanwhile
        self._thumbnail_timer.start(0)

    # ------------------------------------------------------------
    def download_folder(self):
        try:
            return self._folder()
        except (ValueError, OSError):
            return ""

    # ------------------------------------------------------------
    @_guarded_slot
    def assign_selected(self):
        items = self.list_files.selectedItems()
        if not items:
            self._log("Select a material in the list first.")
            return
        for item in items:
            self.assignRequested.emit(item.data(QtCore.Qt.UserRole))

    # ------------------------------------------------------------
    # The files that the last download wrote: the ones of the list that are newer than its start.
    def _assign_new_files(self):
        fresh = [self.list_files.item(i) for i in range(self.list_files.count())
                 if os.path.getmtime(self.list_files.item(i).data(QtCore.Qt.UserRole)) >= self._started - 1]
        for item in fresh[:1]:
            self.assignRequested.emit(item.data(QtCore.Qt.UserRole))

    # ------------------------------------------------------------
    @_guarded_slot
    def use_selected(self):
        items = self.list_files.selectedItems()
        if not items:
            self._log("Select a file in the list first.")
            return
        self.fileChosen.emit(items[0].data(QtCore.Qt.UserRole))

    # ------------------------------------------------------------
    @_guarded_slot
    def open_folder(self):
        try:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self._folder()))
        except (ValueError, OSError) as exc:
            self._log("Not opened: {}".format(exc))

    # ------------------------------------------------------------
    @_guarded_slot
    def open_site(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(SOURCE_SITES[self.combo_source.currentText()]))

    # ------------------------------------------------------------
    def closeEvent(self, event):
        self._thumbnail_timer.stop()
        self._save_settings()
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.cancel.set()
            if not worker.wait(1500):
                # still inside a request: the thread ends on its own, nothing may destroy it before, and its results
                # have nobody to go to any more
                for signal in (worker.message, worker.done):
                    try:
                        signal.disconnect()
                    except (RuntimeError, TypeError):
                        pass
                worker.setParent(None)
                _ORPHANS.append(worker)
                worker.finished.connect(lambda w=worker: _ORPHANS.remove(w) if w in _ORPHANS else None)
        super().closeEvent(event)
