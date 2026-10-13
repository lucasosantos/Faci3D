# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Faci3D's 3D-printing interface: the modeller with the architecture and
civil-engineering features out of sight.

IngeTrazo, which Faci3D forks, carries georeferencing, BIM, sheets, sections,
walkthroughs and sun shadows. For someone modelling a part to print those
are noise, so this mode HIDES them — the code stays, so the fork keeps
merging upstream fixes, and ``ui/full_interface = 1`` in the settings brings
the whole interface back.

What it does, applied once the window is built and its saved layout restored
(``apply``):

- toolbars: Sections and Walkthrough go; Draw, Modify, Annotate and Solid
  Tools keep the everyday tools (the rest stay in the menus, with their keys);
- menus: entries listed in ``HIDDEN_MENU_ITEMS`` are hidden — a hidden
  action's shortcut does not fire either;
- side panels: BIM and Terrain leave Window ▸ Panels, Scenes leaves the
  Properties tray;
- extensions: Render with Blender is not loaded;
- units: millimetres for new documents, without the start-up question;
- the 3D Print menu and the print bed (views/print_bed.py).

Menu entries are named by their English source path, translated at run
time, so the list works in every UI language.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QToolBar

from core.i18n import tr

#: QSettings key: "1" brings back the full IngeTrazo interface.
FULL_INTERFACE_KEY = "ui/full_interface"

#: Toolbars taken out of the window altogether.
REMOVED_TOOLBARS = ("sections", "walkthrough")

#: What each trimmed toolbar keeps, by tool key (``"text3d"`` is the 3D Text
#: command). Everything else on it leaves the bar but stays in the menus.
TOOLBAR_KEEP = {
    "draw": ("line", "rectangle", "circle", "polygon", "arc"),
    "modify": ("pushpull", "move", "rotate", "scale", "offset", "fillet"),
    "annotate": ("tape", "text3d"),
    "solids": ("solid_union", "solid_subtract", "solid_intersect"),
}

#: Buttons of the Panels toolbar that go (Styles stays).
REMOVED_PANEL_BUTTONS = ("shadows", "dimension_style")

#: Projections without a place in the Standard Views bar.
REMOVED_PROJECTIONS = ("two_point",)

#: Menu entries hidden, as English source paths from the menu bar down.
HIDDEN_MENU_ITEMS = (
    ("File", "Import", "Orthomosaic (GeoTIFF)…"),
    ("File", "Import", "AutoCAD DWG (.dwg)…"),
    ("File", "Import", "AutoCAD DXF (.dxf)…"),
    ("File", "Import", "Georeference (KML / GeoJSON)…"),
    ("File", "Import", "Survey points CSV (UTM)…"),
    ("File", "Import", "Photogrammetric mesh (WebODM)…"),
    ("File", "Import", "Clear imported texture cache…"),
    ("File", "Export", "IFC (BIM)…"),
    ("File", "Export", "Current view as DXF…"),
    ("File", "Sheet composer…"),
    ("Edit", "Convert Path to Geometry"),
    ("Camera", "Two-Point Perspective"),
    ("Camera", "Style", "Architectural"),
    ("Camera", "Shadows"),
    ("Camera", "Section Planes"),
    ("Camera", "Section Cuts"),
    ("Camera", "Section Fill"),
    ("Camera", "Position Camera"),
    ("Camera", "Walk"),
    ("Camera", "Look Around"),
    ("Camera", "First Person"),
    ("Draw", "Path"),
    ("Tools", "Section Plane"),
    ("Tools", "Terrain profile of selection"),
    ("Window", "Terrain profile"),
    ("Help", "Get more models and textures…"),
)

#: Sections of the Properties tray hidden (its attribute names): Scenes are
#: presentation views of a building.
HIDDEN_TRAY_SECTIONS = ("scenes",)

#: Side panels (dock object names) kept out of Window ▸ Panels.
HIDDEN_DOCKS = frozenset({"tray_bim", "tray_georef", "dock_profile"})

#: Bundled extensions not loaded (plugin file stems).
SKIPPED_PLUGINS = frozenset({"render_blender"})

#: Units of a new document: millimetres, to a tenth — a 0.4 mm wall must
#: not read as "0 mm".
PRINT_UNITS = {"length": "mm", "precision": 1}


def enabled() -> bool:
    return str(QSettings().value(FULL_INTERFACE_KEY, "0")) != "1"


def apply(window) -> None:
    """Trim ``window`` down to the 3D-printing interface."""
    from views import print_bed
    _trim_toolbars(window)
    print_bed.install(window)
    # A new document (the window opens on one) starts framed on the bed.
    print_bed.frame_bed(window)
    _hide_menu_items(window.menuBar())
    for dock in _hidden_docks(window):
        dock.hide()
    for name in HIDDEN_TRAY_SECTIONS:
        panel = getattr(window.tray, name, None)
        if panel is not None and panel.parentWidget() is not None:
            panel.parentWidget().hide()


def skip_plugin(plugin) -> bool:
    from pathlib import Path
    path = getattr(plugin, "path", None)
    return bool(path) and Path(path).stem in SKIPPED_PLUGINS


def hides_dock(dock) -> bool:
    return dock.objectName() in HIDDEN_DOCKS


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
    window._print_removed_toolbars = []
    for name in REMOVED_TOOLBARS:
        tb = window.toolbars.get(name)
        if tb is not None:
            window.removeToolBar(tb)
            tb.setParent(None)
            # Kept referenced: its actions still serve the menus.
            window._print_removed_toolbars.append(tb)
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
    views_tb = window.toolbars.get("views")
    for mode in REMOVED_PROJECTIONS:
        act = getattr(window, "_projection_actions", {}).get(mode)
        if views_tb is not None and act is not None:
            views_tb.removeAction(act)
    panel_actions = getattr(window, "_panel_actions", {})
    for key in REMOVED_PANEL_BUTTONS:
        act = panel_actions.get(key)
        if act is not None:
            act.setVisible(False)


def _hide_menu_items(menubar) -> int:
    """Hide every entry of ``HIDDEN_MENU_ITEMS``; returns how many."""
    wanted = {tuple(tr(part) for part in path) for path in HIDDEN_MENU_ITEMS}
    hidden = 0

    def walk(menu, prefix):
        nonlocal hidden
        for act in menu.actions():
            if act.isSeparator():
                continue
            path = prefix + (act.text(),)
            if path in wanted:
                act.setVisible(False)
                hidden += 1
            elif act.menu() is not None:
                walk(act.menu(), path)

    walk(menubar, ())
    return hidden


def _hidden_docks(window) -> list:
    from PySide6.QtWidgets import QDockWidget
    return [d for d in window.findChildren(QDockWidget) if hides_dock(d)]


def visible_toolbars(window) -> list:
    """The toolbars left in the window (for tests and diagnostics)."""
    return [tb for tb in window.findChildren(QToolBar)
            if tb.parent() is window]
