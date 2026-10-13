# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Solid colours only: image textures become the colour they look like.

Faci3D models for 3D printing, where a face's paint is a filament colour,
never a picture. Documents and imports may still arrive textured (a .skp, a
COLLADA, an old .igz), so whatever comes in is flattened here: every
``attrs["texture"]`` is dropped and the face keeps the AVERAGE colour of the
image it showed — the same colour the "Shaded" style already drew it in, so
the model reads the same, just without the picture.

The format readers stay untouched (they still parse textures faithfully);
the app calls :func:`flatten_textures` on the scene once a file is loaded.
Face-me billboards (2D people, trees) are pictures by nature and are left
alone, as are reference image planes, which are not paint.
"""
from __future__ import annotations

#: The colour a texture whose image cannot be read turns into.
FALLBACK_RGB = (0.78, 0.78, 0.78)


def average_color(path, cache={}) -> tuple[float, float, float] | None:
    """The mean RGB (floats 0–1) of the image at ``path``, or ``None`` when
    it cannot be read. Transparent pixels do not count. Cached per path."""
    key = str(path)
    if key in cache:
        return cache[key]
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QImageReader
    limit = QImageReader.allocationLimit()
    QImageReader.setAllocationLimit(0)
    try:
        img = QImage(key)
    finally:
        QImageReader.setAllocationLimit(limit)
    rgb = None
    if not img.isNull():
        small = img.scaled(16, 16, Qt.IgnoreAspectRatio,
                           Qt.SmoothTransformation)
        rs = gs = bs = n = 0
        for yy in range(small.height()):
            for xx in range(small.width()):
                px = small.pixelColor(xx, yy)
                if px.alpha() < 32:
                    continue
                rs += px.red()
                gs += px.green()
                bs += px.blue()
                n += 1
        if n:
            rgb = (rs / (255.0 * n), gs / (255.0 * n), bs / (255.0 * n))
    cache[key] = rgb
    return rgb


def _texture_color(tex: dict, fallback) -> tuple[float, float, float]:
    rgb = average_color(tex["path"]) if tex.get("path") else None
    if rgb is None and tex.get("tint"):
        rgb = tuple(float(c) for c in tex["tint"][:3])
    if rgb is None and fallback is not None:
        rgb = tuple(float(c) for c in tuple(fallback)[:3])
    return rgb or FALLBACK_RGB


def flatten_paint(paint) -> bool:
    """Turn the texture of one paint dict (face attrs, a group's material,
    a face's own back side) into a colour, in place. Returns whether
    anything changed."""
    if not isinstance(paint, dict):
        return False
    changed = False
    tex = paint.get("texture")
    if tex:
        paint["color"] = _texture_color(tex, paint.get("color"))
        changed = True
    if "texture" in paint:
        del paint["texture"]
    if flatten_paint(paint.get("back")):
        changed = True
    return changed


def flatten_textures(scene) -> int:
    """Flatten every texture in ``scene`` — loose geometry, groups and
    components (nested and kept ones included), group paint and the named
    material registry. Returns how many paints changed."""
    from core.purge import _document_groups, iter_groups
    count = 0
    meshes = [scene.loose_mesh]
    for g in iter_groups(_document_groups(scene)):
        if getattr(g, "billboard", False):
            continue
        if flatten_paint(getattr(g, "material", None)):
            count += 1
        meshes.append(g.mesh)
    seen: set[int] = set()
    for mesh in meshes:
        if mesh is None or id(mesh) in seen:
            continue
        seen.add(id(mesh))
        for f in mesh.faces:
            if flatten_paint(f.attrs):
                count += 1
    for mat in (getattr(scene, "materials", None) or {}).values():
        if mat.texture:
            mat.color = _texture_color(mat.texture, mat.color)
            mat.texture = None
            count += 1
    if count:
        scene.version += 1
    return count
