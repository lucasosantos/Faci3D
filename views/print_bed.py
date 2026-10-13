# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The 3D Print menu: the printer, its bed in the viewport, and setting the
model down on it (core.printer holds the numbers).

A printer is OPTIONAL: Faci3D models freely without one, on the ground.

- **Printer…** picks a printer from the presets, types its build volume,
  or says there is none;
- **Show print bed** draws the plate and the build volume (asking for the
  printer the first time, when none was chosen);
- **Place on bed** sets the selection (or the whole model) down on the
  ground, its bottom at z = 0 — the plate, when there is a printer;
- **Center on bed** also centres it on the origin, the plate's middle.

Each placement is one undo step. When a printer is chosen and the result
does not fit its build volume, the status bar says so.
"""
from __future__ import annotations

from PySide6.QtGui import QAction, QVector3D
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout)

from core import printer as _printer
from core.i18n import tr


#: The combo entry for "no printer".
_NONE = "none"


class PrinterDialog(QDialog):
    """Pick a printer, type its build volume (millimetres), or say there is
    none."""

    def __init__(self, parent=None, current: _printer.Printer | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("3D printer"))
        if current is None:
            current = _printer.load()
        form = QFormLayout(self)
        self.model = QComboBox(self)
        self.model.addItem(tr("None (model freely)"), _NONE)
        for p in _printer.PRESETS:
            self.model.addItem(p.name, p)
        self.model.addItem(tr("Custom"), None)
        form.addRow(tr("Printer"), self.model)
        self.width = self._size_box()
        self.depth = self._size_box()
        self.height = self._size_box()
        form.addRow(tr("Width (X)"), self.width)
        form.addRow(tr("Depth (Y)"), self.depth)
        form.addRow(tr("Height (Z)"), self.height)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        if current is None:
            index = 0
            self._show_sizes(_printer.DEFAULT)
        else:
            index = next((i + 1 for i, p in enumerate(_printer.PRESETS)
                          if p == current), self.model.count() - 1)
            self._show_sizes(current)
        self.model.setCurrentIndex(index)
        self._sync_enabled()
        self.model.currentIndexChanged.connect(self._on_model)
        for box in (self.width, self.depth, self.height):
            box.valueChanged.connect(self._on_typed)

    def _size_box(self) -> QDoubleSpinBox:
        box = QDoubleSpinBox(self)
        box.setRange(10.0, 2000.0)
        box.setDecimals(0)
        box.setSuffix(" mm")
        return box

    def _show_sizes(self, p: _printer.Printer) -> None:
        for box, value in ((self.width, p.width), (self.depth, p.depth),
                           (self.height, p.height)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)

    def _sync_enabled(self) -> None:
        free = self.model.currentData() == _NONE
        for box in (self.width, self.depth, self.height):
            box.setEnabled(not free)

    def _on_model(self, _index: int) -> None:
        preset = self.model.currentData()
        if isinstance(preset, _printer.Printer):
            self._show_sizes(preset)
        self._sync_enabled()

    def _on_typed(self, _value: float) -> None:
        # Typing a size that is not the preset's makes it a custom printer.
        preset = self.model.currentData()
        if isinstance(preset, _printer.Printer) and \
                preset != self._typed(preset.name):
            self.model.blockSignals(True)
            self.model.setCurrentIndex(self.model.count() - 1)
            self.model.blockSignals(False)

    def _typed(self, name: str) -> _printer.Printer:
        return _printer.Printer(name, self.width.value(), self.depth.value(),
                                self.height.value())

    def printer(self) -> _printer.Printer | None:
        """The choice; ``None`` for no printer."""
        data = self.model.currentData()
        if data == _NONE:
            return None
        if isinstance(data, _printer.Printer):
            return data
        return self._typed(_printer.CUSTOM)


def install(window) -> None:
    """Add the 3D Print menu to ``window`` and show the bed."""
    menu = window.menuBar().addMenu(tr("3D Print"))
    window._print_menu = menu

    act_printer = QAction(tr("Printer…"), window)
    act_printer.setStatusTip(tr("Choose the printer, if you want: its "
                                "build volume is drawn as the bed."))
    act_printer.triggered.connect(lambda: choose_printer(window))
    menu.addAction(act_printer)

    act_bed = QAction(tr("Show print bed"), window)
    act_bed.setCheckable(True)
    act_bed.setChecked(_printer.bed_shown()
                       and _printer.load() is not None)
    act_bed.setStatusTip(tr("Show or hide the printer's bed and build "
                            "volume."))
    act_bed.toggled.connect(lambda on: show_bed(window, on))
    menu.addAction(act_bed)
    window._act_show_bed = act_bed
    menu.addSeparator()

    act_place = QAction(tr("Place on bed"), window)
    act_place.setShortcut("Ctrl+Shift+B")
    act_place.setStatusTip(tr("Set the selection — or the whole model — "
                              "down on the bed."))
    act_place.triggered.connect(lambda: place(window, centre=False))
    menu.addAction(act_place)

    act_centre = QAction(tr("Center on bed"), window)
    act_centre.setStatusTip(tr("Set the selection — or the whole model — "
                               "down in the middle of the bed."))
    act_centre.triggered.connect(lambda: place(window, centre=True))
    menu.addAction(act_centre)
    window._act_place_on_bed = act_place
    window._act_center_on_bed = act_centre

    # The two placements on a bar of their own: the step before every
    # export, so it should not take a trip to the menu.
    from views.icons import tool_icon
    tb = window._new_toolbar(tr("3D Print"), "print_bed")
    window.toolbars["print_bed"] = tb
    for act, key in ((act_place, "place_on_bed"),
                     (act_centre, "center_on_bed")):
        act.setIcon(tool_icon(key))
        act.setToolTip(f"{act.text()}\n{act.statusTip()}")
        tb.addAction(act)
        window._icon_actions.append((act, key))

    # Before Window and Help, where a document's own commands go.
    bar = window.menuBar()
    acts = bar.actions()
    window_title = tr("Window")
    anchor = next((a for a in acts if a.text() == window_title), None)
    if anchor is not None:
        bar.removeAction(menu.menuAction())
        bar.insertMenu(anchor, menu)

    show_bed(window, act_bed.isChecked())


def frame_bed(window) -> None:
    """Look at the bed from a corner above, framing the build volume — or,
    with no printer, a part-sized working area: the start view of a new
    document (a part is millimetres, not the 20 m an architect's default
    view takes in)."""
    lo, hi = (_printer.load() or _printer.WORK_AREA).bounds()
    cam = window.viewport.camera
    cam.set_view("iso")
    cam.fit_to(QVector3D(*lo), QVector3D(*hi))
    window.viewport.update()


def show_bed(window, shown: bool) -> None:
    """Show or hide the bed. Showing it with no printer chosen asks for
    one; cancelling (or choosing none) leaves the bed off."""
    bed = _printer.load()
    if shown and bed is None:
        act = getattr(window, "_act_show_bed", None)
        if getattr(window, "_asking_printer", False):
            return
        window._asking_printer = True
        try:
            chosen = choose_printer(window)
        finally:
            window._asking_printer = False
        if not chosen or _printer.load() is None:
            if act is not None:
                act.blockSignals(True)
                act.setChecked(False)
                act.blockSignals(False)
            window.viewport.set_print_bed(None)
        return
    _printer.set_bed_shown(shown)
    window.viewport.set_print_bed(bed if shown else None)


def choose_printer(window) -> bool:
    """Printer…: returns whether the user confirmed a choice (a printer or
    none)."""
    dlg = PrinterDialog(window)
    try:
        if dlg.exec() != QDialog.Accepted:
            return False
        chosen = dlg.printer()
    finally:
        dlg.deleteLater()
    _printer.save(chosen)
    act = getattr(window, "_act_show_bed", None)
    if chosen is None:
        if act is not None:
            act.blockSignals(True)
            act.setChecked(False)
            act.blockSignals(False)
        window.viewport.set_print_bed(None)
        window.statusBar().showMessage(
            tr("No printer: modelling freely on the ground."), 4000)
        return True
    _printer.set_bed_shown(True)
    if act is not None and not act.isChecked():
        act.blockSignals(True)
        act.setChecked(True)
        act.blockSignals(False)
    window.viewport.set_print_bed(chosen)
    window.statusBar().showMessage(
        tr("Printer: {name} — {w:.0f} × {d:.0f} × {h:.0f} mm",
           name=tr(chosen.name), w=chosen.width, d=chosen.depth,
           h=chosen.height), 4000)
    return True


def _move_commands(scene, delta: QVector3D) -> list:
    """The commands that move the selection — or, with nothing selected,
    the whole model — by ``delta``."""
    from core.group import Group
    from core.history import MoveGroupCommand, MoveVerticesCommand
    if scene.selection:
        groups = [e for e in scene.selection if isinstance(e, Group)]
        points: dict = {}
        for e in scene.selection:
            if isinstance(e, Group):
                continue
            if hasattr(e, "vertices"):            # Face
                for p in e.vertices:
                    points[(p.x(), p.y(), p.z())] = p
            elif hasattr(e, "v0"):                # Edge
                for p in (e.a, e.b):
                    points[(p.x(), p.y(), p.z())] = p
        loose = list(points.values())
    else:
        groups = [g for g in scene.groups if scene.entity_visible(g)]
        loose = [v.position for v in scene.loose_mesh.vertices]
    cmds = [MoveGroupCommand(g, delta) for g in groups]
    if loose:
        cmds.append(MoveVerticesCommand(loose, delta))
    return cmds


def place(window, centre: bool) -> bool:
    """Place on bed / Center on bed. Returns whether anything moved."""
    from core.history import CompoundCommand
    vp = window.viewport
    scene = vp.scene
    status = window.statusBar()
    if scene.edit_group is not None:
        status.showMessage(tr("Close the group being edited first."), 4000)
        return False
    lo, hi = (scene.selection_bounds() if scene.selection
              else scene.bounds())
    if lo is None:
        status.showMessage(tr("Nothing to place on the bed."), 4000)
        return False
    lo_t, hi_t = (lo.x(), lo.y(), lo.z()), (hi.x(), hi.y(), hi.z())
    d = (_printer.centre_delta(lo_t, hi_t) if centre
         else _printer.drop_delta(lo_t, hi_t))
    delta = QVector3D(*d)
    moved = delta.length() > 1e-9
    if moved:
        cmds = _move_commands(scene, delta)
        if not cmds:
            return False
        vp.history.execute(CompoundCommand(cmds))
        vp.notify_scene_changed()
        vp.update()
    bed = _printer.load()
    if bed is not None and not _printer.fits(bed, lo_t, hi_t):
        status.showMessage(tr("It does not fit the build volume of {name}.",
                              name=tr(bed.name)), 6000)
    elif moved:
        status.showMessage(tr("On the bed."), 3000)
    return moved
