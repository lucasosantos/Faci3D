# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Draw Faci3D's scale figure: a potted plant, on a transparent background.

A new Faci3D document starts with it beside the origin, 150 mm tall — the
size of something you would print, where IngeTrazo's 1.70 m engineer would
dwarf every part. Drawn here rather than shipped from elsewhere, so the
image is original work under the project's licence.

    python scripts/gen_plant_pot.py   →  resources/components/plant_pot.png
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage,
                           QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resources" / "components" / "plant_pot.png"
W, H = 560, 840                     # aspect 2:3


def _leaf(p: QPainter, base: QPointF, angle_deg: float, length: float,
          width: float, light: QColor, dark: QColor) -> None:
    """A lance-shaped leaf from ``base``, pointing ``angle_deg`` (0 = up),
    with a lighter midrib and a soft gradient across it."""
    p.save()
    p.translate(base)
    p.rotate(angle_deg)
    path = QPainterPath(QPointF(0, 0))
    path.cubicTo(QPointF(width, -length * 0.25), QPointF(width * 0.8,
                 -length * 0.75), QPointF(0, -length))
    path.cubicTo(QPointF(-width * 0.8, -length * 0.75),
                 QPointF(-width, -length * 0.25), QPointF(0, 0))
    grad = QLinearGradient(QPointF(-width, 0), QPointF(width, 0))
    grad.setColorAt(0.0, dark)
    grad.setColorAt(0.55, light)
    grad.setColorAt(1.0, dark)
    p.setBrush(QBrush(grad))
    p.setPen(QPen(dark.darker(140), 3.0))
    p.drawPath(path)
    rib = QPen(light.lighter(135), 2.4)
    rib.setCapStyle(Qt.RoundCap)
    p.setPen(rib)
    p.drawLine(QPointF(0, -length * 0.06), QPointF(0, -length * 0.9))
    p.restore()


def draw() -> QImage:
    img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    rnd = random.Random(7)

    # ---- The pot: a terracotta frustum with a rim, standing on the bottom.
    cx = W / 2
    top_y, rim_h, bottom_y = 470.0, 52.0, H - 6.0
    top_half, bottom_half = 175.0, 125.0
    body = QPainterPath(QPointF(cx - top_half + 14, top_y + rim_h))
    body.lineTo(cx + top_half - 14, top_y + rim_h)
    body.lineTo(cx + bottom_half, bottom_y - 14)
    body.quadTo(QPointF(cx + bottom_half, bottom_y),
                QPointF(cx + bottom_half - 14, bottom_y))
    body.lineTo(cx - bottom_half + 14, bottom_y)
    body.quadTo(QPointF(cx - bottom_half, bottom_y),
                QPointF(cx - bottom_half, bottom_y - 14))
    body.closeSubpath()
    terracotta = QColor(196, 104, 62)
    grad = QLinearGradient(QPointF(cx - top_half, 0), QPointF(cx + top_half, 0))
    grad.setColorAt(0.0, terracotta.darker(150))
    grad.setColorAt(0.35, terracotta.lighter(115))
    grad.setColorAt(0.7, terracotta)
    grad.setColorAt(1.0, terracotta.darker(170))
    outline = QPen(QColor(92, 44, 24), 4.0)
    outline.setJoinStyle(Qt.RoundJoin)
    p.setPen(outline)
    p.setBrush(QBrush(grad))
    p.drawPath(body)

    # ---- The plant, drawn before the rim so the rim overlaps the stems.
    soil = QRadialGradient(QPointF(cx, top_y + 10), top_half)
    soil.setColorAt(0.0, QColor(92, 64, 44))
    soil.setColorAt(1.0, QColor(52, 36, 26))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(soil))
    p.drawEllipse(QRectF(cx - top_half + 18, top_y - 16, 2 * (top_half - 18),
                         40))
    greens = [(QColor(104, 170, 72), QColor(40, 96, 40)),
              (QColor(126, 190, 84), QColor(52, 112, 46)),
              (QColor(88, 150, 64), QColor(32, 80, 34))]
    base = QPointF(cx, top_y + 4)
    # Back leaves first (darker, shorter), then the front fan.
    for i in range(9):
        a = -60 + i * 15 + rnd.uniform(-5, 5)
        light, dark = greens[2]
        _leaf(p, base + QPointF(rnd.uniform(-30, 30), 0), a,
              rnd.uniform(220, 280), rnd.uniform(34, 44), light, dark)
    for i in range(11):
        a = -55 + i * 11 + rnd.uniform(-4, 4)
        light, dark = greens[i % 2]
        length = 420 - abs(a) * 2.6 + rnd.uniform(-15, 15)
        _leaf(p, base + QPointF(rnd.uniform(-30, 30), 6), a, length,
              rnd.uniform(38, 50), light, dark)

    # ---- The rim, in front of the stems.
    rim = QRectF(cx - top_half, top_y, 2 * top_half, rim_h)
    rgrad = QLinearGradient(rim.topLeft(), rim.topRight())
    rgrad.setColorAt(0.0, terracotta.darker(140))
    rgrad.setColorAt(0.35, terracotta.lighter(125))
    rgrad.setColorAt(1.0, terracotta.darker(160))
    p.setPen(outline)
    p.setBrush(QBrush(rgrad))
    p.drawRoundedRect(rim, 10, 10)
    # A soft highlight down the pot's lit side.
    shine = QPen(QColor(255, 220, 190, 90), 10.0)
    shine.setCapStyle(Qt.RoundCap)
    p.setPen(shine)
    x0 = cx - top_half * 0.45
    p.drawLine(QPointF(x0, top_y + rim_h + 24),
               QPointF(x0 + (top_half - bottom_half) * 0.45 * 0.9,
                       bottom_y - 40))
    p.end()
    return img


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    img = draw()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ok = img.save(str(OUT), "PNG")
    print(("wrote " if ok else "FAILED ") + str(OUT))
    del app
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
