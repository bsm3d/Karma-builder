# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Karma viewport, renderer and camera lock helpers for the Solaris viewport.

# Houdini : 21 and 22

import re
import hou
from .config import CAMERA_CREATE_LABEL, GENERATED_CAMERA_NAME, USD_CAMERA_PREFIX, _PRIM_PATH_RE
from .debuglog import _guarded_slot
from .environment import _camera_prim_path

# ------------------------------------------------------------
class ViewportMixin:

    # ----------------------------------------------------------------------
    def _call_method_if_available(self, obj, method_name, *args):
        method = getattr(obj, method_name, None)
        if callable(method):
            try:
                method(*args)
                return True
            except (hou.Error, TypeError, AttributeError):
                return False
        return False

    # ----------------------------------------
    def _set_karma_viewport_minimal_ui(self, scene_viewer, viewport):
        scene_toggles = [
            ("showOperationBar", True),
            ("showSelectionBar", False),
            ("showDisplayOptionsBar", False),
            ("showColorCorrectionBar", False),
            ("showMemoryBar", False),
            ("setIncludeColorCorrectionBar", False),
            ("setIncludeMemoryBar", False),
            ("setGroupListVisible", False),
            ("setShowNetworkControls", False),
            ("showNetworkControls", False),
            ("showRenderStats", False),
            ("showRenderTime", False),
        ]
        for name, value in scene_toggles:
            self._call_method_if_available(scene_viewer, name, value)

        self._call_method_if_available(scene_viewer, "enterViewState")

        try:
            scene_viewer.setViewportLayout(hou.geometryViewportLayout.Single)
        except (hou.Error, AttributeError):
            pass

        pane = None
        try:
            pane = scene_viewer.pane()
        except (hou.Error, AttributeError):
            pane = None

        if pane is not None:
            self._call_method_if_available(pane, "setShowPaneTabs", False)
            self._call_method_if_available(pane, "showPaneTabs", False)
            self._call_method_if_available(pane, "showPaneTabsStow", False)
            self._call_method_if_available(pane, "setIsMaximized", True)
            self._call_method_if_available(pane, "setIsSplitMaximized", True)

        floating_panel = None
        try:
            floating_panel = scene_viewer.floatingPanel()
        except (hou.Error, AttributeError):
            floating_panel = None

        if floating_panel is not None:
            self._call_method_if_available(floating_panel, "setContainsShelf", False)
            self._call_method_if_available(floating_panel, "setContainsStatusBar", False)
            self._call_method_if_available(floating_panel, "setContainsMenuBar", False)
            self._call_method_if_available(floating_panel, "setContainsPlaybar", False)

        if viewport is not None:
            settings = None
            try:
                settings = viewport.settings()
            except (hou.Error, AttributeError):
                settings = None

            if settings is not None:
                view_toggles_off = [
                    "setShowGrid",
                    "setShowCompass",
                    "setShowOriginGnomon",
                    "setShowViewName",
                    "setShowCameraName",
                    "setShowFPS",
                    "setShowMemory",
                    "setShowTime",
                    "setShowViewerHandle",
                ]
                for name in view_toggles_off:
                    self._call_method_if_available(settings, name, False)

    # --------------------------------------------------------
    def _open_karma_render_options_panel(self, desktop):
        target_node = hou.node("/stage/render_to_disk") or hou.node("/stage/karma_settings")
        if desktop is None or target_node is None:
            return

        parm_tab = self._parm_pane_tab
        if parm_tab is not None:
            try:
                parm_tab.floatingPanel()
            except hou.Error:
                parm_tab = None
        if parm_tab is None:
            parm_tab = desktop.createFloatingPaneTab(hou.paneTabType.Parm)
            if parm_tab is None:
                return
            self._parm_pane_tab = parm_tab

        self._call_method_if_available(parm_tab, "setCurrentNode", target_node)
        self._call_method_if_available(parm_tab, "setNode", target_node)
        self._call_method_if_available(parm_tab, "setPin", True)

    # --------------------------------------------------------------------------------
    def _set_viewport_renderer(self, scene_viewer, viewport, engine):
        renderer_candidates = ["Karma XPU", "Karma"] if engine == "xpu" else ["Karma CPU", "Karma"]

        renderer_set = False
        for renderer_name in renderer_candidates:
            for obj in (scene_viewer, viewport):
                if obj is None:
                    continue
                for method_name in ("setHydraRenderer", "setCurrentHydraRenderer", "setRenderer"):
                    method = getattr(obj, method_name, None)
                    if callable(method):
                        try:
                            method(renderer_name)
                            renderer_set = True
                            break
                        except (hou.Error, TypeError):
                            pass
                if renderer_set:
                    break
            if renderer_set:
                break

        # the viewport name goes into a command line: plain names only
        if not renderer_set and viewport is not None and re.fullmatch(r"[A-Za-z0-9_.]+", str(viewport.name())):
            for renderer_name in renderer_candidates:
                try:
                    hou.hscript('viewrenderer -V "{}" "{}"'.format(viewport.name(), renderer_name))
                    renderer_set = True
                    break
                except hou.Error:
                    pass

        return renderer_set

    # ------------------------------------------------------------------------
    def _is_stage_viewer(self, viewer):
        try:
            return viewer.pwd().path() == "/stage"
        except hou.Error:
            return False

    # ------------------------------------------------------------
    def _get_active_scene_viewer(self):
        viewer = self._karma_scene_viewer
        if viewer is not None:
            try:
                viewer.curViewport()
                return viewer
            except hou.Error:
                self._karma_scene_viewer = None

        for tab in hou.ui.paneTabs():
            if tab.type() == hou.paneTabType.SceneViewer and self._is_stage_viewer(tab):
                return tab

        desktop = hou.ui.curDesktop()
        if desktop is None:
            return None
        return desktop.paneTabOfType(hou.paneTabType.SceneViewer)

    # ------------------------------------------------------------
    @_guarded_slot
    def on_apply_viewport_engine(self):
        engine = self.combo_viewport_engine.currentText().strip().lower()
        self.combo_engine.setCurrentText(engine)
        self.on_build()

        scene_viewer = self._get_active_scene_viewer()
        if scene_viewer is None:
            self.log_message("[WARN] Karma viewport not found.")
            return

        vp = None
        try:
            vp = scene_viewer.curViewport()
        except hou.Error:
            vp = None

        if self._set_viewport_renderer(scene_viewer, vp, engine):
            self.log_message("[OK] Karma viewport renderer set to {}.".format(engine.upper()))
        else:
            self.log_message("[WARN] Could not switch Karma viewport renderer to {}.".format(engine.upper()))

    # ------------------------------------------------------------
    def _sync_viewport_engine_combo(self, engine):
        if hasattr(self, "combo_viewport_engine") and self.combo_viewport_engine is not None:
            if self.combo_viewport_engine.currentText() != engine:
                self.combo_viewport_engine.blockSignals(True)
                self.combo_viewport_engine.setCurrentText(engine)
                self.combo_viewport_engine.blockSignals(False)

    # ------------------------------------------------------------
    def _render_camera_prim_path(self):
        ks = hou.node("/stage/karma_settings")
        if ks is not None and ks.parm("camera") is not None:
            value = ks.parm("camera").evalAsString().strip()
            if value.startswith("/"):
                return value
        choice = self._current_camera_choice()
        if choice.startswith(USD_CAMERA_PREFIX):
            return choice[len(USD_CAMERA_PREFIX):]
        if choice != CAMERA_CREATE_LABEL:
            node = hou.node(choice)
            if node is not None:
                return _camera_prim_path(node)
        return ""

    # ------------------------------------------------------------------------
    # Fix erreur = setCamera(node) lève TypeError sur H22, Solaris veut le chemin de prim USD en chaîne
    def _lock_viewport_to_camera(self, scene_viewer, viewport, prim_path):
        if viewport is None or not prim_path:
            return False
        try:
            viewport.setCamera(prim_path)
            return True
        except (hou.Error, TypeError):
            pass
        # older builds: node path through hscript. The path comes from the scene (a .hip can hold anything),
        # so only a plain USD path may go into a command line
        if not _PRIM_PATH_RE.match(prim_path):
            return False
        for cmd in (
            'viewcamera "{}" "{}"'.format(prim_path, viewport.name()),
            'viewcamera -c "{}" "{}"'.format(prim_path, viewport.name()),
        ):
            try:
                hou.hscript(cmd)
                return True
            except hou.Error:
                pass
        return False

    def _apply_camera_to_viewport(self, scene_viewer, viewport):
        self._lock_viewport_to_camera(scene_viewer, viewport, self._render_camera_prim_path())

    @_guarded_slot
    def on_look_through_camera(self):
        stage = hou.node("/stage")
        if self._current_camera_choice() == CAMERA_CREATE_LABEL and (stage is None or stage.node(GENERATED_CAMERA_NAME) is None):
            self.on_build()
        scene_viewer = self._get_active_scene_viewer()
        if scene_viewer is None or not self._is_stage_viewer(scene_viewer):
            # Solaris cameras only exist in a viewer on /stage: open the Karma viewport, which locks the camera
            self.log_message("[INFO] No Scene Viewer on /stage: opening the Karma viewport.")
            self.on_open_viewport()
            return
        try:
            viewport = scene_viewer.curViewport()
        except hou.Error:
            viewport = None
        prim_path = self._render_camera_prim_path()
        if self._lock_viewport_to_camera(scene_viewer, viewport, prim_path):
            self.log_message("[OK] Viewport locked to {}.".format(prim_path))
        else:
            self.log_message("[WARN] Could not lock the viewport to {}.".format(prim_path or "the render camera"))

    # ----------------------------------------------------------------------
    @_guarded_slot
    def on_open_karma_settings(self):
        self.on_build()
        desktop = hou.ui.curDesktop()
        if desktop is None:
            self.log_message("[WARN] Cannot access current Houdini desktop.")
            return
        self._open_karma_render_options_panel(desktop)
        self.log_message("[OK] Karma settings panel opened.")

    # ------------------------------------------------------------
    @_guarded_slot
    def on_open_viewport(self):
        self.on_build()

        stage = hou.node("/stage")
        cam_prim_path = self._render_camera_prim_path()

        desktop = hou.ui.curDesktop()
        if desktop is None:
            self.log_message("[WARN] Cannot access current Houdini desktop.")
            return

        scene_viewer = self._karma_scene_viewer
        is_new_viewer = False

        if scene_viewer is not None:
            try:
                scene_viewer.curViewport()
            except hou.Error:
                scene_viewer = None
                self._karma_scene_viewer = None

        if scene_viewer is None:
            scene_viewer = desktop.createFloatingPaneTab(hou.paneTabType.SceneViewer)
            if scene_viewer is None:
                self.log_message("[WARN] Failed to create floating Scene Viewer.")
                return
            self._karma_scene_viewer = scene_viewer
            is_new_viewer = True

        vp = None
        renderer_set = False
        if stage is not None:
            try:
                scene_viewer.setPwd(stage)
            except hou.Error:
                pass

        try:
            vp = scene_viewer.curViewport()
        except hou.Error:
            vp = None

        engine = self.combo_engine.currentText().strip().lower()
        renderer_set = self._set_viewport_renderer(scene_viewer, vp, engine)

        if vp is not None and cam_prim_path:
            if not self._lock_viewport_to_camera(scene_viewer, vp, cam_prim_path):
                self.log_message("[WARN] Viewport opened, but camera lock to {} could not be set.".format(cam_prim_path))

        self._set_karma_viewport_minimal_ui(scene_viewer, vp)

        if renderer_set:
            if is_new_viewer:
                self.log_message("[OK] Karma viewport opened.")
            else:
                self.log_message("[OK] Karma viewport updated.")
        else:
            self.log_message("[WARN] Viewport opened, but Karma renderer switch could not be confirmed.")
