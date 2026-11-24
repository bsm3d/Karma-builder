# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Log and About tabs of the Karma Builder dialog, with the controls of the debug log file.

# Houdini : 21 and 22 (PySide6 only, no hou calls)

import datetime
import os
from hutil.Qt import QtWidgets, QtCore, QtGui
from .config import SCRIPT_VERSION
from .logo import logo_pixmap
from .debuglog import _debug, _debug_session_header, _debug_state, debug_log_path
from .styles import _C
from .util import _tool_data_folder
from .widgets import wrap_tab

# ------------------------------------------------------------
class LogTab:

    def _build_about_tab(self, tabs):
        tab_about = QtWidgets.QWidget()
        layout_about = QtWidgets.QVBoxLayout(tab_about)
        layout_about.setAlignment(QtCore.Qt.AlignTop)
        layout_about.setSpacing(12)
        layout_about.setContentsMargins(16, 20, 16, 16)

        logo = logo_pixmap(110)
        if logo is not None:
            lbl_logo = QtWidgets.QLabel()
            lbl_logo.setPixmap(logo)
            lbl_logo.setAlignment(QtCore.Qt.AlignCenter)
            layout_about.addWidget(lbl_logo)

        lbl_title = QtWidgets.QLabel("Karma Builder")
        title_font = lbl_title.font()
        title_font.setPointSize(16)
        title_font.setBold(True)
        lbl_title.setFont(title_font)
        lbl_title.setAlignment(QtCore.Qt.AlignCenter)
        lbl_title.setWordWrap(True)
        layout_about.addWidget(lbl_title)

        lbl_version = QtWidgets.QLabel("Version : {}".format(SCRIPT_VERSION))
        lbl_version.setAlignment(QtCore.Qt.AlignCenter)
        layout_about.addWidget(lbl_version)

        lbl_sub = QtWidgets.QLabel("Procedural Environment & Render Setup\nfor SideFX Houdini")
        lbl_sub.setAlignment(QtCore.Qt.AlignCenter)
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet("color: #aaa;")
        layout_about.addWidget(lbl_sub)

        sep1 = QtWidgets.QFrame()
        sep1.setFrameShape(QtWidgets.QFrame.HLine)
        sep1.setFrameShadow(QtWidgets.QFrame.Sunken)
        layout_about.addWidget(sep1)

        lbl_cred = QtWidgets.QLabel(
            "<b>Programming & Design</b><br>"
            "Beno\u00eet Saint-Moulin<br>"
            '<a href="https://www.bsm3d.com" style="color: {};">www.bsm3d.com</a>'.format(_C["link"])
        )
        lbl_cred.setAlignment(QtCore.Qt.AlignCenter)
        lbl_cred.setOpenExternalLinks(True)
        lbl_cred.setStyleSheet("line-height: 1.6;")
        layout_about.addWidget(lbl_cred)

        lbl_help = QtWidgets.QLabel('<a href="help" style="color: {};">Help (user guide)</a>'.format(_C["link"]))
        lbl_help.setAlignment(QtCore.Qt.AlignCenter)
        lbl_help.setToolTip("Open the user guide (docs/index.html next to the tool, the website when there is none).")
        lbl_help.linkActivated.connect(self.on_open_help)
        layout_about.addWidget(lbl_help)

        btn_folder = QtWidgets.QPushButton("Open Karma Folder")
        btn_folder.setToolTip("Show the folder where Karma Builder keeps its files (datas, materials, cloud pictures, debug log).")
        btn_folder.clicked.connect(self.on_open_karma_folder)
        layout_about.addWidget(btn_folder)

        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.HLine)
        sep2.setFrameShadow(QtWidgets.QFrame.Sunken)
        layout_about.addWidget(sep2)

        lbl_sch = QtWidgets.QLabel("PolyForm Noncommercial License 1.0.0")
        lbl_sch.setAlignment(QtCore.Qt.AlignCenter)
        lbl_sch.setWordWrap(True)
        lbl_sch.setStyleSheet("color: #aaa; font-size: 12px;")
        layout_about.addWidget(lbl_sch)

        layout_about.addStretch(1)

        tabs.addTab(wrap_tab(tab_about), "About")

    # ------------------------------------------------------------
    # The HDA does not carry the guide (screenshots): it is read from the folder of the tool when it is there, else the site.
    def on_open_help(self, *_):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        guide = os.path.join(here, "docs", "index.html")
        url = QtCore.QUrl.fromLocalFile(guide) if os.path.isfile(guide) else QtCore.QUrl("https://www.bsm3d.com")
        try:
            if not QtGui.QDesktopServices.openUrl(url):
                self.log_message("[WARN] The help could not be opened: {}".format(url.toString()))
        except Exception as exc:   # a link click must never raise into Qt
            self.log_message("[WARN] The help could not be opened: {}".format(exc))

    # ------------------------------------------------------------
    def on_open_karma_folder(self, *_):
        folder = _tool_data_folder()
        if not folder:
            self.log_message("[WARN] No Houdini preferences folder found, there is no Karma folder to open.")
            return
        try:
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder)):
                self.log_message("[WARN] The folder could not be opened: {}".format(folder))
        except Exception as exc:   # a click must never raise into Qt
            self.log_message("[WARN] The folder could not be opened: {}".format(exc))

    def _build_log_tab(self, tabs):
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
        self.lbl_debug_path.setTextFormat(QtCore.Qt.PlainText)
        self.lbl_debug_path.setWordWrap(True)
        self.lbl_debug_path.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.lbl_debug_path.setStyleSheet("color: {};".format(_C["text_muted"]))
        layout_logs.addWidget(self.lbl_debug_path)

        tabs.addTab(wrap_tab(tab_logs), "Log")

    #----------------------------------------------------------------
    def log_message(self, message):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        # plain text on purpose: append() would parse HTML, and the message may carry text from outside
        # (catalog labels, node names), enough to forge lines or draw images in the Log
        self.txt_log.moveCursor(QtGui.QTextCursor.End)
        self.txt_log.insertPlainText(f"[{now}] {message}\n")
        self.txt_log.ensureCursorVisible()
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
