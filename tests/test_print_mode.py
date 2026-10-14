# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Faci3D's 3D-printing interface (views/print_mode.py): the architecture
features gone, everyday modelling tools in reach, millimetres."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog, QToolBar

from core import i18n, units
from views import print_mode
from views.main_window import MainWindow


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


@pytest.fixture(autouse=True)
def no_printer():
    """Every test starts without a printer chosen — it is optional."""
    from core import printer
    printer.save(None)
    yield
    printer.save(None)


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(MainWindow, "print_mode", True)
    w = MainWindow()
    yield w
    _close(w)


def _bar_keys(win, name):
    key_of = {a: k for k, a in win._tool_actions.items()}
    key_of[win._act_3dtext] = "text3d"
    return [key_of.get(a, a.text()) for a in win.toolbars[name].actions()]


def test_architecture_toolbars_are_gone(win):
    left = {tb.objectName() for tb in win.findChildren(QToolBar)
            if tb.parent() is win}
    assert "sections" not in left and "walkthrough" not in left
    assert {"main", "draw", "modify", "annotate", "solids", "view",
            "views"} <= left


def test_trimmed_bars_keep_the_everyday_tools_in_order(win):
    for name, keep in print_mode.TOOLBAR_KEEP.items():
        assert _bar_keys(win, name) == list(keep)
    assert set(win._projection_actions) == {"parallel", "perspective"}
    assert set(win._panel_actions) == {"styles"}


def test_a_tool_off_the_bar_still_answers_from_the_menu(win):
    # Follow Me left the Modify bar but keeps its menu entry (and key).
    act = win._tool_actions["followme"]
    assert act not in win.toolbars["modify"].actions()
    assert act.isVisible()


#: Menu entries of the architecture features Faci3D removed, as English
#: source paths from the menu bar down.
REMOVED_MENU_ITEMS = (
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


def _menu_paths(menubar):
    paths = set()

    def walk(menu, prefix):
        for act in menu.actions():
            if act.isSeparator():
                continue
            path = prefix + (act.text(),)
            paths.add(path)
            if act.menu() is not None:
                walk(act.menu(), path)

    walk(menubar, ())
    return paths


@pytest.mark.parametrize("lang", ["en", "es", "pt-BR"])
def test_the_removed_features_have_no_menu_entry(lang, monkeypatch):
    before = i18n.current_language()
    i18n.set_language(lang)
    try:
        monkeypatch.setattr(MainWindow, "print_mode", True)
        w = MainWindow()
        try:
            shown = _menu_paths(w.menuBar())
            gone = {tuple(i18n.tr(part) for part in path)
                    for path in REMOVED_MENU_ITEMS}
            assert not shown & gone
            # The menus are still there: the check is not passing empty.
            assert (i18n.tr("File"), i18n.tr("Import"),
                    i18n.tr("SVG drawing (.svg)…")) in shown
        finally:
            _close(w)
    finally:
        i18n.set_language(before)


def test_only_the_modelling_trays_are_left(win):
    names = {d.objectName() for d in win._sidebar_docks()}
    assert {"tray_properties", "tray_project_browser"} <= names
    assert not names & {"tray_bim", "tray_georef", "dock_profile"}
    assert not hasattr(win.tray, "scenes")
    assert not win.tray.materials.parentWidget().isHidden()


def test_render_with_blender_is_gone():
    from core.paths import app_root
    assert not (app_root() / "plugins" / "render_blender.py").exists()
    assert (app_root() / "plugins" / "solid_inspector.py").exists()


def test_new_documents_start_in_millimetres(win):
    st = QSettings()
    st.remove(units.NEW_DOCUMENT_KEY)
    try:
        print_mode.ensure_print_units(win)
        assert win.viewport.scene.units == print_mode.PRINT_UNITS
        assert units.new_document_units() == print_mode.PRINT_UNITS
        assert win.viewport.scene.version == win._saved_version  # not dirty
    finally:
        units.remember_new_document_units(units.DEFAULT_MODEL_UNITS)


def test_a_units_choice_of_the_users_own_is_kept(win):
    own = {"length": "cm", "precision": 1}
    units.remember_new_document_units(own)
    try:
        print_mode.ensure_print_units(win)
        assert units.new_document_units() == own
    finally:
        units.remember_new_document_units(units.DEFAULT_MODEL_UNITS)


# ---- The 3D Print menu and the bed (views/print_bed.py) ----------------------

def _box_group(win, z0=0.05, x0=0.10):
    """A 20 mm cube floating above the ground, off to one side, as a group."""
    from PySide6.QtGui import QVector3D
    from core.group import Group
    from core.mesh import Mesh
    s = 0.02
    m = Mesh()
    c = [QVector3D(x0 + dx * s, dy * s, z0 + dz * s)
         for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)]
    for quad in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3),
                 (0, 4, 6, 2), (1, 3, 7, 5)):
        m.add_face([c[i] for i in quad])
    g = Group(m, name="Cube")
    win.viewport.scene.groups.append(g)
    win.viewport.scene.version += 1
    return g


def test_the_print_menu_sits_before_window(win):
    titles = [a.text() for a in win.menuBar().actions()]
    assert titles.index(i18n.tr("3D Print")) == \
        titles.index(i18n.tr("Window")) - 1
    assert win._act_place_on_bed in win.toolbars["print_bed"].actions()


def test_without_a_printer_there_is_no_bed(win):
    assert win.viewport.print_bed is None
    assert not win._act_show_bed.isChecked()


def test_showing_the_bed_asks_for_a_printer_and_cancel_keeps_it_off(
        win, monkeypatch):
    from views.print_bed import PrinterDialog
    monkeypatch.setattr(PrinterDialog, "exec", lambda self: QDialog.Rejected)
    win._act_show_bed.setChecked(True)
    assert not win._act_show_bed.isChecked()
    assert win.viewport.print_bed is None


def test_choosing_a_printer_shows_its_bed(win, monkeypatch):
    from core import printer
    from views import print_bed
    from views.print_bed import PrinterDialog

    def pick(self):
        self.model.setCurrentIndex(3)          # a preset, past "None"
        return QDialog.Accepted

    monkeypatch.setattr(PrinterDialog, "exec", pick)
    win._act_show_bed.setChecked(True)
    assert printer.load() == printer.PRESETS[2]
    assert win.viewport.print_bed == printer.PRESETS[2]
    assert win._act_show_bed.isChecked()
    win._act_show_bed.setChecked(False)
    assert win.viewport.print_bed is None

    def none(self):
        self.model.setCurrentIndex(0)
        return QDialog.Accepted

    monkeypatch.setattr(PrinterDialog, "exec", none)
    assert print_bed.choose_printer(win)
    assert printer.load() is None
    assert win.viewport.print_bed is None


def test_place_on_bed_drops_the_whole_model_in_one_undo(win):
    from views import print_bed
    g = _box_group(win)
    assert print_bed.place(win, centre=False)
    lo, hi = win.viewport.scene.bounds()
    assert lo.z() == pytest.approx(0.0, abs=1e-9)
    assert lo.x() == pytest.approx(0.10)               # not moved sideways
    assert win.viewport.history.undo()
    assert win.viewport.scene.bounds()[0].z() == pytest.approx(0.05)
    assert g in win.viewport.scene.groups


def test_center_on_bed_moves_the_selection_only(win):
    from views import print_bed
    a = _box_group(win, z0=0.05, x0=0.10)
    b = _box_group(win, z0=0.03, x0=-0.08)
    win.viewport.scene.select([], additive=False)
    win.viewport.scene.selection.add(a)
    assert print_bed.place(win, centre=True)
    lo, hi = win.viewport.scene.selection_bounds()
    assert ((lo.x() + hi.x()) / 2, (lo.y() + hi.y()) / 2, lo.z()) == \
        pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    others = [v.position.z() for v in b.mesh.vertices]
    assert min(others) == pytest.approx(0.03)          # b stayed


def test_a_part_bigger_than_the_printer_is_reported(win):
    from PySide6.QtGui import QVector3D
    from views import print_bed
    m = win.viewport.scene.mesh
    m.add_face([QVector3D(0, 0, 0.01), QVector3D(0.5, 0, 0.01),
                QVector3D(0.5, 0.5, 0.01), QVector3D(0, 0.5, 0.01)])
    win.viewport.scene.version += 1
    from core import printer
    printer.save(printer.PRESETS[0])
    assert print_bed.place(win, centre=False)
    assert win.viewport.scene.bounds()[0].z() == pytest.approx(0.0, abs=1e-9)
    bed = printer.load()
    assert win.statusBar().currentMessage() == i18n.tr(
        "It does not fit the build volume of {name}.", name=i18n.tr(bed.name))


def test_without_a_printer_any_size_is_fine(win):
    from PySide6.QtGui import QVector3D
    from views import print_bed
    m = win.viewport.scene.mesh
    m.add_face([QVector3D(0, 0, 0.01), QVector3D(5, 0, 0.01),
                QVector3D(5, 5, 0.01), QVector3D(0, 5, 0.01)])
    win.viewport.scene.version += 1
    assert print_bed.place(win, centre=True)
    assert win.statusBar().currentMessage() == i18n.tr("On the bed.")


def test_nothing_to_place_says_so(win):
    from views import print_bed
    assert not print_bed.place(win, centre=True)


def test_a_new_document_starts_with_a_150_mm_potted_plant(win):
    from core.insert import is_scale_figure
    figures = [g for g in win.viewport.scene.groups if g.billboard]
    assert len(figures) == 1
    pot = figures[0]
    zs = [v.position.z() for v in pot.mesh.vertices]
    assert max(zs) - min(zs) == pytest.approx(0.15)
    assert min(zs) == pytest.approx(0.0)
    assert pot.name == i18n.tr("Plant pot")
    assert is_scale_figure(pot)
    assert win.viewport.scene.version == win._saved_version   # not dirty


def test_the_full_interface_keeps_the_engineer():
    w = MainWindow()
    try:
        figures = [g for g in w.viewport.scene.groups if g.billboard]
        zs = [v.position.z() for v in figures[0].mesh.vertices]
        assert max(zs) - min(zs) == pytest.approx(1.70)
    finally:
        _close(w)


# ---- The Faci3D brand (core.version, core.i18n) ------------------------------

def test_the_interface_says_faci3d_and_shortcut_keys_stay_the_source():
    from core.version import APP_NAME, UPSTREAM_NAME
    assert APP_NAME == "Faci3D"
    shown = i18n.tr("About IngeTrazo")
    assert UPSTREAM_NAME not in shown and APP_NAME in shown
    # A remembered shortcut is keyed by the English source, as before.
    assert i18n.source_of(shown) == "About IngeTrazo"


def test_the_about_box_credits_ingetrazo():
    from views.about_dialog import AboutDialog
    from PySide6.QtWidgets import QLabel
    dlg = AboutDialog(None, "0.0")
    text = " ".join(lab.text() for lab in dlg.findChildren(QLabel))
    assert "Faci3D" in dlg.windowTitle()
    assert "IngeTrazo" in text and "Marco Sumari Tellez" in text
    dlg.deleteLater()


def test_faci3d_versions_itself_but_extensions_measure_the_engine():
    from core import extension_manager as manager
    from core.version import ENGINE_VERSION, __version__
    assert __version__ == "0.1.0"
    assert ENGINE_VERSION == "0.5.8"
    base = manager.bundled_extensions()
    assert base, "the bundled extensions are listed"
    ext = base[0]
    # An extension written for IngeTrazo 0.5 still fits: compatibility is
    # measured against the engine, not against Faci3D's 0.1.0.
    fits = manager.Extension(**{**ext.__dict__, "minimum_version": "0.5.0"})
    assert manager.compatible_with_current(fits)
    too_new = manager.Extension(**{**ext.__dict__, "minimum_version": "9.0"})
    assert not manager.compatible_with_current(too_new)
