# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SVG import (formats/svg_in.py): flat faces on the ground, at real size,
holes where the drawing has holes, ready for Push/Pull."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D

from core.history import History, SnapshotImport
from core.scene import Scene
from formats import svg_in


def _svg(tmp_path, body, attrs='width="100mm" height="100mm" '
                                'viewBox="0 0 100 100"', name="a.svg"):
    p = tmp_path / name
    p.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" {attrs}>'
                 f'{body}</svg>', encoding="utf-8")
    return p


def _import(tmp_path, body, scale=1.0, **kw):
    scene = Scene()
    hist = History(scene)
    drawing = svg_in.parse_svg(_svg(tmp_path, body, **kw), scale=scale)
    stats = {}
    hist.execute(SnapshotImport(
        lambda s: stats.update(r=svg_in.add_to_scene(s, drawing, scale))))
    return scene, hist, stats["r"]


def _bbox_mm(scene):
    lo, hi = scene.bounds()
    return ((hi.x() - lo.x()) * 1000, (hi.y() - lo.y()) * 1000,
            (lo.x() + hi.x()) * 500, (lo.y() + hi.y()) * 500)


# ---- Parsing ----------------------------------------------------------------

def test_transforms_compose_in_order():
    m = svg_in.parse_transform("translate(10,0) scale(2)")
    assert svg_in._apply(m, 1, 1) == pytest.approx((12, 2))
    r = svg_in.parse_transform("rotate(90 5 5)")
    assert svg_in._apply(r, 10, 5) == pytest.approx((5, 10))


def test_arc_flags_written_together_are_read(tmp_path):
    # "a5 5 0 105 5": flags 1 and 0 glued to the 5 that follows.
    d = svg_in.parse_svg(_svg(tmp_path,
                              '<path d="M10 10a5 5 0 105 5z"/>'))
    assert len(d.contours) == 1 and d.contours[0].closed


def test_units_and_viewbox_give_millimetres(tmp_path):
    # 50 user units in a 100-unit viewBox shown 20 mm wide → 10 mm.
    d = svg_in.parse_svg(_svg(
        tmp_path, '<rect x="0" y="0" width="50" height="50"/>',
        attrs='width="20mm" height="20mm" viewBox="0 0 100 100"'))
    assert d.size() == pytest.approx((10, 10))
    # No units: CSS pixels, 96 to the inch.
    d = svg_in.parse_svg(_svg(tmp_path, '<rect width="96" height="48"/>',
                              attrs=""))
    assert d.size() == pytest.approx((25.4, 12.7))


def test_hidden_and_text_are_left_out(tmp_path):
    d = svg_in.parse_svg(_svg(
        tmp_path, '<rect width="10" height="10"/>'
                  '<rect x="20" width="10" height="10" style="display:none"/>'
                  '<defs><rect id="r" width="5" height="5"/></defs>'
                  '<text>hi</text>'))
    assert len(d.contours) == 1
    assert d.skipped == {"text": 1}


def test_use_places_a_definition(tmp_path):
    d = svg_in.parse_svg(_svg(
        tmp_path, '<defs><rect id="r" width="5" height="5"/></defs>'
                  '<use href="#r" x="10"/><use href="#r" x="30"/>'))
    assert len(d.contours) == 2


def test_only_text_is_reported(tmp_path):
    with pytest.raises(svg_in.SvgError):
        svg_in.parse_svg(_svg(tmp_path, '<text>Faci3D</text>'))


def test_not_an_svg(tmp_path):
    p = tmp_path / "x.svg"
    p.write_text("<html/>", encoding="utf-8")
    with pytest.raises(svg_in.SvgError):
        svg_in.parse_svg(p)


def test_curves_stay_within_tolerance(tmp_path):
    d = svg_in.parse_svg(_svg(tmp_path, '<circle cx="50" cy="50" r="40"/>'))
    (c,) = d.contours
    for x, y in c.points:
        assert math.hypot(x - 50, y + 50) == pytest.approx(40, abs=0.06)
    assert all(c.curved)


# ---- Into the model -----------------------------------------------------------

def test_a_plate_with_a_hole_is_one_face_with_a_hole(tmp_path):
    scene, hist, st = _import(
        tmp_path, '<rect x="10" y="10" width="80" height="60"/>'
                  '<circle cx="50" cy="40" r="10"/>')
    assert st.faces == 1
    (face,) = scene.mesh.faces
    assert len(face.holes) == 1
    assert face.normal().z() == pytest.approx(1.0)       # looks up
    w, h, cx, cy = _bbox_mm(scene)
    assert (w, h) == pytest.approx((80, 60), abs=1e-3)
    assert (cx, cy) == pytest.approx((0, 0), abs=1e-3)   # centred
    assert all(v.position.z() == 0 for v in scene.mesh.vertices)
    assert hist.undo() and not scene.mesh.faces


def test_an_o_keeps_its_counter_open_and_its_dot_filled(tmp_path):
    # An "O" (outer + counter in one path) and a dot inside the counter.
    body = ('<path d="M10 10 H90 V90 H10 Z M30 30 V70 H70 V30 Z"/>'
            '<rect x="45" y="45" width="10" height="10"/>')
    scene, _h, st = _import(tmp_path, body)
    assert st.faces == 2
    ring = max(scene.mesh.faces, key=lambda f: f.area())
    assert len(ring.holes) == 1


def test_open_paths_come_in_as_edges(tmp_path):
    scene, _h, st = _import(tmp_path, '<polyline points="0,0 10,0 10,10"/>')
    assert st.faces == 0 and st.edges == 2
    assert len(scene.mesh.edges) == 2


def test_the_size_can_be_changed_on_import(tmp_path):
    scene, _h, st = _import(tmp_path, '<rect width="40" height="20"/>',
                            scale=2.5)
    w, h, _cx, _cy = _bbox_mm(scene)
    assert (w, h) == pytest.approx((100, 50), abs=1e-3)
    assert st.size_mm == pytest.approx((100, 50))


def test_lands_beside_loose_geometry_instead_of_welding_into_it(tmp_path):
    scene = Scene()
    scene.mesh.add_face([QVector3D(-0.01, -0.01, 0), QVector3D(0.01, -0.01, 0),
                         QVector3D(0.01, 0.01, 0), QVector3D(-0.01, 0.01, 0)])
    drawing = svg_in.parse_svg(_svg(tmp_path, '<rect width="20" height="20"/>'))
    svg_in.add_to_scene(scene, drawing)
    new = [f for f in scene.mesh.faces
           if min(v.x() for v in f.vertices) > 0.0105]
    assert len(new) == 1                                  # 10 mm to the right


def test_push_pull_turns_the_import_into_a_closed_solid(tmp_path):
    from core.solids import solid_report
    from tools.pushpull import PushPullTool
    scene, hist, _st = _import(
        tmp_path, '<rect x="10" y="10" width="80" height="60"/>'
                  '<circle cx="50" cy="40" r="10"/>')
    face = scene.mesh.faces[0]

    class _VP:
        def __init__(self):
            self.scene, self.history = scene, hist

        def update(self):
            pass

        def set_hover(self, entity):
            pass

        def set_suppressed_faces(self, faces):
            pass

    t = PushPullTool()
    t.base_face = face
    t.extrusion = 0.005                                    # 5 mm up
    t.dragging = True
    t._anchor = face.centroid()
    t._normal = face.normal()
    t._attached, t._prism_cap = t._classify_base(scene)
    t._cap_positions = t._cap_loop_positions(face)
    t._commit(_VP())
    ok, vol = solid_report(scene.mesh)
    assert ok
    plate = 0.08 * 0.06 * 0.005
    hole = math.pi * 0.01 ** 2 * 0.005
    assert vol == pytest.approx(plate - hole, rel=0.01)


# ---- File ▸ Import ▸ SVG (views/svg_import.py) -------------------------------

@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def test_the_import_arrives_selected_in_one_undo(win, tmp_path):
    from views.svg_import import import_svg_path
    p = _svg(tmp_path, '<rect width="30" height="20"/>'
                       '<text>left out</text>')
    before = set(win.viewport.scene.mesh.faces)
    assert import_svg_path(win, p, scale=1.0)
    new = set(win.viewport.scene.mesh.faces) - before
    assert len(new) == 1
    assert set(win.viewport.scene.selection) == new
    assert "a.svg" in win.statusBar().currentMessage()
    assert win.viewport.history.undo()
    assert set(win.viewport.scene.mesh.faces) == before
    assert not win.viewport.scene.selection & new          # nothing stale


def test_a_broken_file_is_reported_not_raised(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from views.svg_import import import_svg_path
    seen = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: seen.append(a[2])))
    p = tmp_path / "bad.svg"
    p.write_text("<svg", encoding="utf-8")
    assert not import_svg_path(win, p, scale=1.0)
    assert seen


def test_the_size_dialog_keeps_the_proportion():
    from views.svg_import import SvgSizeDialog
    dlg = SvgSizeDialog(None, 40.0, 20.0, "logo.svg")
    dlg.width.setValue(100.0)
    assert dlg.height.value() == pytest.approx(50.0)
    dlg.height.setValue(10.0)
    assert dlg.width.value() == pytest.approx(20.0)
    assert dlg.scale() == pytest.approx(0.5)
    dlg.deleteLater()


def test_the_import_menu_offers_svg(win):
    from core.i18n import tr
    file_menu = win.menuBar().actions()[0].menu()
    imp = next(a.menu() for a in file_menu.actions()
               if a.menu() is not None and a.text() == tr("Import"))
    assert tr("SVG drawing (.svg)…") in [a.text() for a in imp.actions()]
