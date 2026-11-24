# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Debug log file for Karma Builder and the guard around the button handlers that writes any error to that log.

# Houdini : 21 and 22

import datetime
import functools
import hou
import os
import platform
import sys
import traceback
from hutil.Qt import QtCore
from .buildinfo import build_summary
from .config import SCRIPT_VERSION
from .util import _private_temp_dir

# Everything the tool does goes to a text file: log messages, build configuration, missing parameters, node graph after a build, tracebacks.
# Folder: the bsm_karma package folder; for the HDA or a read-only folder, the user preferences folder (bsm_karma/), else the temp folder.
# BSM_KARMA_DEBUG=0 in the environment starts with the log off.

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
    except (hou.Error, AttributeError):
        pass
    # last resort: a private folder of this session (a predictable name in the shared temp could be a planted link)
    try:
        folders.append(_private_temp_dir())
    except OSError:
        pass
    return folders

# ------------------------------------------------------------
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
    except (hou.Error, AttributeError):
        return "<node gone>"

# ------------------------------------------------------------
def _debug_session_header():
    try:
        houdini = "{} ({})".format(hou.applicationVersionString(), hou.applicationName())
    except (hou.Error, AttributeError):
        houdini = "unknown"
    try:
        binding = QtCore.__name__.split(".")[0]
        qt_version = QtCore.qVersion()
    except AttributeError:
        binding, qt_version = "unknown", "unknown"
    _debug("=" * 72, "SESSION")
    _debug("Karma Builder {} | Houdini {}".format(SCRIPT_VERSION, houdini), "SESSION")
    _debug("Python {} | {} (Qt {}) | {}".format(
        sys.version.split()[0], binding, qt_version, platform.platform()), "SESSION")
    _debug("script: {}".format(globals().get("__file__") or "<embedded>"), "SESSION")
    _debug(build_summary(SCRIPT_VERSION), "SESSION")
    try:
        _debug("hip file: {}".format(hou.hipFile.path()), "SESSION")
    except (hou.Error, AttributeError):
        _debug("hip file: unknown", "SESSION")

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
            except (RuntimeError, AttributeError):
                pass  # the window is deleted, or not built far enough to have its log
            return None
    return wrapper
