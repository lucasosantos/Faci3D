# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Solid colours only: whatever arrives textured is painted the colour its
image looked like (core.flat_paint)."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QImage, QVector3D

from core.flat_paint import FALLBACK_RGB, flatten_textures
from core.group import Group
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


def _png(path, argb: int):
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(argb)
    img.save(str(path), "PNG")
    return str(path)


def _square(mesh, x0=0.0):
    return mesh.add_face([V(x0, 0), V(x0 + 1, 0), V(x0 + 1, 1), V(x0, 1)])


def test_a_textured_face_takes_the_colour_of_its_image(tmp_path):
    red = _png(tmp_path / "red.png", 0xFFFF0000)
    scene = Scene()
    f = _square(scene.mesh)
    f.attrs["texture"] = {"path": red, "sw": 1.0, "sh": 1.0}
    f.attrs["mat"] = "Brick"
    assert flatten_textures(scene) == 1
    assert "texture" not in f.attrs
    assert f.attrs["color"] == pytest.approx((1.0, 0.0, 0.0), abs=0.01)
    assert f.attrs["mat"] == "Brick"            # the name survives


def test_the_back_side_and_a_groups_paint_flatten_too(tmp_path):
    blue = _png(tmp_path / "blue.png", 0xFF0000FF)
    scene = Scene()
    f = _square(scene.mesh)
    f.attrs["back"] = {"texture": {"path": blue, "sw": 1, "sh": 1}}
    g = Group(Mesh())
    _square(g.mesh, 3.0)
    g.material = {"texture": {"path": blue, "sw": 1, "sh": 1}}
    scene.groups.append(g)
    flatten_textures(scene)
    assert f.attrs["back"]["color"] == pytest.approx((0, 0, 1), abs=0.01)
    assert "texture" not in f.attrs["back"]
    assert g.material["color"] == pytest.approx((0, 0, 1), abs=0.01)


def test_the_registry_drops_its_images(tmp_path):
    green = _png(tmp_path / "green.png", 0xFF00FF00)
    scene = Scene()
    scene.materials["Grass"] = Material(
        "Grass", texture={"path": green, "sw": 1, "sh": 1})
    flatten_textures(scene)
    mat = scene.materials["Grass"]
    assert mat.texture is None
    assert mat.color == pytest.approx((0, 1, 0), abs=0.01)


def test_an_unreadable_image_falls_back_to_tint_colour_then_grey(tmp_path):
    scene = Scene()
    tinted = _square(scene.mesh)
    tinted.attrs["texture"] = {"path": str(tmp_path / "gone.png"),
                               "tint": [0.2, 0.4, 0.6]}
    coloured = _square(scene.mesh, 2.0)
    coloured.attrs["texture"] = {"path": str(tmp_path / "gone.png")}
    coloured.attrs["color"] = (0.1, 0.1, 0.1)
    bare = _square(scene.mesh, 4.0)
    bare.attrs["texture"] = {"path": str(tmp_path / "gone.png")}
    flatten_textures(scene)
    assert tinted.attrs["color"] == pytest.approx((0.2, 0.4, 0.6))
    assert coloured.attrs["color"] == pytest.approx((0.1, 0.1, 0.1))
    assert bare.attrs["color"] == FALLBACK_RGB


def test_transparent_pixels_do_not_darken_the_colour(tmp_path):
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(0x00000000)
    for x in range(4):
        img.setPixel(x, 0, 0xFFFFFF00)
    path = tmp_path / "sprite.png"
    img.save(str(path), "PNG")
    scene = Scene()
    f = _square(scene.mesh)
    f.attrs["texture"] = {"path": str(path)}
    flatten_textures(scene)
    assert f.attrs["color"] == pytest.approx((1, 1, 0), abs=0.02)


def test_billboards_keep_their_picture(tmp_path):
    person = _png(tmp_path / "person.png", 0xFF808080)
    scene = Scene()
    g = Group(Mesh())
    f = _square(g.mesh)
    f.attrs["texture"] = {"path": person}
    g.billboard = True
    scene.groups.append(g)
    assert flatten_textures(scene) == 0
    assert f.attrs["texture"]["path"] == person


def test_a_plain_model_is_left_alone():
    scene = Scene()
    f = _square(scene.mesh)
    f.attrs["color"] = (0.5, 0.5, 0.5)
    version = scene.version
    assert flatten_textures(scene) == 0
    assert scene.version == version
