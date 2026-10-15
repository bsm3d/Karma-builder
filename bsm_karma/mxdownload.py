# mxdownload.py - BSM Karma Builder - download MaterialX materials with the materialxmaterials tool, from a window
# Version : 2026.10.15.1 | Revision : 15-10-2026 | Auteur : BSM

import hou
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from hutil.Qt import QtWidgets, QtCore, QtGui
from .debuglog import _guarded_slot
from .styles import _C, _btn_style
from .util import _expand_plain_path

SOURCE_AMBIENTCG = "ambientCG"
SOURCE_POLYHAVEN = "Poly Haven"
SOURCE_PHYSBASED = "PhysicallyBased"
SOURCES = (SOURCE_AMBIENTCG, SOURCE_POLYHAVEN, SOURCE_PHYSBASED)

SOURCE_SITES = {
    SOURCE_AMBIENTCG: "https://ambientcg.com",
    SOURCE_POLYHAVEN: "https://polyhaven.com/textures",
    SOURCE_PHYSBASED: "https://physicallybased.info",
}

AMBIENTCG_RESOLUTIONS = ("1", "2", "4", "8")
POLYHAVEN_RESOLUTIONS = ("1k", "2k", "4k", "8k")
SHADING_MODELS = ("all", "standard_surface", "open_pbr_surface", "gltf_pbr")

# no leading dash: the value would be read as an option by the command
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
CHECK_TIMEOUT_SECONDS = 25
ZIP_MAX_FILES = 5000
ZIP_MAX_BYTES = 4 * 1024 ** 3
SETTINGS_KEYS = ("python", "folder", "source")


# ------------------------------------------------------------
def _no_window():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ------------------------------------------------------------
# Commands that may start a Python with the tool: the Windows launcher, then python and python3 of the PATH.
def find_python_candidates():
    found = []
    if sys.platform.startswith("win") and shutil.which("py"):
        found.append(["py", "-3"])
    for name in ("python", "python3"):
        path = shutil.which(name)
        if path and [path] not in found:
            found.append([path])
    return found


# ------------------------------------------------------------
# (ok, text): the Python version when materialxmaterials imports, else why it does not.
def check_python(command, timeout=CHECK_TIMEOUT_SECONDS):
    try:
        result = subprocess.run(
            list(command) + ["-c", "import materialxMaterials, sys; print(sys.version.split()[0])"],
            capture_output=True, text=True, timeout=timeout, creationflags=_no_window())
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return False, "{}: {}".format(type(exc).__name__, exc)
    if result.returncode != 0:
        last = (result.stderr or result.stdout or "").strip().splitlines()
        return False, last[-1][:160] if last else "exit code {}".format(result.returncode)
    return True, result.stdout.strip()


# ------------------------------------------------------------
def first_working_python(candidates=None):
    for command in (candidates if candidates is not None else find_python_candidates()):
        ok, text = check_python(command)
        if ok:
            return command, text
    return None, ""


# ------------------------------------------------------------
def split_command(text):
    text = text.strip()
    if not text:
        return []
    if os.path.isfile(text):
        return [text]
    parts = text.split()
    return parts if parts and (shutil.which(parts[0]) or os.path.isfile(parts[0])) else []


# ------------------------------------------------------------
# Arguments of the materialxmaterials command for a source. fields: name, resolution, fmt, model. Raises ValueError.
def build_arguments(source, fields, folder):
    if source not in SOURCES:
        raise ValueError("unknown source {!r}".format(source))
    base = ["-m", "materialxMaterials"]
    if source == SOURCE_AMBIENTCG:
        name = str(fields.get("name", "")).strip()
        resolution = str(fields.get("resolution", "2"))
        fmt = str(fields.get("fmt", "PNG")).upper()
        if not NAME_RE.match(name):
            raise ValueError("the material name must be letters, digits, _ . - (for example WoodFloor038)")
        if resolution not in AMBIENTCG_RESOLUTIONS or fmt not in ("PNG", "JPEG"):
            raise ValueError("resolution or format not offered by ambientCG")
        return base + ["acg", "-m", name, "-r", resolution, "-f", fmt, "--output", folder]
    if source == SOURCE_POLYHAVEN:
        name = str(fields.get("name", "")).strip()
        resolution = str(fields.get("resolution", "2k"))
        if not NAME_RE.match(name):
            raise ValueError("the asset id must be letters, digits, _ . - (for example polystyrene)")
        if resolution not in POLYHAVEN_RESOLUTIONS:
            raise ValueError("resolution not offered by Poly Haven")
        return base + ["polyhaven", "-id", name, "-dt", "mtlx", "-res", resolution, "-c", "1", "-x", "-fe", "-df", folder]
    model = str(fields.get("model", "all"))
    if model not in SHADING_MODELS:
        raise ValueError("unknown shading model")
    args = base + ["physbased", "-o", folder]
    if model != "all":
        args += ["-m", model]
    return args


# ------------------------------------------------------------
# Unzip into a folder named after the archive. Nothing may land outside it, and the size is capped: the archive comes
# from the internet. Returns the folder.
def safe_extract(zip_path, base_folder):
    target = os.path.join(base_folder, os.path.splitext(os.path.basename(zip_path))[0])
    os.makedirs(target, exist_ok=True)
    root = os.path.realpath(target)
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        if len(infos) > ZIP_MAX_FILES or sum(info.file_size for info in infos) > ZIP_MAX_BYTES:
            raise ValueError("{} is too large to unpack".format(os.path.basename(zip_path)))
        for info in infos:
            name = info.filename
            if "`" in name:
                raise ValueError("{} holds a file name with a backtick, refused".format(os.path.basename(zip_path)))
            destination = os.path.realpath(os.path.join(root, name))
            if os.path.commonpath([root, destination]) != root:
                raise ValueError("{} holds a path that leaves its folder, refused".format(os.path.basename(zip_path)))
        archive.extractall(root)
    return target


# ------------------------------------------------------------
def list_files(folder, suffix):
    found = []
    for current, _, names in os.walk(folder):
        for name in names:
            if name.lower().endswith(suffix):
                found.append(os.path.join(current, name))
    return found


# ------------------------------------------------------------
class MaterialDownloadDialog(QtWidgets.QDialog):
    fileChosen = QtCore.Signal(str)

    # ----------------------------------------------------------------------
    def __init__(self, default_folder, settings=None, parent=None, extra_env=None):
        super().__init__(parent)
        self.setWindowTitle("Download MaterialX Materials")
        self.resize(560, 640)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self._settings = settings if settings is not None else self._make_settings()
        self._default_folder = default_folder
        self._extra_env = dict(extra_env or {})
        self._python = []
        self._process = None
        self._zips_before = set()
        self._mtlx_before = set()
        self._started = 0.0
        self._build_ui()
        self._load_settings()
        self.detect_python()

    # ------------------------------------------------------------
    @staticmethod
    def _make_settings():
        try:
            return QtCore.QSettings("BSM", "KarmaBuilder")
        except RuntimeError:
            return None

    # ------------------------------------------------------------
    def _build_ui(self):
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
        self.lbl_resolution = QtWidgets.QLabel("Resolution:")
        form.addRow(self.lbl_resolution, self.combo_resolution)
        self.combo_format = QtWidgets.QComboBox()
        self.combo_format.addItems(["PNG", "JPEG"])
        self.lbl_format = QtWidgets.QLabel("Image format:")
        form.addRow(self.lbl_format, self.combo_format)
        self.combo_model = QtWidgets.QComboBox()
        self.combo_model.addItems(SHADING_MODELS)
        self.lbl_model = QtWidgets.QLabel("Shading model:")
        form.addRow(self.lbl_model, self.combo_model)

        row_folder = QtWidgets.QHBoxLayout()
        self.line_folder = QtWidgets.QLineEdit(self._default_folder)
        btn_browse = QtWidgets.QPushButton("...")
        btn_browse.setMaximumWidth(40)
        btn_browse.clicked.connect(self.browse_folder)
        row_folder.addWidget(self.line_folder, 1)
        row_folder.addWidget(btn_browse)
        form.addRow("Download to:", row_folder)

        row_python = QtWidgets.QHBoxLayout()
        self.line_python = QtWidgets.QLineEdit()
        self.line_python.setToolTip("The Python that has materialxmaterials (pip install materialxmaterials). "
                                    "Houdini's own Python is not used.")
        btn_detect = QtWidgets.QPushButton("Detect")
        btn_detect.clicked.connect(self.detect_python)
        row_python.addWidget(self.line_python, 1)
        row_python.addWidget(btn_detect)
        form.addRow("Python:", row_python)
        layout.addLayout(form)

        row_state = QtWidgets.QHBoxLayout()
        self.lbl_python = QtWidgets.QLabel("")
        self.lbl_python.setTextFormat(QtCore.Qt.PlainText)
        self.lbl_python.setWordWrap(True)
        self.btn_install = QtWidgets.QPushButton("Install materialxmaterials")
        self.btn_install.setToolTip("Runs: python -m pip install materialxmaterials")
        self.btn_install.clicked.connect(self.install_package)
        row_state.addWidget(self.lbl_python, 1)
        row_state.addWidget(self.btn_install)
        layout.addLayout(row_state)

        row_run = QtWidgets.QHBoxLayout()
        self.btn_download = QtWidgets.QPushButton("Download")
        self.btn_download.setStyleSheet(_btn_style(_C["amber"]))
        self.btn_download.clicked.connect(self.start_download)
        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_process)
        self.btn_site = QtWidgets.QPushButton("Open Website")
        self.btn_site.setToolTip("Browse the source to find the name of a material.")
        self.btn_site.clicked.connect(self.open_site)
        row_run.addWidget(self.btn_download, 1)
        row_run.addWidget(self.btn_stop)
        row_run.addWidget(self.btn_site)
        layout.addLayout(row_run)

        self.txt_output = QtWidgets.QPlainTextEdit()
        self.txt_output.setReadOnly(True)
        self.txt_output.setMinimumHeight(120)
        layout.addWidget(self.txt_output, 1)

        layout.addWidget(QtWidgets.QLabel("Materials found in the folder (.mtlx):"))
        self.list_files = QtWidgets.QListWidget()
        self.list_files.setMinimumHeight(110)
        self.list_files.itemDoubleClicked.connect(lambda *_: self.use_selected())
        layout.addWidget(self.list_files, 1)

        row_use = QtWidgets.QHBoxLayout()
        self.btn_use = QtWidgets.QPushButton("Use in Catalog")
        self.btn_use.setToolTip("Show the selected file's materials in the Materials tab.")
        self.btn_use.clicked.connect(self.use_selected)
        btn_open = QtWidgets.QPushButton("Open Folder")
        btn_open.clicked.connect(self.open_folder)
        btn_refresh = QtWidgets.QPushButton("Refresh")
        btn_refresh.clicked.connect(self.refresh_files)
        row_use.addWidget(self.btn_use, 1)
        row_use.addWidget(btn_open)
        row_use.addWidget(btn_refresh)
        layout.addLayout(row_use)
        self._update_source_ui()

    # ------------------------------------------------------------
    def _update_source_ui(self, *_):
        source = self.combo_source.currentText()
        self.combo_resolution.clear()
        if source == SOURCE_AMBIENTCG:
            self.combo_resolution.addItems(["{}K".format(r) for r in AMBIENTCG_RESOLUTIONS])
            self.combo_resolution.setCurrentIndex(1)
            self.line_name.setPlaceholderText("WoodFloor038")
            self.lbl_name.setText("Material name:")
        elif source == SOURCE_POLYHAVEN:
            self.combo_resolution.addItems(list(POLYHAVEN_RESOLUTIONS))
            self.combo_resolution.setCurrentIndex(1)
            self.line_name.setPlaceholderText("polystyrene")
            self.lbl_name.setText("Asset id:")
        for widget in (self.lbl_name, self.line_name):
            widget.setVisible(source != SOURCE_PHYSBASED)
        for widget in (self.lbl_resolution, self.combo_resolution):
            widget.setVisible(source != SOURCE_PHYSBASED)
        for widget in (self.lbl_format, self.combo_format):
            widget.setVisible(source == SOURCE_AMBIENTCG)
        for widget in (self.lbl_model, self.combo_model):
            widget.setVisible(source == SOURCE_PHYSBASED)

    # ------------------------------------------------------------
    def _load_settings(self):
        if self._settings is None:
            return
        try:
            folder = self._settings.value("folder", "")
            python = self._settings.value("python", "")
            source = self._settings.value("source", "")
        except (RuntimeError, TypeError):
            return
        if folder:
            self.line_folder.setText(str(folder))
        if python:
            self.line_python.setText(str(python))
        index = self.combo_source.findText(str(source))
        if index >= 0:
            self.combo_source.setCurrentIndex(index)

    # ------------------------------------------------------------
    def _save_settings(self):
        if self._settings is None:
            return
        try:
            self._settings.setValue("folder", self.line_folder.text().strip())
            self._settings.setValue("python", self.line_python.text().strip())
            self._settings.setValue("source", self.combo_source.currentText())
        except RuntimeError:
            pass

    # ------------------------------------------------------------
    def _log(self, text):
        self.txt_output.moveCursor(QtGui.QTextCursor.End)
        self.txt_output.insertPlainText(text if text.endswith("\n") else text + "\n")
        self.txt_output.ensureCursorVisible()

    # ------------------------------------------------------------
    @_guarded_slot
    def detect_python(self):
        typed = split_command(self.line_python.text())
        candidates = [typed] if typed else find_python_candidates()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            command, version = first_working_python(candidates)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if command:
            self._python = command
            self.line_python.setText(" ".join(command))
            self.lbl_python.setText("materialxmaterials found (Python {}).".format(version))
            self.btn_install.setVisible(False)
            self.btn_download.setEnabled(True)
            return
        self._python = typed or (candidates[0] if candidates else [])
        if not candidates and not typed:
            self.lbl_python.setText("No Python found. Install Python 3 from python.org, then press Detect.")
            self.btn_install.setVisible(False)
        else:
            self.lbl_python.setText("materialxmaterials is not installed for this Python.")
            self.btn_install.setVisible(bool(self._python))
        self.btn_download.setEnabled(False)

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
    def _fields(self):
        resolution = self.combo_resolution.currentText()
        if self.combo_source.currentText() == SOURCE_AMBIENTCG:
            resolution = resolution.rstrip("Kk")
        return {"name": self.line_name.text(), "resolution": resolution,
                "fmt": self.combo_format.currentText(), "model": self.combo_model.currentText()}

    # ------------------------------------------------------------
    def _run(self, arguments, folder):
        if self._process is not None:
            return
        self._python = split_command(self.line_python.text()) or self._python
        if not self._python:
            self._log("No Python to run: press Detect.")
            return
        self._zips_before = set(list_files(folder, ".zip"))
        self._mtlx_before = set(list_files(folder, ".mtlx"))
        self._started = time.time()
        process = QtCore.QProcess(self)
        process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        process.setWorkingDirectory(folder)
        env = QtCore.QProcessEnvironment.systemEnvironment()
        for key, value in (("PYTHONUTF8", "1"), ("PYTHONIOENCODING", "utf-8"), ("PYTHONUNBUFFERED", "1")):
            env.insert(key, value)
        for key, value in self._extra_env.items():
            env.insert(key, value)
        process.setProcessEnvironment(env)
        process.readyReadStandardOutput.connect(self._read_output)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._failed)
        self._process = process
        program, args = self._python[0], list(self._python[1:]) + arguments
        self._log("> {} {}".format(program, " ".join(args)))
        self._busy(True)
        process.start(program, args)

    # ------------------------------------------------------------
    def _busy(self, running):
        self.btn_download.setEnabled(not running and bool(self._python))
        self.btn_install.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    # ------------------------------------------------------------
    @_guarded_slot
    def start_download(self):
        try:
            folder = self._folder()
            arguments = build_arguments(self.combo_source.currentText(), self._fields(), folder)
        except (ValueError, OSError) as exc:
            self._log("Not started: {}".format(exc))
            return
        self._save_settings()
        self._run(arguments, folder)

    # ------------------------------------------------------------
    @_guarded_slot
    def install_package(self):
        try:
            folder = self._folder()
        except (ValueError, OSError) as exc:
            self._log("Not started: {}".format(exc))
            return
        self._log("Installing materialxmaterials with pip. It is downloaded from PyPI, which is the usual way.")
        self._run(["-m", "pip", "install", "--user", "materialxmaterials"], folder)

    # ------------------------------------------------------------
    @_guarded_slot
    def stop_process(self):
        if self._process is not None:
            self._process.kill()
            self._log("Stopped.")

    # ------------------------------------------------------------
    def _read_output(self):
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            self._log(data.rstrip("\r\n"))

    # ------------------------------------------------------------
    @_guarded_slot
    def _finished(self, code, status):
        self._read_output()
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()
        self._busy(False)
        self._log("Finished (exit code {}).".format(code))
        if code == 0:
            self._unpack_new_zips()
        self.refresh_files()
        self.detect_python()

    # ------------------------------------------------------------
    @_guarded_slot
    def _failed(self, error):
        if self._process is not None and self._process.state() == QtCore.QProcess.NotRunning and error == QtCore.QProcess.FailedToStart:
            self._log("The program could not be started: {}".format(self._process.errorString()))
            process, self._process = self._process, None
            process.deleteLater()
            self._busy(False)

    # ------------------------------------------------------------
    def _unpack_new_zips(self):
        try:
            folder = self._folder()
        except (ValueError, OSError):
            return
        for path in sorted(set(list_files(folder, ".zip")) - self._zips_before):
            try:
                target = safe_extract(path, os.path.dirname(path))
                self._log("Unpacked {} to {}".format(os.path.basename(path), target))
            except (ValueError, OSError, zipfile.BadZipFile) as exc:
                self._log("[WARN] {}: {}".format(os.path.basename(path), exc))

    # ------------------------------------------------------------
    @_guarded_slot
    def refresh_files(self):
        self.list_files.clear()
        try:
            folder = self._folder()
        except (ValueError, OSError):
            return
        files = sorted(list_files(folder, ".mtlx"), key=os.path.getmtime, reverse=True)
        for path in files[:300]:
            item = QtWidgets.QListWidgetItem(os.path.relpath(path, folder).replace("\\", "/"))
            item.setData(QtCore.Qt.UserRole, path.replace("\\", "/"))
            item.setToolTip(path)
            self.list_files.addItem(item)
            if path not in self._mtlx_before and os.path.getmtime(path) >= self._started - 1:
                item.setSelected(True)
        if self.list_files.count() and not self.list_files.selectedItems():
            self.list_files.item(0).setSelected(True)

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
        self._save_settings()
        if self._process is not None:
            try:
                self._process.kill()
                self._process.waitForFinished(1500)
            except RuntimeError:
                pass
        super().closeEvent(event)
