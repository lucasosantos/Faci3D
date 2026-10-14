# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Display styles: presets, persistence, scene binding."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from core.scene import Scene
from core.style import BUILTIN_STYLES, FACE_MODES, Style

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def test_style_roundtrip_and_defaults():
    s = Style()
    assert s.face_mode == "textures" and s.edges and s.profiles and s.sky
    again = Style.from_dict(s.to_dict())
    assert again.to_dict() == s.to_dict()
    assert Style.from_dict({"face_mode": "no_such_mode"}).face_mode == "textures"
    c = s.copy()
    c.edges = False
    assert s.edges is True                     # copies never alias


def test_builtin_presets_cover_the_classics():
    names = {p.name for p in BUILTIN_STYLES}
    assert {"Default", "Shaded", "Hidden line",
            "Monochrome", "Wireframe", "X-ray"} <= names
    for p in BUILTIN_STYLES:
        assert p.face_mode in FACE_MODES
    hidden = next(p for p in BUILTIN_STYLES if p.name == "Hidden line")
    assert hidden.face_mode == "hidden_line"
    assert hidden.background == (1.0, 1.0, 1.0) and not hidden.sky


def test_scene_carries_a_style_and_clear_resets_it():
    scene = Scene()
    assert scene.display_style.face_mode == "textures"
    scene.display_style = Style(name="Hidden line", face_mode="hidden_line")
    scene.mesh.add_edge(_v(0, 0), _v(1, 0))    # so clear() has work to do
    scene.clear()
    assert scene.display_style.face_mode == "textures"


def test_igz_roundtrip_keeps_the_style(tmp_path):
    from formats import igz as igz_format
    scene = Scene()
    scene.mesh.add_edge(_v(0, 0), _v(1, 0))
    scene.display_style = Style(name="Monochrome", face_mode="monochrome",
                                background=(1.0, 1.0, 1.0), sky=False)
    path = tmp_path / "estilo.igz"
    igz_format.save_scene(scene, path)

    fresh = Scene()
    igz_format.load_into(fresh, path)
    assert fresh.display_style.name == "Monochrome"
    assert fresh.display_style.face_mode == "monochrome"
    assert fresh.display_style.sky is False

    # A default style stays implicit — old readers see the same terse file.
    scene2 = Scene()
    scene2.mesh.add_edge(_v(0, 0), _v(1, 0))
    igz_format.save_scene(scene2, path)
    fresh2 = Scene()
    igz_format.load_into(fresh2, path)
    assert fresh2.display_style.to_dict() == Style().to_dict()



def test_style_by_name_returns_copies():
    from core.style import style_by_name
    a = style_by_name("Hidden line")
    assert a is not None and a.face_mode == "hidden_line"
    assert a.background == (1.0, 1.0, 1.0) and a.sky is False
    a.edges = False
    b = style_by_name("Hidden line")
    assert b.edges is True                     # presets stay pristine
    assert style_by_name("No existe") is None



def _v(x, y, z=0.0):
    from PySide6.QtGui import QVector3D
    return QVector3D(x, y, z)
