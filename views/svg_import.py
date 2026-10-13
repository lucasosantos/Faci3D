# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""File ▸ Import ▸ SVG: the size dialog and the undoable import
(formats/svg_in.py does the reading and the geometry).

The dialog shows the drawing's own size and lets the user change it — width
or height, the other follows — since an SVG made for a screen rarely has the
size the printed part should have. The result arrives selected, on the
ground, ready for Push/Pull.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QMessageBox)

from core.i18n import tr
from formats import svg_in


class SvgSizeDialog(QDialog):
    """Width × height in millimetres, kept in proportion."""

    def __init__(self, parent, width_mm: float, height_mm: float,
                 name: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Import SVG"))
        self._w0 = max(width_mm, 1e-6)
        self._h0 = max(height_mm, 1e-6)
        form = QFormLayout(self)
        form.addRow(QLabel(tr("{name}: {w:.1f} × {h:.1f} mm as drawn.",
                              name=name, w=width_mm, h=height_mm), self))
        self.width = self._box(width_mm)
        self.height = self._box(height_mm)
        form.addRow(tr("Width (X)"), self.width)
        form.addRow(tr("Depth (Y)"), self.height)
        form.addRow(QLabel(tr("Closed shapes become faces, ready for "
                              "Push/Pull."), self))
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.width.valueChanged.connect(self._on_width)
        self.height.valueChanged.connect(self._on_height)

    def _box(self, value: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox(self)
        box.setRange(0.1, 100000.0)
        box.setDecimals(1)
        box.setSuffix(" mm")
        box.setValue(value)
        return box

    def _on_width(self, w: float) -> None:
        self.height.blockSignals(True)
        self.height.setValue(w * self._h0 / self._w0)
        self.height.blockSignals(False)

    def _on_height(self, h: float) -> None:
        self.width.blockSignals(True)
        self.width.setValue(h * self._w0 / self._h0)
        self.width.blockSignals(False)

    def scale(self) -> float:
        """The factor from the drawing's own size to the chosen one."""
        return self.width.value() / self._w0


def _import_command(drawing, scale: float, result: dict):
    """The undoable import. It selects nothing itself, but the faces it
    made leave the selection when it is undone — a selection holding faces
    that no longer exist is what the caller's select would leave behind."""
    from core.history import SnapshotImport

    class SvgImport(SnapshotImport):
        def undo(self, scene) -> None:
            super().undo(scene)
            stats = result.get("stats")
            if stats is not None:
                scene.selection.difference_update(stats.new_faces)

    return SvgImport(lambda scene: result.update(
        stats=svg_in.add_to_scene(scene, drawing, scale)))


def import_svg_path(window, path: Path, scale: float | None = None) -> bool:
    """Read ``path``, ask its size (unless ``scale`` is given), build it as
    one undo step and select the new faces. Returns whether it came in."""
    path = Path(path)
    try:
        drawing = svg_in.parse_svg(path)
    except (svg_in.SvgError, OSError) as exc:
        QMessageBox.warning(window, tr("Import SVG"), str(exc))
        return False
    if scale is None:
        w, h = drawing.size()
        dlg = SvgSizeDialog(window, w, h, path.name)
        try:
            if dlg.exec() != QDialog.Accepted:
                return False
            scale = dlg.scale()
        finally:
            dlg.deleteLater()
    if abs(scale - 1.0) > 1e-9:
        # Read again at the chosen size: the curve tolerance and the
        # weld-sized steps must hold for the part as it will be built.
        drawing = svg_in.parse_svg(path, scale=scale)
    vp = window.viewport
    vp.end_group_edit()
    result: dict = {}
    cmd = _import_command(drawing, scale, result)
    try:
        vp.history.execute(cmd)
    except Exception as exc:  # noqa: BLE001 - surface any build error
        QMessageBox.critical(window, tr("Import SVG"), str(exc))
        return False
    stats = result.get("stats")
    if stats is None:
        return False
    scene = vp.scene
    scene.select(stats.new_faces, additive=False)
    vp.notify_scene_changed()
    vp.update()
    msg = tr("Imported {name}: {faces} faces, {w:.1f} × {h:.1f} mm.",
             name=path.name, faces=stats.faces, w=stats.size_mm[0],
             h=stats.size_mm[1])
    if stats.skipped.get("text"):
        msg += " " + tr("Text was left out: convert it to paths first.")
    window.statusBar().showMessage(msg, 8000)
    return True
