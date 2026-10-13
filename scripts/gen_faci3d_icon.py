# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Build every application icon from the Faci3D logo.

The logo (``resources/branding/faci3d_logo.png``) is the cube mark above the
word "Faci3d" on a near-black ground. The icon is the cube alone, on a
rounded tile of that same ground — it reads on light and dark panels alike,
where the cube's grey faces alone would vanish against a dark taskbar.

Writes, keeping the file names the packaging already points at:

    resources/icons/ingetrazo_master.png      1024 px
    resources/icons/ingetrazo_<n>.png         16 … 512 (window/taskbar icon)
    resources/icons/ingetrazo.ico             Windows (PNG entries, 16–256)
    resources/icons/ingetrazo.icns            macOS (PNG entries, 128–1024)
    resources/icons/ingetrazo.svg             scalable icon (wraps the PNG)

Qt only, no Inkscape or ImageMagick:  python scripts/gen_faci3d_icon.py
"""
from __future__ import annotations

import base64
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, QRectF, Qt
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient,
                           QPainter, QPainterPath)

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "resources" / "branding" / "faci3d_logo.png"
ICONS = ROOT / "resources" / "icons"
SIZES = (16, 32, 48, 64, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
#: The cube in the 1254 px logo: centred on (626, 446), 468 px tall.
CUBE = QRect(356, 176, 540, 540)
MASTER = 1024


def master() -> QImage:
    logo = QImage(str(LOGO))
    if logo.isNull():
        raise SystemExit(f"cannot read {LOGO}")
    s = logo.width() / 1254.0              # the crop was measured at 1254 px
    crop = logo.copy(QRect(int(CUBE.x() * s), int(CUBE.y() * s),
                           int(CUBE.width() * s), int(CUBE.height() * s)))
    img = QImage(MASTER, MASTER, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    tile = QRectF(24, 24, MASTER - 48, MASTER - 48)
    path = QPainterPath()
    path.addRoundedRect(tile, MASTER * 0.2, MASTER * 0.2)
    p.setClipPath(path)
    ground = QLinearGradient(tile.topLeft(), tile.bottomRight())
    ground.setColorAt(0.0, QColor(18, 20, 28))
    ground.setColorAt(1.0, QColor(9, 9, 14))
    p.fillPath(path, ground)
    inner = int(MASTER * 0.9)
    off = (MASTER - inner) // 2
    p.drawImage(QRect(off, off, inner, inner), crop)
    p.setClipping(False)
    p.end()
    return img


def _png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data)


def _scaled(img: QImage, size: int) -> QImage:
    return img.scaled(size, size, Qt.IgnoreAspectRatio,
                      Qt.SmoothTransformation)


def write_ico(img: QImage, path: Path) -> None:
    """A multi-size .ico whose entries are PNGs (Windows Vista and later)."""
    blobs = [_png_bytes(_scaled(img, n)) for n in ICO_SIZES]
    out = bytearray(struct.pack("<HHH", 0, 1, len(blobs)))
    offset = 6 + 16 * len(blobs)
    for n, blob in zip(ICO_SIZES, blobs):
        dim = 0 if n >= 256 else n
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob),
                           offset)
        offset += len(blob)
    for blob in blobs:
        out += blob
    path.write_bytes(bytes(out))


def write_icns(img: QImage, path: Path) -> None:
    """A .icns with PNG entries: ic07 128, ic08 256, ic09 512, ic10 1024."""
    body = bytearray()
    for code, n in ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512),
                    (b"ic10", 1024)):
        blob = _png_bytes(_scaled(img, n))
        body += code + struct.pack(">I", 8 + len(blob)) + blob
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + bytes(body))


def write_svg(img: QImage, path: Path) -> None:
    b64 = base64.b64encode(_png_bytes(_scaled(img, 512))).decode("ascii")
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" width="512" '
        'height="512" viewBox="0 0 512 512">\n'
        f'  <image width="512" height="512" '
        f'xlink:href="data:image/png;base64,{b64}"/>\n</svg>\n',
        encoding="ascii")


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    img = master()
    img.save(str(ICONS / "ingetrazo_master.png"), "PNG")
    for n in SIZES:
        _scaled(img, n).save(str(ICONS / f"ingetrazo_{n}.png"), "PNG")
    write_ico(img, ICONS / "ingetrazo.ico")
    write_icns(img, ICONS / "ingetrazo.icns")
    write_svg(img, ICONS / "ingetrazo.svg")
    print("wrote the Faci3D icons in", ICONS)
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
