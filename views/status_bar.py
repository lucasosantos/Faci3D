# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The main window's status bar: one standing hint for the tool and its
step, timed messages that give it back when they expire, and menu
descriptions shown while a menu entry is hovered."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QSizePolicy, QStatusBar, QWidget


class _ElidedLabel(QLabel):
    """A label that never asks for room: a plain QLabel's minimum width is
    its whole text, and the standing hint of the main window is a long
    line — as a permanent widget it made the window impossible to shrink
    or maximise onto a smaller screen (Marco, 2026-09-07: «no puedo
    maximizar la ventana»). This one reports no minimum and elides."""

    def __init__(self, parent=None) -> None:
        super().__init__("", parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.setTextInteractionFlags(Qt.NoTextInteraction)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = str(text or "")
        self._relayout()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        fm = QFontMetrics(self.font())
        shown = fm.elidedText(self._full, Qt.ElideRight, max(self.width() - 4, 0))
        super().setText(shown)
        # Cut short, the whole line is one hover away (Marco, 23-09).
        self.setToolTip(self._full if shown != self._full else "")


class StatusBar(QStatusBar):
    """A status bar whose messages go to a label of its own, so the hint
    shares the row with the measurements box and never hides it.

    ``showMessage(text)`` (no timeout) sets the standing text; a timed
    message replaces it for a while and then the standing text comes back
    — a plain QStatusBar leaves the bar empty after a timed message."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self._msg = _ElidedLabel(self)
        self._base = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._restore)
        # Permanent widgets: the message label with all the stretch, so
        # whatever the window adds later (tool, the VCB, the zoom combo)
        # lines up on the right.
        self.addPermanentWidget(self._msg, 10)
        # An empty filler takes what the capped message leaves, so the
        # message stays glued to the LEFT (without it the
        # bar's own leading spacer pushed them toward the middle — Marco,
        # 2026-09-15: «debería estar alineado a la izquierda»).
        self._filler = QWidget(self)
        self.addPermanentWidget(self._filler, 1)
        # A menu entry's description (its status tip) reaches the bar
        # through Qt's C++ showMessage, which never calls the override
        # below: it went to QStatusBar's own message area, hidden behind
        # our widgets, so hovering a menu showed nothing (0.5.7, #213).
        # Qt still announces it, and the announcement goes to our label.
        self.messageChanged.connect(self._on_qt_message)

    #: The message never takes more than this share of the bar, so the
    #: right end stays clear for the coordinates and the VCB (Marco,
    #: 2026-09-15: «que no llegue hasta el otro extremo derecho»). It was
    #: half; the tool's name moved into the hint (23-09) and freed its own
    #: label, and the hint, now longer by that name, gets that room.
    MESSAGE_SHARE = 0.6

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._msg.setMaximumWidth(max(120, int(self.width() * self.MESSAGE_SHARE)))

    # ---- messages, routed to our label ---------------------------------------
    def showMessage(self, text: str, timeout: int = 0) -> None:  # noqa: N802
        text = str(text or "")
        if timeout and timeout > 0:
            self._msg.setText(text)
            self._timer.start(int(timeout))
        else:
            self._timer.stop()
            self._base = text
            self._msg.setText(text)

    def clearMessage(self) -> None:  # noqa: N802
        self._timer.stop()
        self._msg.setText(self._base)

    def currentMessage(self) -> str:  # noqa: N802
        return self._msg.text()

    def _restore(self) -> None:
        self._msg.setText(self._base)

    def _on_qt_message(self, text: str) -> None:
        """A status tip (a menu entry being hovered) while it lasts; the
        standing text again when it clears."""
        if text:
            self._timer.stop()
            self._msg.setText(text)
        else:
            self._msg.setText(self._base)
