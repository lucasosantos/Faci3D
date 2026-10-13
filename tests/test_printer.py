# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The printer's build volume and the bed geometry (core.printer)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from core import printer as P


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "printer.ini"), QSettings.IniFormat)


def test_the_bed_is_centred_on_the_origin_on_the_ground():
    bed = P.Printer("x", 220, 200, 250)
    lo, hi = bed.bounds()
    assert lo == pytest.approx((-0.11, -0.10, 0.0))
    assert hi == pytest.approx((0.11, 0.10, 0.25))


def test_choosing_a_printer_is_optional(settings):
    assert P.load(settings) is None
    P.save(P.DEFAULT, settings)
    assert P.load(settings) == P.DEFAULT
    P.save(None, settings)
    assert P.load(settings) is None


def test_a_printer_round_trips_through_the_settings(settings):
    mine = P.Printer(P.CUSTOM, 300, 280, 320)
    P.save(mine, settings)
    assert P.load(settings) == mine


def test_absurd_sizes_are_clamped(settings):
    P.save(P.DEFAULT, settings)
    settings.setValue("printer/width", "-5")
    settings.setValue("printer/depth", "nan")
    settings.setValue("printer/height", "1e9")
    got = P.load(settings)
    assert got.width == 10.0
    assert got.depth == P.DEFAULT.depth
    assert got.height == 2000.0


def test_the_bed_can_be_hidden(settings):
    assert P.bed_shown(settings)
    P.set_bed_shown(False, settings)
    assert not P.bed_shown(settings)


def test_plate_grid_and_volume_geometry():
    bed = P.Printer("x", 40, 20, 30)
    assert len(P.plate_triangles(bed)) == 6 * 3
    assert all(z == 0.0 for z in P.plate_triangles(bed)[2::3])
    grid = P.grid_lines(bed)
    # x = -20..20 every 10 → 5 lines; y = -10..10 → 3 lines; 2 points each.
    assert len(grid) == (5 + 3) * 2 * 3
    assert len(P.volume_edges(bed)) == 12 * 2 * 3


def test_drop_sets_the_bottom_on_the_plate_and_nothing_else():
    assert P.drop_delta((1, 2, 0.05), (3, 4, 0.2)) == (0.0, 0.0, -0.05)
    assert P.drop_delta((1, 2, -0.01), (3, 4, 0.2)) == (0.0, 0.0, 0.01)


def test_centre_also_centres_on_the_plate():
    assert P.centre_delta((0.1, 0.2, 0.05), (0.3, 0.4, 0.2)) == \
        pytest.approx((-0.2, -0.3, -0.05))


def test_fits_compares_sizes_not_positions():
    bed = P.Printer("x", 100, 100, 100)
    assert P.fits(bed, (5.0, 5.0, 5.0), (5.1, 5.1, 5.1))
    assert not P.fits(bed, (0, 0, 0), (0.101, 0.05, 0.05))
