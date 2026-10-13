# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The 3D printer a Faci3D model is made for: its build volume, and where
that volume sits in the model.

Choosing a printer is optional: with none, Faci3D models on the plain
ground and "place on the bed" means "on the ground, at the origin".

The bed is centred on the model's origin, on the ground plane (z = 0): the
red and green axes cross in the middle of the plate and the blue one rises
through the build volume. Sizes are kept in millimetres, the unit every
printer is sold in; the model itself is in metres, so the geometry below
converts (1 mm = 0.001).

No Qt widgets here — the dialog and the viewport read this module.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Metres per millimetre.
MM = 0.001


@dataclass(frozen=True)
class Printer:
    """A build volume in millimetres: ``width`` along X (red), ``depth``
    along Y (green), ``height`` along Z (blue)."""

    name: str
    width: float
    depth: float
    height: float

    def bounds(self) -> tuple[tuple[float, float, float],
                              tuple[float, float, float]]:
        """``(min, max)`` corners of the build volume, in metres."""
        w, d, h = self.width * MM, self.depth * MM, self.height * MM
        return (-w / 2, -d / 2, 0.0), (w / 2, d / 2, h)


#: Common printers, in the order the dialog lists them. The first is the
#: one the dialog offers when none was chosen yet: the most widespread bed
#: size on hobby printers.
PRESETS = (
    Printer("Creality Ender 3 / V2 / S1", 220, 220, 250),
    Printer("Creality K1 / K1C", 220, 220, 250),
    Printer("Prusa MK4 / MK3S", 250, 210, 220),
    Printer("Prusa MINI", 180, 180, 180),
    Printer("Bambu Lab A1", 256, 256, 256),
    Printer("Bambu Lab A1 mini", 180, 180, 180),
    Printer("Bambu Lab P1S / X1C", 256, 256, 256),
    Printer("Anycubic Kobra 2", 220, 220, 250),
    Printer("Elegoo Neptune 4", 225, 225, 265),
)
DEFAULT = PRESETS[0]
#: The name a printer with hand-typed sizes is saved under.
CUSTOM = "Custom"

_KEY = "printer/"
_LIMIT = (10.0, 2000.0)          # sane build sizes, mm


def _clamp(value, fallback: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    if v != v:                   # NaN
        return fallback
    return max(_LIMIT[0], min(_LIMIT[1], v))


#: What the start view frames when no printer is chosen: a part-sized
#: working area, millimetres, not an architect's 20 m.
WORK_AREA = Printer("", 200, 200, 200)


def load(settings=None) -> Printer | None:
    """The printer chosen in the settings, or ``None`` — choosing one is
    optional."""
    if settings is None:
        from PySide6.QtCore import QSettings
        settings = QSettings()
    if not settings.contains(_KEY + "width"):
        return None
    return Printer(
        str(settings.value(_KEY + "name", CUSTOM) or CUSTOM),
        _clamp(settings.value(_KEY + "width"), DEFAULT.width),
        _clamp(settings.value(_KEY + "depth"), DEFAULT.depth),
        _clamp(settings.value(_KEY + "height"), DEFAULT.height))


def save(printer: Printer | None, settings=None) -> None:
    """Remember ``printer``; ``None`` forgets the choice."""
    if settings is None:
        from PySide6.QtCore import QSettings
        settings = QSettings()
    if printer is None:
        for key in ("name", "width", "depth", "height"):
            settings.remove(_KEY + key)
        return
    settings.setValue(_KEY + "name", printer.name)
    settings.setValue(_KEY + "width", float(printer.width))
    settings.setValue(_KEY + "depth", float(printer.depth))
    settings.setValue(_KEY + "height", float(printer.height))


def bed_shown(settings=None) -> bool:
    if settings is None:
        from PySide6.QtCore import QSettings
        settings = QSettings()
    return str(settings.value(_KEY + "show_bed", "1")) != "0"


def set_bed_shown(shown: bool, settings=None) -> None:
    if settings is None:
        from PySide6.QtCore import QSettings
        settings = QSettings()
    settings.setValue(_KEY + "show_bed", "1" if shown else "0")


# ---- Geometry (metres, flat float lists for GL) -----------------------------

def plate_triangles(printer: Printer) -> list[float]:
    """The bed plate as two triangles at z = 0."""
    (x0, y0, _), (x1, y1, _) = printer.bounds()
    return [x0, y0, 0.0, x1, y0, 0.0, x1, y1, 0.0,
            x0, y0, 0.0, x1, y1, 0.0, x0, y1, 0.0]


def grid_lines(printer: Printer, step_mm: float = 10.0) -> list[float]:
    """Grid lines on the plate every ``step_mm``, from the centre out so the
    lines through the origin always exist (the axes run along them)."""
    (x0, y0, _), (x1, y1, _) = printer.bounds()
    step = step_mm * MM
    out: list[float] = []

    def ticks(lo, hi):
        n = int(hi / step + 1e-9)
        return [k * step for k in range(-n, n + 1) if lo <= k * step <= hi]

    for x in ticks(x0, x1):
        out += [x, y0, 0.0, x, y1, 0.0]
    for y in ticks(y0, y1):
        out += [x0, y, 0.0, x1, y, 0.0]
    return out


def volume_edges(printer: Printer) -> list[float]:
    """The twelve edges of the build volume as line segments."""
    (x0, y0, z0), (x1, y1, z1) = printer.bounds()
    c = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    out: list[float] = []
    for i in range(8):
        for bit in (1, 2, 4):
            j = i | bit
            if j != i:
                out += [*c[i], *c[j]]
    return out


# ---- Placing on the bed -----------------------------------------------------

def drop_delta(lo, hi) -> tuple[float, float, float]:
    """The move that sets a box with corners ``lo``/``hi`` (x, y, z
    sequences, metres) down on the plate: its bottom to z = 0, nothing
    else changed."""
    return (0.0, 0.0, -float(lo[2]))


def centre_delta(lo, hi) -> tuple[float, float, float]:
    """The move that centres a box on the plate AND sets it down on it."""
    cx = (float(lo[0]) + float(hi[0])) / 2.0
    cy = (float(lo[1]) + float(hi[1])) / 2.0
    return (-cx, -cy, -float(lo[2]))


def fits(printer: Printer, lo, hi, tol: float = 1e-6) -> bool:
    """Whether a box of the size ``hi - lo`` fits the build volume (in any
    position — placing it is :func:`centre_delta`'s job)."""
    size = [float(hi[i]) - float(lo[i]) for i in range(3)]
    room = (printer.width * MM, printer.depth * MM, printer.height * MM)
    return all(s <= r + tol for s, r in zip(size, room))
