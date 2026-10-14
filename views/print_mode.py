# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Faci3D's 3D-printing interface, applied once the window is built and its
saved layout restored (``apply``):

- toolbars: Draw, Modify, Annotate and Solid Tools keep the everyday tools
  (the rest stay in the menus, with their keys);
- units: millimetres for new documents, without the start-up question;
- the 3D Print menu and the print bed (views/print_bed.py).

IngeTrazo, which Faci3D forks, also carried georeferencing, BIM, sheets,
sections, walkthroughs and sun shadows; Faci3D removed them.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QToolBar

#: What each trimmed toolbar keeps, by tool key (``"text3d"`` is the 3D Text
#: command). Everything else on it leaves the bar but stays in the menus.
TOOLBAR_KEEP = {
    "draw": ("line", "rectangle", "circle", "polygon", "arc"),
    "modify": ("pushpull", "move", "rotate", "scale", "offset", "fillet"),
    "annotate": ("tape", "text3d"),
    "solids": ("solid_union", "solid_subtract", "solid_intersect"),
}

#: Units of a new document: millimetres, to a tenth — a 0.4 mm wall must
#: not read as "0 mm".
PRINT_UNITS = {"length": "mm", "precision": 1}


def apply(window) -> None:
    """Trim ``window`` down to the 3D-printing interface."""
    from views import print_bed
    _trim_toolbars(window)
    print_bed.install(window)
    # A new document (the window opens on one) starts framed on the bed.
    print_bed.frame_bed(window)


def ensure_print_units(window) -> None:
    """New documents in millimetres unless the user already chose units
    for them; the untouched first document follows at once."""
    from core import units
    st = QSettings()
    if not st.contains(units.NEW_DOCUMENT_KEY):
        units.remember_new_document_units(PRINT_UNITS)
    if (window._current_path is None
            and window.viewport.scene.version == window._saved_version):
        units.apply_units(window.viewport.scene, units.new_document_units())
        window._saved_version = window.viewport.scene.version


# ---- internals --------------------------------------------------------------

def _trim_toolbars(window) -> None:
    key_of = {act: key for key, act in window._tool_actions.items()}
    act_3d = getattr(window, "_act_3dtext", None)
    if act_3d is not None:
        key_of[act_3d] = "text3d"
    for name, keep in TOOLBAR_KEEP.items():
        tb = window.toolbars.get(name)
        if tb is None:
            continue
        for act in list(tb.actions()):
            if act.isSeparator() or key_of.get(act) not in keep:
                tb.removeAction(act)


def visible_toolbars(window) -> list:
    """The toolbars left in the window (for tests and diagnostics)."""
    return [tb for tb in window.findChildren(QToolBar)
            if tb.parent() is window]
