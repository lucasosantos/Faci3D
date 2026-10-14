# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The status bar's per-hover texts settle a few times a second, not on
every mouse move (Marco's plaza, 2026-09-14: every setText flushed the
whole window's backing store — frames p90 190 ms live, 57 ms frozen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def test_measurement_texts_are_coalesced():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        calls = []
        real = win._on_measurement
        win._on_measurement = lambda t: (calls.append(t), real(t))
        for i in range(50):
            win.viewport.measurementChanged.emit(f"{i} m")
        assert calls == []                              # nothing yet: pending
        assert win._status_timer.isActive()
        win._flush_status_texts()
        assert calls == ["49 m"]                        # one update, the latest
        assert win._vcb_live == "49 m"
        win.viewport.measurementChanged.emit("49 m")    # unchanged text…
        win._flush_status_texts()
        assert calls == ["49 m"]                        # …no repaint
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
