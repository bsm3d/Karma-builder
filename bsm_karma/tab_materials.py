# tab_materials.py - BSM Karma Builder - Materials tab: catalog, geometry source and assignments
# Version : 2026.10.15.1 | Revision : 15-10-2026 | Auteur : BSM

import hou
import os
import tempfile
from hutil.Qt import QtWidgets, QtCore
from .util import _expand_plain_path
from .catalog import _amd_library_reachable, _bound_material_name, _list_materials_in_file, _material_catalog_file, _parse_catalog_drop, _stage_target_prims
from .config import _PRIM_PATH_RE, MATERIAL_EDIT_PATH_PARM, STAGE_TARGET_LIMIT
from .debuglog import _debug, _guarded_slot
from .linker import (_get_or_create_material_edit, _get_or_create_material_linker, _insert_material_edit_in_chain, _insert_material_linker_in_chain,
                     _linker_add_reference, _linker_assign, _linker_unassign, _material_edit_load, _material_edit_node, _material_linker_node)
from .matviews import MaterialBrowser
from .basicmaterials import data_folder
from .localmaterials import is_local_payload, local_assets, local_payload
from .mxdownload import MaterialDownloadDialog
from .nodeutil import _is_tool_node_candidate, _paused_cooking
from .styles import _C
from .viewport_drop import ViewportDropFilter, viewer_selection
from .widgets import MaterialTargetTree, PopupRefreshComboBox, wrap_tab

# ------------------------------------------------------------
class MaterialsTab:

    def _build_materials_tab(self, tabs):
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
        self.mat_browser = None
        if self.mat_gallery is not None:
            self.mat_gallery.setMinimumHeight(150)
            self.mat_browser = MaterialBrowser(self.mat_gallery)
            self.mat_browser.contextRequested.connect(self._on_catalog_context_menu)
            lay_catalog.addWidget(self.mat_browser, 1)
        else:
            lbl_no_gallery = QtWidgets.QLabel(
                "The material catalog is not available in this Houdini build ({}).\n"
                "Use 'Assign File...' below instead.".format(self._gallery_problem or "unknown reason"))
            lbl_no_gallery.setAlignment(QtCore.Qt.AlignCenter)
            lbl_no_gallery.setTextFormat(QtCore.Qt.PlainText)
            lbl_no_gallery.setWordWrap(True)
            lay_catalog.addWidget(lbl_no_gallery)

        self.lbl_mat_status = QtWidgets.QLabel(
            "Showing Houdini's current material catalog. Pick another source and press Connect to switch.")
        self.lbl_mat_status.setTextFormat(QtCore.Qt.PlainText)
        self.lbl_mat_status.setWordWrap(True)
        self.lbl_mat_status.setStyleSheet("color: {};".format(_C["text_muted"]))
        self.btn_mat_download = QtWidgets.QPushButton("Download...")
        self.btn_mat_download.setToolTip("Download MaterialX materials from ambientCG or Poly Haven, then show them in this catalog.")
        self.btn_mat_download.clicked.connect(self.on_open_material_downloader)
        row_status = QtWidgets.QHBoxLayout()
        row_status.addWidget(self.lbl_mat_status, 1)
        row_status.addWidget(self.btn_mat_download, 0, QtCore.Qt.AlignTop)
        lay_catalog.addLayout(row_status)
        layout_materials.addWidget(grp_catalog, 3)

        grp_targets = QtWidgets.QGroupBox("Assign to Geometry")
        lay_targets = QtWidgets.QVBoxLayout(grp_targets)
        lbl_drag_hint = QtWidgets.QLabel("Drag a material from the catalog onto a prim of the list, or onto the viewport.")
        lbl_drag_hint.setWordWrap(True)
        lbl_drag_hint.setStyleSheet("color: {};".format(_C["text_muted"]))
        lay_targets.addWidget(lbl_drag_hint)

        row_geo = QtWidgets.QHBoxLayout()
        self.combo_geo_source = PopupRefreshComboBox()
        self.combo_geo_source.popupAboutToShow.connect(self._fill_geo_source_combo)
        self.combo_geo_source.setToolTip(
            "LOP node merged with the environment so materials can be bound to its prims. "
            "Applied on the next Build.")
        self.combo_geo_source.currentIndexChanged.connect(self.on_geo_source_changed)
        self.btn_refresh_geo = QtWidgets.QPushButton("Refresh")
        self.btn_refresh_geo.clicked.connect(self.refresh_geo_sources)
        row_geo.addWidget(QtWidgets.QLabel("Geometry:"))
        row_geo.addWidget(self.combo_geo_source, 1)
        row_geo.addWidget(self.btn_refresh_geo)
        lay_targets.addLayout(row_geo)

        self.tree_mat_targets = MaterialTargetTree()
        self.tree_mat_targets.setMinimumHeight(120)
        self.tree_mat_targets.assetDropped.connect(self.on_material_asset_dropped)
        lay_targets.addWidget(self.tree_mat_targets, 1)

        row_assign = QtWidgets.QHBoxLayout()
        self.btn_assign_selection = QtWidgets.QPushButton("Assign Material to Selection")
        self.btn_assign_selection.setToolTip(
            "Bind the material selected in the catalog to the selected prims: those of the list below, "
            "or the selection of the viewport when the list has none.")
        self.btn_assign_selection.clicked.connect(self.on_assign_material_to_selection)
        self.btn_pick_viewport = QtWidgets.QPushButton("From Viewport")
        self.btn_pick_viewport.setToolTip("Select in the list the prims selected in the Solaris viewport.")
        self.btn_pick_viewport.clicked.connect(self.on_pick_viewport_selection)
        row_assign.addWidget(self.btn_assign_selection, 1)
        row_assign.addWidget(self.btn_pick_viewport)
        lay_targets.addLayout(row_assign)

        self.chk_viewport_drop = QtWidgets.QCheckBox("Accept drops on the Solaris viewport")
        self.chk_viewport_drop.setToolTip(
            "Drag a material from the catalog onto a prim of the viewport. Armed only while a drag from the "
            "catalog may be running. Off with BSM_KARMA_VIEWPORT_DROP=0.")
        self.chk_viewport_drop.setChecked(os.environ.get("BSM_KARMA_VIEWPORT_DROP", "1") != "0")
        lay_targets.addWidget(self.chk_viewport_drop)

        row_mat_buttons = QtWidgets.QHBoxLayout()
        self.btn_assign_file = QtWidgets.QPushButton("Assign File...")
        self.btn_assign_file.setToolTip("Assign MaterialX / USD file: pick a .mtlx or USD file and bind its material to the selected prims.")
        self.btn_assign_file.clicked.connect(self.on_assign_material_file)
        self.btn_unassign = QtWidgets.QPushButton("Remove")
        self.btn_unassign.setToolTip("Remove the material assignment of the selected prims.")
        self.btn_unassign.clicked.connect(self.on_unassign_material)
        self.btn_open_linker = QtWidgets.QPushButton("Linker")
        self.btn_open_linker.setToolTip("Open Material Linker: select the node to edit the rules in Houdini's own panel.")
        self.btn_open_linker.clicked.connect(self.on_open_material_linker)
        row_mat_buttons.addWidget(self.btn_assign_file)
        row_mat_buttons.addWidget(self.btn_unassign)
        row_mat_buttons.addWidget(self.btn_open_linker)
        lay_targets.addLayout(row_mat_buttons)
        layout_materials.addWidget(grp_targets, 2)

        self._viewport_drop = ViewportDropFilter(self, self._get_active_scene_viewer, hou.qt.mainWindow, self)
        self._viewport_drop.dropped.connect(self.on_viewport_material_drop)
        if self.mat_browser is not None:
            self.mat_browser.dragStarted.connect(self._arm_viewport_drop)

        tabs.addTab(wrap_tab(tab_materials), "Materials")

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

    def _default_material_download_dir(self):
        pref_dir = hou.text.expandString("$HOUDINI_USER_PREF_DIR")
        if not pref_dir or pref_dir.startswith("$"):
            pref_dir = tempfile.gettempdir()
        return os.path.join(pref_dir, "bsm_karma", "materials").replace("\\", "/")

    # --------------------------------------------------
    def _create_material_gallery(self):
        # HACK: hou.qt._createAssetGallery is private. It is what the Material Linker panel calls,
        # there is no public way to get this widget. Guard rail: any failure, or an object that is not a widget,
        # leaves the Materials tab without catalog (the reason is shown there) and "Assign File..." still works.
        # BSM_KARMA_GALLERY=0 skips the private call altogether. When it fails, the debug log lists what hou.qt
        # offers instead, so a replacement can be found for that Houdini version.
        self._gallery_problem = ""
        if os.environ.get("BSM_KARMA_GALLERY", "1") == "0":
            self._gallery_problem = "switched off by BSM_KARMA_GALLERY=0"
            return None
        try:
            gallery = hou.qt._createAssetGallery("material")
        except (AttributeError, hou.Error, TypeError, RuntimeError) as exc:
            self._gallery_problem = "{}: {}".format(type(exc).__name__, exc)
            self._pending_logs.append("Material catalog widget unavailable: {}".format(self._gallery_problem))
            _debug("hou.qt names about galleries: {}".format(
                [name for name in dir(hou.qt) if "allery" in name or "sset" in name]))
            return None
        if not isinstance(gallery, QtWidgets.QWidget):
            self._gallery_problem = "Houdini returned a {} instead of a widget".format(type(gallery).__name__)
            self._pending_logs.append("Material catalog widget unavailable: {}".format(self._gallery_problem))
            return None
        return gallery

    #------------------------------------------------------------------------------------------
    def update_material_source_ui(self):
        self.w_mat_download.setVisible(self.combo_mat_source.currentText() == self.MATERIAL_SOURCES[0])
        # without the catalog widget the source controls would do nothing
        has_gallery = self.mat_gallery is not None
        self.btn_mat_connect.setEnabled(has_gallery)
        self.combo_mat_source.setEnabled(has_gallery)
        if not has_gallery:
            self.w_mat_download.setVisible(False)

    @_guarded_slot
    def browse_material_download_dir(self):
        path = hou.ui.selectFile(start_directory=self.line_mat_download.text(), title="Material Download Folder",
                                 file_type=hou.fileType.Directory, chooser_mode=hou.fileChooserMode.Read)
        if path:
            try:
                self.line_mat_download.setText(_expand_plain_path(path).rstrip("/\\"))
            except ValueError as exc:
                self._set_material_status("Folder not changed: {}".format(exc))

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
                data_source, hint = self._material_file_source(_expand_plain_path(path))
                if data_source is None:
                    return
            hou.ui.setSharedAssetGalleryDataSource(data_source, "material")
            self._material_source_changed = True
            self._amd_folder = folder if source == self.MATERIAL_SOURCES[0] else None
            self._set_material_status(hint)
            if self.mat_browser is not None:
                self.mat_browser.refresh()
            self.log_message("[OK] Material catalog connected: {}".format(source))
        except (hou.Error, OSError, ValueError, AttributeError) as exc:
            self._set_material_status("Could not connect: {}".format(exc))
            self.log_message("[WARN] Material catalog connection failed ({}): {}".format(source, exc))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    # ------------------------------------------------------------
    # The catalog source of a .mtlx or USD file, and the line that says what it shows; (None, "") when Houdini cannot
    # open it.
    def _material_file_source(self, path):
        source_file = _material_catalog_file(path)
        if source_file != path:
            self._hdri_temp_files.append(source_file)  # removed when the dialog is released
        data_source = hou.AssetGalleryDataSource(source_file, "%type:Material")
        if not data_source.isValid():
            self._set_material_status("Houdini could not open {} as a material source.".format(path))
            return None, ""
        return data_source, "Materials found in {}".format(path)

    # ------------------------------------------------------------
    # A file chosen in the download window: show it in the catalog like the "USD / MaterialX File..." source.
    @_guarded_slot
    def _show_material_file(self, path):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            data_source, hint = self._material_file_source(_expand_plain_path(path))
            if data_source is None:
                return
            hou.ui.setSharedAssetGalleryDataSource(data_source, "material")
            self._material_source_changed = True
            self._amd_folder = None
            self.combo_mat_source.setCurrentIndex(2)
            self._set_material_status(hint)
            if self.mat_browser is not None:
                self.mat_browser.refresh()
            self.log_message("[OK] Material catalog connected: {}".format(path))
        except (hou.Error, OSError, ValueError, AttributeError) as exc:
            self._set_material_status("Could not open the file: {}".format(exc))
            self.log_message("[WARN] Downloaded material not shown ({}): {}".format(path, exc))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    # ------------------------------------------------------------
    @_guarded_slot
    def on_open_material_downloader(self):
        dialog = self._mx_dialog
        if dialog is not None:
            try:
                dialog.raise_()
                dialog.activateWindow()
                return
            except RuntimeError:
                self._mx_dialog = None   # closed meanwhile
        dialog = MaterialDownloadDialog(self._default_download_folder(), parent=self)
        dialog.fileChosen.connect(self._show_material_file)
        dialog.dragStarted.connect(self._arm_viewport_drop)
        dialog.assignRequested.connect(self.on_downloaded_material_assign)
        dialog.destroyed.connect(lambda *_: setattr(self, "_mx_dialog", None))
        self._mx_dialog = dialog
        dialog.show()

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
    @_guarded_slot
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
    @_guarded_slot
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
        self._assign_material_pairs([(asset, prim_paths) for asset in assets])

    # ------------------------------------------------------------
    # pairs: [(material descriptor, prim paths)], all done in one step, so one prim list refresh and one undo.
    def _assign_material_pairs(self, pairs):
        pairs = [(asset, [p for p in prims if p]) for asset, prims in pairs]
        pairs = [(asset, prims) for asset, prims in pairs if asset and prims]
        if not pairs:
            return
        with hou.undos.group("BSM Karma - Assign Material"):
            linker = self._ensure_material_linker()
            if linker is None:
                return
            assigned = 0
            for asset, prim_paths in pairs:
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
                assigned += count
                if len(pairs) <= 5:
                    self.log_message("[OK] {} -> {} prim(s): {}".format(material_path, count, ", ".join(prim_paths[:3])
                                                                        + (" ..." if len(prim_paths) > 3 else "")))
            if len(pairs) > 5:
                self.log_message("[OK] {} materials assigned, one to each of {} prims.".format(len(pairs), assigned))
        self.refresh_material_targets()

    # ------------------------------------------------------------------------
    @_guarded_slot
    def on_material_asset_dropped(self, payload, paths_text):
        self._assign_payload(payload, [p for p in paths_text.splitlines() if p])

    # ------------------------------------------------------------
    def _assets_from_payload(self, payload):
        if is_local_payload(payload):
            return self._local_assets_from_payload(payload)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            # TODO: an AMD package downloads here on the UI thread (Houdini's own code), the window freezes while it runs
            assets, failures = _parse_catalog_drop(payload, amd_folder=self._amd_folder)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, hou.Error) as exc:
            self.log_message("[WARN] Unreadable material drop: {}".format(exc))
            return []
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        for failure in failures:
            self.log_message("[WARN] Material not available: {}".format(failure))
        if not assets:
            self.log_message("[INFO] No material found: pick a material (not a folder) in the catalog.")
        return assets

    # ------------------------------------------------------------
    # Files dragged from the download window. Only files of a download folder are taken: the drop could come from anywhere.
    def _local_assets_from_payload(self, payload):
        roots = [self._default_download_folder()]
        for sub in ("materials_basic", "my_materials", "materials_random"):
            try:
                roots.append(data_folder(sub))
            except OSError:
                pass
        dialog = self._mx_dialog
        if dialog is not None:
            try:
                roots.append(dialog.download_folder())
            except RuntimeError:
                self._mx_dialog = None   # closed meanwhile
        assets, failures = local_assets(payload, roots, lister=_list_materials_in_file)
        for failure in failures:
            self.log_message("[WARN] Material not available: {}".format(failure))
        return assets

    # ------------------------------------------------------------
    def _default_download_folder(self):
        pref = hou.text.expandString("$HOUDINI_USER_PREF_DIR")
        base = pref if pref and not pref.startswith("$") else os.path.dirname(self._default_material_download_dir())
        return os.path.join(base, "bsm_karma", "mtlx").replace("\\", "/")

    # ------------------------------------------------------------
    # A material of the download window, bound to the prims selected in the list or in the viewport.
    @_guarded_slot
    def on_downloaded_material_assign(self, path):
        paths, origin = self._assignment_targets()
        if not paths:
            self.log_message("[INFO] Select prims in the Materials tab list, or in the Solaris viewport, then assign the material.")
            return
        self.log_message("[INFO] Assigning {} to {} prim(s) of {}.".format(os.path.basename(path), len(paths), origin))
        self._assign_payload(local_payload([path]), paths)

    # ------------------------------------------------------------
    def _assign_payload(self, payload, prim_paths):
        if not prim_paths:
            self.log_message("[INFO] No prim to assign to.")
            return
        assets = self._assets_from_payload(payload)
        if assets:
            self._assign_material_assets(assets, prim_paths)

    # ------------------------------------------------------------
    # Prim paths come from Houdini or from the list, and end up in a rule text: plain USD paths only.
    def _plain_prim_paths(self, paths):
        good = [p for p in paths if _PRIM_PATH_RE.match(p)]
        if len(good) != len(paths):
            self.log_message("[WARN] {} prim path(s) ignored: not a plain USD path.".format(len(paths) - len(good)))
        return good

    # ------------------------------------------------------------
    # The prims chosen in the list win, the viewport selection is the fallback. Returns (paths, where they come from).
    def _assignment_targets(self):
        paths = self.tree_mat_targets.selected_paths()
        if paths:
            return self._plain_prim_paths(paths), "the prim list"
        viewer = self._get_active_scene_viewer()
        if viewer is not None:
            paths = viewer_selection(viewer)
            if paths:
                return self._plain_prim_paths(paths), "the viewport"
        return [], ""

    # ------------------------------------------------------------
    @_guarded_slot
    def on_assign_material_to_selection(self):
        payload = self.mat_browser.current_payload() if self.mat_browser is not None else ""
        if not payload:
            self.log_message("[INFO] Select a material in the catalog first (a click on it, not a folder).")
            return
        paths, origin = self._assignment_targets()
        if not paths:
            self.log_message("[INFO] Select prims in the list, or in the viewport, first.")
            return
        self.log_message("[INFO] Assigning to {} prim(s) of {}.".format(len(paths), origin))
        self._assign_payload(payload, paths)

    # ------------------------------------------------------------
    @_guarded_slot
    def on_pick_viewport_selection(self):
        viewer = self._get_active_scene_viewer()
        paths = viewer_selection(viewer) if viewer is not None else []
        if not paths:
            self.log_message("[INFO] Nothing selected in the Solaris viewport (or this Houdini cannot report it).")
            return
        found = self.tree_mat_targets.select_paths(paths)
        self.log_message("[OK] {} of {} viewport prim(s) selected in the list.".format(found, len(paths)))

    # ------------------------------------------------------------
    def _arm_viewport_drop(self):
        if self.chk_viewport_drop.isChecked():
            self._viewport_drop.arm()

    # ------------------------------------------------------------
    @_guarded_slot
    def on_viewport_material_drop(self, payload, prim_path):
        if not prim_path:
            self.log_message("[INFO] No prim under the cursor: drop the material on an object of the viewport.")
            return
        viewer = self._get_active_scene_viewer()
        selected = viewer_selection(viewer) if viewer is not None else []
        # like the list: dropping on a selected prim takes the whole selection
        paths = selected if prim_path in selected else [prim_path]
        self.log_message("[INFO] Dropped on {} in the viewport.".format(prim_path))
        self._assign_payload(payload, self._plain_prim_paths(paths))

    # ------------------------------------------------------------
    @_guarded_slot
    def _on_catalog_context_menu(self, global_pos):
        menu = QtWidgets.QMenu(self)
        menu.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        act_assign = menu.addAction("Assign to Selection")
        menu.addSeparator()
        act_edit = menu.addAction("Edit Material (Material Linker)")
        act_network = menu.addAction("Open MaterialX Network (Edit Material node)")
        run = getattr(menu, "exec", None) or menu.exec_
        chosen = run(global_pos)
        if chosen is act_assign:
            self.on_assign_material_to_selection()
        elif chosen is act_edit:
            self._edit_catalog_material(network=False)
        elif chosen is act_network:
            self._edit_catalog_material(network=True)

    # ------------------------------------------------------------
    # Reference the selected material in the Material Linker (not assigned to anything) and open it for editing:
    # in the linker's own panel, or as a node network through an Edit Material LOP placed after the linker.
    def _edit_catalog_material(self, network):
        payload = self.mat_browser.current_payload() if self.mat_browser is not None else ""
        if not payload:
            self.log_message("[INFO] Select a material in the catalog first.")
            return
        assets = self._assets_from_payload(payload)
        if not assets:
            return
        if len(assets) > 1:
            self.log_message("[INFO] {} materials selected, editing the first one.".format(len(assets)))
        asset = assets[0]
        if network and not self._confirm_replace_edited_material(asset["label"]):
            return
        problems = []
        with hou.undos.group("BSM Karma - Edit Material"):
            with _paused_cooking(self.log_message):
                linker = self._ensure_material_linker()
                if linker is None:
                    return
                try:
                    material_path = _linker_add_reference(linker, asset["file_path"], asset["prim_path"], asset["label"])
                except ValueError as exc:
                    self.log_message("[WARN] Material not opened: {}".format(exc))
                    return
                node = linker
                if network:
                    try:
                        node = _get_or_create_material_edit(hou.node("/stage"))
                        _insert_material_edit_in_chain(linker, node)
                    except hou.Error as exc:
                        self.log_message("[WARN] Edit Material node unavailable ({}), opening the Material Linker instead.".format(exc))
                        node = linker
            # the Load button reads the stage: cooking is back on for it
            if network and node is not linker:
                try:
                    problems = _material_edit_load(node, material_path)
                except hou.Error as exc:
                    problems = ["Load failed: {}".format(exc)]
        for problem in problems:
            self.log_message("[WARN] {}".format(problem))
        self.log_message("[OK] {} ready to edit in {}.".format(material_path, node.path()))
        self._focus_node(node, dive=network and not problems)
        self.refresh_material_targets()

    # ------------------------------------------------------------
    # The Edit Material node holds one material at a time: loading another one replaces the network being edited.
    def _confirm_replace_edited_material(self, label):
        edit = _material_edit_node(hou.node("/stage"))
        if edit is None or not edit.children():
            return True
        current = edit.parm(MATERIAL_EDIT_PATH_PARM)
        current = current.evalAsString() if current is not None else ""
        if not current or current.rsplit("/", 1)[-1] == label:
            return True
        reply = QtWidgets.QMessageBox.question(
            self, "Edit Material",
            "{} is editing {}.\n\nOpening {} replaces it, and the edits made in that network are lost "
            "(Ctrl+Z brings them back).\n\nContinue?".format(edit.name(), current, label),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel, QtWidgets.QMessageBox.Cancel)
        return reply == QtWidgets.QMessageBox.Yes

    # ------------------------------------------------------------
    # Select the node, make it current (the parameter pane follows) and show it in a network editor.
    def _focus_node(self, node, dive=False):
        node.setSelected(True, clear_all_selected=True)
        try:
            node.setCurrent(True, clear_all_selected=True)
        except hou.Error:
            pass
        try:
            editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            if editor is not None:
                editor.setPwd(node if dive and node.children() else node.parent())
                editor.homeToSelection()
        except (hou.Error, AttributeError) as exc:
            _debug("network editor not moved: {}".format(exc))

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
        try:
            path = _expand_plain_path(path)
            materials = _list_materials_in_file(path)
        except Exception as exc:   # pxr raises Tf.ErrorException, which has no narrower base here
            self.log_message("[WARN] Could not read the material file: {}".format(exc))
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
        self._focus_node(linker)

    MATERIAL_SOURCES = ["AMD MaterialX Library", "Houdini Default Catalog", "USD / MaterialX File..."]

    NO_GEO_SOURCE_LABEL = "(none)"
