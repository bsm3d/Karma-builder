# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Viewport snapshots: A/B slots, compare and save
# Houdini : 21 and 22
# Version : 1.0.0

import datetime
import hou
import os
from hutil.Qt import QtCore, QtGui
from .debuglog import _guarded_slot
from .util import _clamp, _expand_plain_path, _private_temp_dir

# ------------------------------------------------------------
class SnapshotMixin:

    # --------------------------------------------------
    def _clear_snapshot_images(self):
        self._snapshot_source_image = QtGui.QImage()
        self._snapshot_compare_image = QtGui.QImage()

    # ------------------------------------------------------------
    @_guarded_slot
    def on_capture_viewport_snapshot(self):
        img = self._capture_viewport_snapshot_image()
        if img is None:
            return

        slot = self._snapshot_slot_target
        if slot == "B":
            self._snapshot_compare_image = img
            self._set_snapshot_slot_target("A")
        else:
            self._snapshot_source_image = img
            self._set_snapshot_slot_target("B")

        self.btn_save_snapshot.setEnabled(True)
        self._update_snapshot_slots_ui()
        self._update_snapshot_preview()
        self.log_message("[OK] Snapshot {} updated ({}x{}).".format(slot, img.width(), img.height()))

    # --------------------------------------------------------
    def on_capture_viewport_snapshot_compare(self):
        self._set_snapshot_slot_target("B")
        self.on_capture_viewport_snapshot()

    # --------------------------------------------------------
    def _set_snapshot_slot_target(self, slot_name):
        slot = "A" if slot_name not in ("A", "B") else slot_name
        self._snapshot_slot_target = slot
        if hasattr(self, "btn_snapshot_slot_a"):
            self.btn_snapshot_slot_a.setChecked(slot == "A")
        if hasattr(self, "btn_snapshot_slot_b"):
            self.btn_snapshot_slot_b.setChecked(slot == "B")
        self._update_snapshot_slots_ui()

    def _snapshot_has_compare(self):
        return (
            self._snapshot_source_image is not None
            and not self._snapshot_source_image.isNull()
            and self._snapshot_compare_image is not None
            and not self._snapshot_compare_image.isNull()
        )

    # --------------------------------------------------------
    def _snapshot_any_image(self):
        return (
            self._snapshot_source_image is not None
            and not self._snapshot_source_image.isNull()
        ) or (
            self._snapshot_compare_image is not None
            and not self._snapshot_compare_image.isNull()
        )

    # ----------------------------------------------------------------
    def _update_snapshot_slot_button(self, btn, slot_name, img):
        is_target = (self._snapshot_slot_target == slot_name)
        label = "Slot {}{}".format(slot_name, " [Target]" if is_target else "")
        btn.setText(label)
        btn.setChecked(is_target)

        if img is None or img.isNull():
            btn.setIcon(QtGui.QIcon())
            btn.setStyleSheet("QToolButton {border: 1px solid #505050; background-color: #2a2a2a;}")
            return

        px = QtGui.QPixmap.fromImage(img)
        if not px.isNull():
            thumb = px.scaled(
                btn.iconSize(),
                QtCore.Qt.KeepAspectRatioByExpanding,
                QtCore.Qt.SmoothTransformation,
            )
            if thumb.width() > btn.iconSize().width() or thumb.height() > btn.iconSize().height():
                x = max(0, int((thumb.width() - btn.iconSize().width()) * 0.5))
                y = max(0, int((thumb.height() - btn.iconSize().height()) * 0.5))
                thumb = thumb.copy(x, y, btn.iconSize().width(), btn.iconSize().height())
            btn.setIcon(QtGui.QIcon(thumb))
        btn.setStyleSheet("QToolButton {border: 1px solid #5e738b; background-color: #2b3440;}")

    # ------------------------------------------------------------
    def _update_snapshot_slots_ui(self):
        if not hasattr(self, "btn_snapshot_slot_a"):
            return

        self._update_snapshot_slot_button(self.btn_snapshot_slot_a, "A", self._snapshot_source_image)
        self._update_snapshot_slot_button(self.btn_snapshot_slot_b, "B", self._snapshot_compare_image)

        has_compare = self._snapshot_has_compare()
        if hasattr(self, "chk_snapshot_compare"):
            self.chk_snapshot_compare.setEnabled(has_compare)
            if has_compare and not self.chk_snapshot_compare.isChecked():
                self.chk_snapshot_compare.setChecked(True)
            if not has_compare:
                self.chk_snapshot_compare.setChecked(False)
        if hasattr(self, "sld_snapshot_compare"):
            self.sld_snapshot_compare.setEnabled(has_compare and self.chk_snapshot_compare.isChecked())
        if hasattr(self, "btn_save_snapshot"):
            self.btn_save_snapshot.setEnabled(self._snapshot_any_image())

    # ------------------------------------------------------------
    def on_clear_snapshot_slots(self):
        self._snapshot_source_image = QtGui.QImage()
        self._snapshot_compare_image = QtGui.QImage()
        self._set_snapshot_slot_target("A")
        self._update_snapshot_slots_ui()
        self._update_snapshot_preview()
        self.log_message("[OK] Snapshot slots cleared.")

    # ----------------------------------------------------------------------
    def _capture_viewport_snapshot_image(self):
        scene_viewer = self._get_active_scene_viewer()
        if scene_viewer is None:
            self.log_message("[WARN] No Scene Viewer found for snapshot.")
            return None

        vp = None
        try:
            vp = scene_viewer.curViewport()
        except hou.Error:
            vp = None

        if vp is None:
            self.log_message("[WARN] No active viewport to capture.")
            return None

        self._apply_camera_to_viewport(scene_viewer, vp)

        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        tmp_path = os.path.join(_private_temp_dir(), "snapshot_{}.png".format(stamp))
        captured_path = None

        try:
            if self._capture_with_viewport_methods(vp, tmp_path):
                captured_path = tmp_path
            else:
                captured_path = self._capture_with_flipbook(scene_viewer, vp, stamp, ext="png")

            if not captured_path:
                self.log_message("[WARN] Snapshot capture failed.")
                return None

            img = QtGui.QImage(captured_path)
            if img.isNull():
                self.log_message("[WARN] Snapshot captured but image is invalid.")
                return None
            return img
        except (hou.Error, OSError, RuntimeError, AttributeError) as exc:
            self.log_message("[WARN] Snapshot capture failed: {}".format(exc))
            return None
        finally:
            import glob
            cleanup_pattern = os.path.join(_private_temp_dir(), "snapshot_{}*".format(stamp))
            for p in glob.glob(cleanup_pattern):
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except OSError:
                    pass

    def _capture_with_viewport_methods(self, viewport, output_path):
        for method_name in ("saveViewToImage", "saveViewToFile", "saveViewImage"):
            method = getattr(viewport, method_name, None)
            if not callable(method):
                continue
            try:
                method(output_path)
                if os.path.isfile(output_path):
                    return True
            except (hou.Error, TypeError):
                pass
        return False

    # ------------------------------------------------------------
    def _capture_with_flipbook(self, viewer, viewport, stamp, ext="png"):
        frame = int(round(hou.frame()))
        pattern = os.path.join(_private_temp_dir(), "snapshot_{}.$F4.{}".format(stamp, ext))

        settings = viewer.flipbookSettings().stash()
        try:
            settings.outputToMPlay(False)
        except (hou.Error, AttributeError, TypeError):
            pass
        try:
            settings.output(pattern)
        except (hou.Error, AttributeError, TypeError):
            return None
        try:
            settings.frameRange((frame, frame))
        except (hou.Error, AttributeError, TypeError):
            pass
        try:
            settings.frameIncrement(1)
        except (hou.Error, AttributeError, TypeError):
            pass
        try:
            settings.useResolution(False)
        except (hou.Error, AttributeError, TypeError):
            pass

        viewer.flipbook(viewport, settings)

        expected = pattern.replace("$F4", "{:04d}".format(frame))
        if os.path.isfile(expected):
            return expected
        return None

    # ------------------------------------------------------------
    def _pixmap_with_safe_overlay(self, pixmap):
        if not self.chk_snapshot_safe.isChecked():
            return pixmap

        safe_type = self.combo_snapshot_safe_type.currentText()
        overlays = []
        if safe_type in ("Action Safe", "Both"):
            overlays.append((0.10, QtGui.QColor("#ff6b6b")))
        if safe_type in ("Text Safe", "Both"):
            overlays.append((0.05, QtGui.QColor("#ffe066")))

        painter = QtGui.QPainter(pixmap)
        rect = QtCore.QRectF(pixmap.rect())
        for margin, color in overlays:
            painter.setPen(QtGui.QPen(color, 1))
            safe_rect = QtCore.QRectF(
                rect.left() + rect.width() * margin,
                rect.top() + rect.height() * margin,
                rect.width() * (1.0 - margin * 2.0),
                rect.height() * (1.0 - margin * 2.0),
            )
            painter.drawRect(safe_rect)
        painter.end()
        return pixmap

    # ------------------------------------------------------------------------
    def _build_centered_pixmap(self, source_image, target_size):
        if source_image is None or source_image.isNull():
            return QtGui.QPixmap()

        src = QtGui.QPixmap.fromImage(source_image)
        if src.isNull():
            return QtGui.QPixmap()

        scaled = src.scaled(target_size, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
        if scaled.isNull():
            return QtGui.QPixmap()

        x = max(0, int((scaled.width() - target_size.width()) * 0.5))
        y = max(0, int((scaled.height() - target_size.height()) * 0.5))
        return scaled.copy(x, y, target_size.width(), target_size.height())

    # ----------------------------------------------------------------
    def _build_compare_pixmap(self, img_a, img_b, target_size, split_percent):
        px_a = self._build_centered_pixmap(img_a, target_size)
        px_b = self._build_centered_pixmap(img_b, target_size)
        if px_a.isNull() or px_b.isNull():
            return px_a if not px_a.isNull() else px_b

        result = QtGui.QPixmap(px_a)
        split_x = int(target_size.width() * (_clamp(split_percent, 0.0, 100.0) / 100.0))
        split_x = max(1, min(target_size.width() - 1, split_x))

        painter = QtGui.QPainter(result)
        painter.setClipRect(QtCore.QRect(0, 0, split_x, target_size.height()))
        painter.drawPixmap(0, 0, px_b)
        painter.setClipping(False)
        painter.setPen(QtGui.QPen(QtGui.QColor("#ffd166"), 2))
        painter.drawLine(split_x, 0, split_x, target_size.height())
        painter.end()
        return result

    # ------------------------------------------------------------
    def _update_snapshot_preview(self, rebuild=False):
        label = self.lbl_snapshot_preview
        if not self._snapshot_any_image():
            label.set_ratio(None)
            label.setPixmap(QtGui.QPixmap())
            label.setText("No snapshot yet.")
            self.lbl_snapshot_caption.setText("")
            return

        source_img = self._snapshot_source_image
        if source_img is None or source_img.isNull():
            source_img = self._snapshot_compare_image
        label.set_ratio(source_img.height() / float(max(1, source_img.width())))

        # the label takes its new height at the next layout pass: work with the size it is going to have
        target_size = QtCore.QSize(label.width(), label.target_height())
        if target_size.width() < 2 or target_size.height() < 2:
            return
        self._last_snapshot_preview_size = label.size()

        fitted = QtCore.QSize(source_img.size()).scaled(target_size, QtCore.Qt.KeepAspectRatio)
        compare_ready = self._snapshot_has_compare() and (
            (not hasattr(self, "chk_snapshot_compare")) or self.chk_snapshot_compare.isChecked()
        )
        if compare_ready:
            picture = self._build_compare_pixmap(
                self._snapshot_source_image,
                self._snapshot_compare_image,
                fitted,
                float(self.sld_snapshot_compare.value()),
            )
        else:
            picture = self._build_centered_pixmap(source_img, fitted)
        picture = self._pixmap_with_safe_overlay(picture)

        frame = QtGui.QPixmap(target_size)
        frame.fill(QtGui.QColor("#1f1f1f"))
        painter = QtGui.QPainter(frame)
        painter.drawPixmap((target_size.width() - fitted.width()) // 2, (target_size.height() - fitted.height()) // 2, picture)
        painter.end()
        label.setText("")
        label.setPixmap(frame)
        self.lbl_snapshot_caption.setText(self._snapshot_caption(source_img, compare_ready))

    # ------------------------------------------------------------
    def _snapshot_caption(self, image, compared):
        parts = ["A | B compared" if compared else "Slot {}".format("A" if not self._snapshot_source_image.isNull() else "B"),
                 "{} x {}".format(image.width(), image.height())]
        if self.chk_snapshot_safe.isChecked():
            parts.append(self.combo_snapshot_safe_type.currentText())
        return "  |  ".join(parts)

    # ------------------------------------------------------------
    @_guarded_slot
    def on_save_viewport_snapshot(self):
        if not self._snapshot_any_image():
            self.log_message("[WARN] No snapshot to save.")
            return

        path = hou.ui.selectFile(
            start_directory="$HIP",
            title="Save Viewport Snapshot",
            pattern="*.png *.jpg",
            chooser_mode=hou.fileChooserMode.Write,
        )
        if not path:
            return

        try:
            path = _expand_plain_path(path)
        except ValueError as exc:
            self.log_message("[WARN] Snapshot not saved: {}".format(exc))
            return
        root, ext = os.path.splitext(path)
        if ext.lower() not in (".png", ".jpg", ".jpeg"):
            path = root + ".png"

        source_img = self._snapshot_source_image
        if source_img is None or source_img.isNull():
            source_img = self._snapshot_compare_image

        img_to_save = source_img.copy()
        if self.chk_snapshot_safe.isChecked():
            safe_type = self.combo_snapshot_safe_type.currentText()
            overlays = []
            if safe_type in ("Action Safe", "Both"):
                overlays.append((0.10, QtGui.QColor("#ff6b6b")))
            if safe_type in ("Text Safe", "Both"):
                overlays.append((0.05, QtGui.QColor("#ffe066")))

            painter = QtGui.QPainter(img_to_save)
            rect = QtCore.QRectF(img_to_save.rect())
            pen_w = max(1, int(round(min(img_to_save.width(), img_to_save.height()) * 0.002)))
            for margin, color in overlays:
                painter.setPen(QtGui.QPen(color, pen_w))
                safe_rect = QtCore.QRectF(
                    rect.left() + rect.width() * margin,
                    rect.top() + rect.height() * margin,
                    rect.width() * (1.0 - margin * 2.0),
                    rect.height() * (1.0 - margin * 2.0),
                )
                painter.drawRect(safe_rect)
            painter.end()

        if img_to_save.save(path):
            self.log_message("[OK] Snapshot saved: {}".format(path))
        else:
            self.log_message("[WARN] Failed to save snapshot: {}".format(path))
