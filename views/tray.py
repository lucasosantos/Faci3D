# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Right-side dockable tray, built from QDockWidget.

Holds collapsible sections:
- **Materiales** — a palette of colour + texture swatches ("En el modelo" and a
  bundled "Biblioteca"). Clicking a swatch makes it the active Paint material
  and switches to the Paint tool. ``+ Textura…`` adds an image with a tile size.
- **Estilo de cota** — precision, unit, font size and colour of dimensions,
  applied live to ``scene.dimension_style``.
- **Info de entidad** — read-only facts about the current selection (face area,
  edge length, dimension value, material).

A ``QDockWidget`` gives docking/floating/closing for free; the sections are a
vertical stack of lightweight collapsibles inside a scroll area.
"""
from __future__ import annotations

from views import prompts as _prompts

import os
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QGridLayout,
    QLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from views.color_dialog import get_color
from core.i18n import tr
from views.theme import style as theme_style
from core.mesh import Edge, Face
from core.group import Group
from core.dimension import Dimension
from core.textlabel import TextLabel
from tools.paint import RECENT_MAX, PaintTool

from core.paths import app_root
from core.units import fmt_area, fmt_len, fmt_volume

#: RAL Classic — the paint standard a drawing can be specified in. Its names
#: are the standard's own, in the standard's own languages, so they live in
#: the data file beside the colour instead of in the UI translations, where
#: "Beige" or "Cream" would collide with strings that mean something else.
_RAL_FILE = app_root() / "resources" / "colors" / "ral.json"
_SWATCH = 44  # swatch pixel size


def _ral_name(entry: dict) -> str:
    """The RAL name in the language the app is running in."""
    from core.i18n import current_language
    if current_language().startswith("es") and entry.get("name_es"):
        return entry["name_es"]
    return entry["name"]


class _Section(QWidget):
    """A collapsible section: a header button that toggles its content."""

    def __init__(self, title: str, content: QWidget) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._btn = QToolButton()
        self._btn.setText(f"  {title}")
        self._btn.setCheckable(True)
        self._btn.setChecked(True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn.setArrowType(Qt.DownArrow)
        # Clean, light header (QGIS-style): plain bold title on the panel
        # background with a subtle underline — no dark bar. Uses palette() roles
        # so it adapts to light and dark themes.
        self._btn.setStyleSheet(
            "QToolButton { font-weight: bold; padding: 6px 4px; border: none;"
            " border-bottom: 1px solid palette(mid); text-align: left; }"
            "QToolButton:hover { background: palette(midlight); }")
        self._btn.toggled.connect(self._on_toggle)
        self._content = content
        lay.addWidget(self._btn)
        lay.addWidget(content)
        # Open or folded, as the user left it last time (a user in Brazil,
        # 25-09: «sempre que eu abro o software ele vem aberta… deve vir como
        # eu deixei»). Keyed by the panel's class, not its title: the title
        # changes with the language.
        self._key = f"tray/collapsed/{type(content).__name__}"
        from PySide6.QtCore import QSettings
        if str(QSettings().value(self._key, "0")) == "1":
            self._btn.setChecked(False)

    def _on_toggle(self, on: bool) -> None:
        self._content.setVisible(on)
        self._btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        key = getattr(self, "_key", None)
        if key is not None:
            from PySide6.QtCore import QSettings
            QSettings().setValue(key, "0" if on else "1")


def style_slider(slider) -> None:
    """A slider whose track reads on any theme. The platform style draws
    the groove in a shade of the window colour, which on macOS's dark
    appearance is black on near-black — the slider looked like a bare
    knob floating in the tray. The track is lifted off the background, the
    part up to the knob wears the highlight colour, and the knob is light
    with a highlight rim, on light and dark themes alike."""
    pal = slider.palette()
    dark = pal.window().color().lightness() < 128
    groove = "#9aa1ad" if dark else "#b9bec7"
    knob = "#e8eaee" if dark else "#ffffff"
    hi = pal.highlight().color().name()
    slider.setStyleSheet(
        "QSlider::groove:horizontal {"
        f" height: 6px; background: {groove}; border-radius: 3px; }}"
        "QSlider::sub-page:horizontal {"
        f" height: 6px; background: {hi}; border-radius: 3px; }}"
        "QSlider::handle:horizontal {"
        f" background: {knob}; border: 1px solid {hi};"
        " width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }")
    slider.setMinimumHeight(20)


def fit_rows(view, min_rows: int = 3, max_rows: int | None = None) -> None:
    """Grow a list / tree to show ALL its rows — no scroll bar of its own,
    so the only scrolling in a tray is the tray's (Marco, 2026-09-14: «no
    me gusta hacer scroll dentro del scroll»). Call after every refill;
    ``min_rows`` keeps an empty list from collapsing to a sliver.

    ``max_rows`` caps that: past it the view stops growing and scrolls on
    its own — for the lists that get long, Layers and Components in the
    model (issue #55, @pacaeiro: «should have their own vertical scroll
    bar»). Short lists keep the no-nested-scroll rule."""
    from PySide6.QtWidgets import QAbstractItemView, QTreeView
    model = view.model()
    rows = model.rowCount() if model is not None else 0
    capped = max_rows is not None and rows > max_rows
    view.setVerticalScrollBarPolicy(
        Qt.ScrollBarAsNeeded if capped else Qt.ScrollBarAlwaysOff)
    view.setSizePolicy(view.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
    if capped:
        rows = max_rows
    if isinstance(view, QTreeView):
        row_h = view.sizeHintForRow(0) if rows else 0
        header = view.header().height() if not view.header().isHidden() else 0
    else:
        row_h = view.sizeHintForRow(0) if rows else 0
        header = 0
    if row_h <= 0:
        row_h = view.fontMetrics().height() + 8
    h = header + max(rows, min_rows) * row_h + 2 * view.frameWidth() + 2
    view.setFixedHeight(h)


def _color_pixmap(rgb, size=_SWATCH) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor.fromRgbF(*rgb))
    return pm


def _default_pixmap(size=_SWATCH) -> QPixmap:
    """The «Default» material swatch: the front's cream and the
    back's blue-grey split on the diagonal."""
    from PySide6.QtGui import QPainter, QPolygonF
    from PySide6.QtCore import QPointF
    pm = QPixmap(size, size)
    pm.fill(QColor.fromRgbF(0.96, 0.95, 0.925))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(164, 176, 196))
    p.drawPolygon(QPolygonF([QPointF(size, 0), QPointF(size, size),
                             QPointF(0, size)]))
    p.end()
    return pm


def _swatch_button(pm: QPixmap, tip: str) -> QToolButton:
    b = QToolButton()
    b.setIcon(QIcon(pm))
    b.setIconSize(QSize(_SWATCH, _SWATCH))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    return b


class FlowLayout(QLayout):
    """A grid that REFLOWS with the width: swatches and component buttons
    fill as many columns as fit and wrap, so a widened tray shows more per
    row instead of a blank right half (Marco, 2026-09-15: «cuando
    redimensiono la barra debería ocupar ese espacio con más columnas»).
    Qt's classic flow layout; ``addWidget`` also accepts and ignores the
    ``row, col`` the grid callers used to pass."""

    def __init__(self, parent=None, spacing: int = 2) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # ---- QLayout interface ---------------------------------------------------
    def addItem(self, item) -> None:            # noqa: N802 — Qt override
        self._items.append(item)

    def addWidget(self, w, *_grid_pos) -> None:  # noqa: N802 — Qt override
        super().addWidget(w)

    def setColumnStretch(self, *_a) -> None:     # noqa: N802 — grid compat
        pass

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):               # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):               # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):              # noqa: N802
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:        # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect) -> None:        # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):                         # noqa: N802
        return self.minimumSize()

    def minimumSize(self):                      # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def columns_at(self, width: int) -> int:
        """How many items the first row holds at ``width`` (for tests)."""
        m = self.contentsMargins()
        x = m.left()
        cols = 0
        for item in self._items:
            w = item.sizeHint().width()
            if cols and x + w > width - m.right():
                break
            x += w + self._spacing
            cols += 1
        return cols

    def _do_layout(self, rect, test_only: bool) -> int:
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        right = rect.right() - m.right()
        row_h = 0
        for item in self._items:
            hint = item.sizeHint()
            if row_h and x + hint.width() - 1 > right:
                x = rect.x() + m.left()
                y += row_h + self._spacing
                row_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_h = max(row_h, hint.height())
        return y + row_h + m.bottom() - rect.y()



class ComponentsPanel(QWidget):
    """Components tray: a grid of clickable thumbnails.

    The thumbnails are STATIC images — the 2D people are their own PNGs and
    the 3D starters ship pre-rendered PNGs in ``resources/components/thumbs``
    (regenerate with the dev script if the models change) — so showing the
    panel costs a handful of pixmap loads and never touches the GL renderer."""

    COLS = 3
    #: Rows from which the «In model» list offers its name filter.
    FILTER_FROM = 8

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtGui import QIcon
        self._window = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        grid = FlowLayout(spacing=4)
        res = app_root() / "resources" / "components"
        import json as _json
        items = []
        # The 2D people are data too: resources/components/people.json lists
        # key/name/tip and the REAL height each one stands, which is the whole
        # point of a scale figure — <key>.png is the cutout, cropped tight so
        # the height it is given is the height it reads.
        people = res / "people.json"
        if people.exists():
            for entry in _json.loads(people.read_text(encoding="utf-8")):
                items.append(
                    (res / f"{entry['key']}.png", tr(entry["name"]),
                     tr(entry.get("tip", entry["name"])),
                     lambda _c=False, k=entry["key"], h=entry["height"],
                     n=entry["name"]:
                         window._on_insert_person_2d(f"{k}.png", h, n)))
        # The 3D starters are data: resources/components/components.json
        # lists key/name/tip; the model is <key>.glb (Sketchfab CC-BY set,
        # see SOURCES.md) with a pre-rendered thumbs/<key>.png.
        manifest = res / "components.json"
        if manifest.exists():
            for entry in _json.loads(manifest.read_text(encoding="utf-8")):
                items.append(
                    (res / "thumbs" / f"{entry['key']}.png",
                     tr(entry["name"]), tr(entry.get("tip", entry["name"])),
                     lambda _c=False, k=entry["key"], n=entry["name"]:
                         window._on_insert_component(k, tr(n))))
        for i, (icon_path, label, tip, callback) in enumerate(items):
            btn = QToolButton()
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setIcon(QIcon(str(icon_path)))
            btn.setIconSize(QSize(56, 56))
            btn.setText(label)
            btn.setToolTip(tip)
            btn.setAutoRaise(True)
            btn.setMinimumWidth(72)
            btn.clicked.connect(callback)
            grid.addWidget(btn, i // self.COLS, i % self.COLS)
        lay.addLayout(grid)
        # The bundled grid is a handful; the rest of the catalogue lives
        # online and is browsed from here (see core/library.py).
        more = QPushButton(tr("More components…"))
        more.setToolTip(tr(
            "Browse the online library and download a model as a component"))
        more.clicked.connect(window._on_open_library)
        lay.addWidget(more)
        custom = QPushButton(tr("Face-me image (PNG)…"))
        custom.setToolTip(tr(
            "Insert your own cutout PNG at real height, always facing "
            "the camera"))
        custom.clicked.connect(window._on_insert_faceme_image)
        lay.addWidget(custom)

        # "In model": what THIS drawing contains, the way a components
        # tray usually lists it. The grid above is a library to insert
        # from; it says nothing about what you already have, which is what
        # you actually look for when you want to find or re-place a piece.
        lay.addWidget(QLabel(f"<b>{tr('In model')}</b>"))
        # A long list is searched by name rather than scrolled (the list
        # «can get quite big», PR #4 review). Only shown once it is long.
        self._in_model_filter = QLineEdit()
        self._in_model_filter.setPlaceholderText(tr("Filter by name…"))
        self._in_model_filter.setClearButtonEnabled(True)
        self._in_model_filter.textChanged.connect(self._apply_in_model_filter)
        lay.addWidget(self._in_model_filter)
        self._in_model = QListWidget()
        self._in_model.setToolTip(tr(
            "Components placed in this drawing — click one to select its "
            "copies"))
        self._in_model.itemClicked.connect(self._select_component)
        # Each row shows what the component looks like
        # (views/component_thumbs.py), not only its name.
        from views.component_thumbs import SIZE as _THUMB
        self._in_model.setIconSize(QSize(_THUMB, _THUMB))
        # Right-click a row: the same two moves the viewport's menu offers,
        # from the list — which is where a long one is searched anyway.
        self._in_model.setContextMenuPolicy(Qt.CustomContextMenu)
        self._in_model.customContextMenuRequested.connect(
            self._in_model_menu)
        lay.addWidget(self._in_model)
        # The definitions of another document, kept here unplaced: a
        # library drawn from a file of one's own.
        from_file = QPushButton(tr("Components from File…"))
        from_file.setToolTip(tr(
            "Add the components of another IngeTrazo document to this "
            "list, kept in the file and ready to place or swap in"))
        from_file.clicked.connect(window._on_components_from_file)
        lay.addWidget(from_file)
        self.refresh_in_model()

    def _components_in_model(self) -> list:
        """``[(name, faces, [groups], template)]`` per distinct prototype,
        most copies first. Instances share their prototype mesh, so identity
        groups them — no geometry is walked. ``template`` is the definition
        kept in the file (``None`` when it is not kept); a kept one with no
        copy placed is a row too, with an empty list."""
        from core.kept_components import kept_template
        scene = self._window.viewport.scene
        by_proto: dict = {}
        for g in scene.groups:
            if not g.is_component() or getattr(g, "billboard", False):
                continue
            by_proto.setdefault(id(g.mesh), []).append(g)
        rows = [(gs[0].name, len(gs[0].mesh.faces), gs,
                 kept_template(scene, gs[0].mesh))
                for gs in by_proto.values()]
        rows += [(t.name, len(t.mesh.faces), [], t)
                 for t in getattr(scene, "kept_components", None) or ()
                 if id(t.mesh) not in by_proto]
        rows.sort(key=lambda r: (-len(r[2]), (r[0] or "").lower()))
        return rows

    def on_scene_changed(self) -> None:
        """The tray's per-change call. The «In model» list reads every
        definition's signature (its faces and paint) to know whether its
        thumbnail changed: on the Plaza that was +20 ms on every edit, its
        section folded or its tab hidden (release_check, 09-10). Refreshed
        now when on screen, on showing otherwise — like the Browser. A
        window not shown yet (scripts, tests) refreshes at once, as before."""
        if not self._window.isVisible():
            self.refresh_in_model()
            return
        if not self.isVisible():
            if not getattr(self, "_in_model_stale", False):
                # Its rows hold the groups they list: kept while it waits,
                # they held a whole previous document in memory after
                # Open (+130 MB on the Plaza, release_check 10-10).
                self._in_model.clear()
            self._in_model_stale = True
            return
        # On screen: one refresh 300 ms after the last edit, as Materials
        # does — a burst of edits (arrows, repeated pushes) pays it once.
        timer = getattr(self, "_in_model_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer
            timer = self._in_model_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self.refresh_in_model)
        timer.start(300)

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if getattr(self, "_in_model_stale", False):
            self._in_model_stale = False
            self.refresh_in_model()

    def refresh_in_model(self) -> None:
        from views.component_thumbs import thumbnail
        self._in_model.clear()
        for name, faces, gs, kept in self._components_in_model():
            copies = len(gs)
            label = f"{name}  ({copies}×, {faces} " + tr("Faces").lower() + ")"
            if kept is not None:
                label += "  · " + tr("kept")
            item = QListWidgetItem(label)
            item.setIcon(QIcon(thumbnail(gs[0] if gs else kept)))
            item.setData(Qt.UserRole, gs)
            item.setData(Qt.UserRole + 1, kept)
            self._in_model.addItem(item)
        if self._in_model.count() == 0:
            self._in_model.addItem(QListWidgetItem(tr("No components yet")))
        self._in_model_filter.setVisible(
            self._in_model.count() >= self.FILTER_FROM
            or bool(self._in_model_filter.text()))
        self._apply_in_model_filter()

    def _apply_in_model_filter(self, _text=None) -> None:
        """Hide the rows whose name does not hold the filter text (any
        case, accents as typed). The list keeps its rows; only their
        visibility changes, so a refresh does not lose the filter."""
        needle = self._in_model_filter.text().strip().casefold()
        for i in range(self._in_model.count()):
            item = self._in_model.item(i)
            groups = item.data(Qt.UserRole) or []
            kept = item.data(Qt.UserRole + 1)
            definition = groups[0] if groups else kept
            name = (definition.name or "") if definition is not None else ""
            item.setHidden(bool(needle) and definition is not None
                           and needle not in name.casefold())
        fit_rows(self._in_model, max_rows=12)

    def _select_component(self, item) -> None:
        groups = item.data(Qt.UserRole)
        if groups:
            self._select_groups(groups)

    def _in_model_actions(self, groups, kept=None) -> list:
        """``[(text, callback, checked, tip)]`` for a row of the «In model»
        list — its right-click menu, kept apart so it can be read without
        opening one. ``callback`` None = shown greyed; ``checked`` None =
        not a check entry; ``tip`` None = no tooltip."""
        from core.kept_components import make_template, place_copy
        definition = kept if kept is not None else groups[0]
        swap = [g for g in self._window.viewport.scene.selection
                if isinstance(g, Group) and g.is_component()
                and g.mesh is not definition.mesh]
        out = [(tr("Select Instances ({n})", n=len(groups)),
                (lambda: self._select_groups(groups)) if groups else None,
                None, None)]
        if swap:
            out.append((tr("Replace {n} Selected with This", n=len(swap)),
                        lambda: self._window.replace_selection_with(
                            definition), None, None))
        else:
            out.append((tr("Replace Selection with This"), None, None,
                        tr("Select the instances of another component in "
                           "the model first")))
        out.append((tr("Place a Copy"),
                    lambda: self._window._start_place(place_copy(
                        kept if kept is not None
                        else make_template(definition))), None, None))
        out.append((tr("Keep in File"),
                    lambda: self._window.keep_component(
                        definition, kept is None), kept is not None,
                    tr("Keep this definition in the file even with no copy "
                       "placed, to place it or swap copies for it later")))
        out.append((tr("Rename…"),
                    lambda: self._window.rename_component(definition),
                    None, tr("Renames every copy of this component")))
        return out

    def _in_model_menu(self, pos) -> None:
        item = self._in_model.itemAt(pos)
        if item is None:
            return
        groups = item.data(Qt.UserRole) or []
        kept = item.data(Qt.UserRole + 1)
        if not groups and kept is None:
            return                          # «No components yet»
        menu = QMenu(self._in_model)
        menu.setToolTipsVisible(True)
        for text, callback, checked, tip in self._in_model_actions(
                groups, kept):
            act = menu.addAction(text)
            if checked is not None:
                act.setCheckable(True)
                act.setChecked(checked)
            if tip:
                act.setToolTip(tip)
            if callback is None:
                act.setEnabled(False)
            else:
                act.triggered.connect(lambda _c=False, cb=callback: cb())
        menu.exec(self._in_model.viewport().mapToGlobal(pos))

    def _select_groups(self, groups) -> None:
        scene = self._window.viewport.scene
        scene.selection.clear()
        scene.selection.update(groups)
        scene.bump_view()
        self._window.viewport.update()
        self._window.statusBar().showMessage(
            tr("{n} entities selected", n=len(groups)), 2500)


class PartsPanel(QWidget):
    """The parts of the selected component — an outliner, one level
    deep, measured like a cut list.

    Select a component made of parts (an imported model, or one regrouped
    with Split into Pieces) and every part is a row: its name, the material
    most of it wears and its size as length × width × thickness. Clicking a
    row opens the component and selects that part, as double-clicking into
    it would; the check shows or hides it; the name edits in place. Copy
    cut list puts the parts on the clipboard as a table, identical parts
    counted once with their quantity."""

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QPushButton,
                                       QTreeWidget, QVBoxLayout)
        self._window = window
        self._updating = False
        self._container = None
        self._rows: list = []
        self._cache: dict = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        self._title = QLabel()
        self._title.setWordWrap(True)
        lay.addWidget(self._title)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([tr("Name"), tr("Size"), tr("Material")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 110)
        self.tree.setColumnWidth(1, 130)
        self.tree.setToolTip(tr(
            "Click a part to select it inside the component; the check "
            "shows or hides it. To rename: double-click the name, press F2, "
            "or right-click ▸ Rename"))
        from PySide6.QtWidgets import QAbstractItemView
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked
                                  | QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.SelectedClicked)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self._items: list = []          # one per part, in the tree's order
        self._shown_selection: tuple = ()
        # «All parts visible»: checked when none is hidden, partial when
        # some are — a click shows every part (or hides them all when all
        # already show).
        self._all_visible = QCheckBox(tr("All parts visible"))
        self._all_visible.setTristate(True)
        self._all_visible.clicked.connect(self._on_all_visible)
        lay.addWidget(self._all_visible)
        lay.addWidget(self.tree)
        row = QHBoxLayout()
        self._split_btn = QPushButton(tr("Split into Pieces"))
        self._split_btn.setToolTip(tr(
            "Regroup the component by the solids that do not touch"))
        self._split_btn.clicked.connect(self._on_split)
        self._copy_btn = QPushButton(tr("Copy cut list"))
        self._copy_btn.setToolTip(tr(
            "Copy the parts as a table (quantity, parts, material, length, "
            "width, thickness) — pastes into a spreadsheet"))
        self._copy_btn.clicked.connect(self._on_copy)
        row.addWidget(self._split_btn)
        row.addStretch(1)
        row.addWidget(self._copy_btn)
        lay.addLayout(row)
        self._by_material, by_material_row = _wrapping_check(
            tr("Count identical parts only when the material matches too"))
        self._by_material.setChecked(True)
        lay.addWidget(by_material_row)

        # Exploded view (core/explode.py): the parts pulled apart from the
        # assembly's centre. Dragging previews live and lands as ONE undo
        # step on release.
        from PySide6.QtWidgets import QComboBox, QSlider, QWidget as _W
        self._explode_box = _W()
        ex = QVBoxLayout(self._explode_box)
        ex.setContentsMargins(0, 6, 0, 0)
        ex.addWidget(QLabel(f"<b>{tr('Exploded view')}</b>"))
        top = QHBoxLayout()
        self._explode_mode = QComboBox()
        for key, label in (("outward", tr("Outward")),
                           ("z", tr("Along blue (up)")),
                           ("x", tr("Along red")),
                           ("y", tr("Along green"))):
            self._explode_mode.addItem(label, key)
        self._explode_mode.setToolTip(tr(
            "Which way the parts move away from the assembly's centre"))
        self._explode_mode.currentIndexChanged.connect(self._on_explode_mode)
        self._reassemble_btn = QPushButton(tr("Reassemble"))
        self._reassemble_btn.setToolTip(tr(
            "Put every part back where it sits assembled (a part you moved "
            "by hand keeps that move)"))
        self._reassemble_btn.clicked.connect(self._on_reassemble)
        top.addWidget(self._explode_mode, 1)
        top.addWidget(self._reassemble_btn)
        ex.addLayout(top)
        slide = QHBoxLayout()
        self._explode_slider = QSlider(Qt.Horizontal)
        style_slider(self._explode_slider)
        self._explode_slider.setRange(0, 300)
        self._explode_slider.setSingleStep(5)
        self._explode_slider.setPageStep(25)
        self._explode_slider.setToolTip(tr(
            "How far apart: 100% puts every part twice as far from the "
            "centre as it sits assembled"))
        self._explode_value = QLabel("0%")
        self._explode_value.setMinimumWidth(36)
        self._explode_slider.sliderPressed.connect(self._on_explode_press)
        self._explode_slider.valueChanged.connect(self._on_explode_value)
        self._explode_slider.sliderReleased.connect(self._on_explode_release)
        slide.addWidget(self._explode_slider, 1)
        slide.addWidget(self._explode_value)
        ex.addLayout(slide)
        lay.addWidget(self._explode_box)
        self._drag = None           # (container, snapshot, centres) mid-drag
        self.refresh()

    # ---- Model → view --------------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def container(self):
        """The component whose parts are listed: the one selected, or the
        one open for editing while you work among its parts."""
        from core.group import Group
        scene = self._scene()
        groups = [g for g in scene.selection if isinstance(g, Group)]
        if len(groups) == 1 and groups[0].children:
            return groups[0]
        edit = scene.edit_group
        if edit is not None and getattr(edit, "children", None):
            return edit
        if len(groups) == 1:
            return groups[0]            # a plain group: offer Split
        return None

    def _row(self, part) -> dict:
        """``part``'s row, measured once per version of its geometry — a
        tray refresh follows every edit, and a part is only re-measured
        when it itself changed."""
        from core.group import iter_placements
        from core.parts import part_rows
        sig = tuple(
            (id(g.mesh), getattr(g.mesh, "_mut_serial", 0),
             tuple(m.data()) if m is not None else None,
             id(getattr(g, "material", None)))
            for g, m in iter_placements(part))
        hit = self._cache.get(id(part))
        if hit is not None and hit[0] == sig:
            row = hit[1]
        else:
            holder = type("_Holder", (), {})()
            holder.children = [part]
            row = part_rows(holder)[0]
            self._cache[id(part)] = (sig, row)
        row = dict(row)
        row["name"] = part.name
        row["hidden"] = bool(getattr(part, "hidden", False))
        return row

    def refresh(self) -> None:
        """Bring the list up to date — IN PLACE when the component and its
        parts are the ones already listed. Rebuilding on every change threw
        the list back to its top after each click (a part below the
        fourteenth row scrolled out from under the pointer) and killed a
        rename half-typed; only a different component, or a different set
        of parts, rebuilds."""
        from PySide6.QtWidgets import QAbstractItemView, QTreeWidgetItem
        from core.parts import is_surface
        from core.units import fmt_len_fine, fmt_triple
        if self.tree.state() == QAbstractItemView.EditingState:
            return                      # a rename in progress: leave it be
        self._updating = True
        cont = self._container = self.container()
        kids = list(getattr(cont, "children", None) or ())
        alive = {id(k) for k in kids}
        for key in [k for k in self._cache if k not in alive]:
            del self._cache[key]
        self._rows = [self._row(k) for k in kids]
        listed = [it.data(0, Qt.UserRole) for it in self._items]
        if len(listed) != len(kids) or any(a is not b
                                           for a, b in zip(listed, kids)):
            self.tree.clear()
            self._items = []
            self._shown_selection = ()
            for row in self._rows:
                item = QTreeWidgetItem(["", "", ""])
                item.setData(0, Qt.UserRole, row["part"])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable
                              | Qt.ItemIsEditable)
                self.tree.addTopLevelItem(item)
                self._items.append(item)
        for item, row in zip(self._items, self._rows):
            if is_surface(row["size"]):
                # No thickness: a skin, a decal, a pane drawn as one plane.
                # Kept — it is what the model shows — but not read as a
                # board with a thickness of 0.
                length, width = row["size"][:2]
                size = tr("{area} — surface", area=(
                    f"{fmt_len_fine(length)} × {fmt_len_fine(width)}"))
                item.setToolTip(1, tr(
                    "No thickness: a surface drawn as a single plane (a "
                    "skin, a decal, a glass pane). It stays in the model; "
                    "the cut list marks it as a surface."))
            else:
                size = fmt_triple(*row["size"], fine=True)
                item.setToolTip(1, "")
            for col, text in enumerate((row["name"], size, row["material"])):
                if item.text(col) != text:
                    item.setText(col, text)
            state = Qt.Unchecked if row["hidden"] else Qt.Checked
            if item.checkState(0) != state:
                item.setCheckState(0, state)
            item.setToolTip(0, tr("{n} faces", n=row["faces"]))
        self._sync_selection()
        hidden = sum(1 for r in self._rows if r["hidden"])
        self._all_visible.setCheckState(
            Qt.Checked if hidden == 0 else
            Qt.Unchecked if hidden == len(self._rows) else Qt.PartiallyChecked)
        self._all_visible.setVisible(bool(kids))
        if cont is None:
            self._title.setText(tr(
                "Select a component to see its parts."))
        elif not kids:
            self._title.setText(tr(
                "«{name}» is one piece. Split into Pieces finds the solids "
                "inside it that do not touch.", name=cont.name))
        else:
            self._title.setText(tr("<b>{name}</b> — {n} parts",
                                   name=cont.name, n=len(kids)))
        self.tree.setVisible(bool(kids))
        self._explode_box.setVisible(len(kids) > 1)
        state = getattr(cont, "exploded", None) or {}
        if self._drag is None:
            self._explode_slider.blockSignals(True)
            self._explode_slider.setValue(
                int(round(100 * float(state.get("factor", 0.0)))))
            self._explode_slider.blockSignals(False)
            self._explode_value.setText(f"{self._explode_slider.value()}%")
            i = self._explode_mode.findData(state.get("mode", "outward"))
            self._explode_mode.blockSignals(True)
            self._explode_mode.setCurrentIndex(max(i, 0))
            self._explode_mode.blockSignals(False)
        self._reassemble_btn.setEnabled(bool(state))
        self._copy_btn.setEnabled(bool(kids))
        self._by_material.parentWidget().setVisible(bool(kids))
        self._split_btn.setEnabled(cont is not None
                                   and not getattr(cont, "billboard", False))
        fit_rows(self.tree, max_rows=14)
        self._updating = False

    def _sync_selection(self) -> None:
        """Highlight the parts selected in the model, and — when that
        selection changed — scroll the first of them into view, so a part
        clicked in the canvas is found in the list without hunting."""
        scene = self._scene()
        chosen = tuple(id(it.data(0, Qt.UserRole)) for it in self._items
                       if it.data(0, Qt.UserRole) in scene.selection)
        self.tree.blockSignals(True)
        for it in self._items:
            want = it.data(0, Qt.UserRole) in scene.selection
            if it.isSelected() != want:
                it.setSelected(want)
        self.tree.blockSignals(False)
        if chosen and chosen != self._shown_selection:
            first = next(it for it in self._items
                         if id(it.data(0, Qt.UserRole)) == chosen[0])
            from PySide6.QtCore import QItemSelectionModel
            self.tree.setCurrentItem(first, 0, QItemSelectionModel.NoUpdate)
            self.tree.scrollToItem(first)
        self._shown_selection = chosen

    # ---- View → model --------------------------------------------------------
    def _on_all_visible(self) -> None:
        """Show every part — or, when every part already shows, hide them
        all — as one undoable step."""
        from core.history import HideCommand
        parts = [r["part"] for r in self._rows]
        hidden = [p for p in parts if p.hidden]
        if hidden:
            cmd = HideCommand(hidden, hidden=False)
        elif parts:
            cmd = HideCommand(parts, hidden=True)
        else:
            return
        self._window.viewport.history.execute(cmd)
        self._window.viewport.update()
        self.refresh()

    def _on_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item is not None:
            part = item.data(0, Qt.UserRole)
            menu.addAction(tr("Rename…"), lambda: self.tree.editItem(item, 0))
            menu.addAction(tr("Show") if part.hidden else tr("Hide"),
                           lambda: item.setCheckState(
                               0, Qt.Checked if part.hidden else Qt.Unchecked))
            menu.addSeparator()
        menu.addAction(tr("Show all parts"), self._show_all)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _show_all(self) -> None:
        from core.history import HideCommand
        hidden = [r["part"] for r in self._rows if r["part"].hidden]
        if hidden:
            self._window.viewport.history.execute(
                HideCommand(hidden, hidden=False))
            self._window.viewport.update()
            self.refresh()

    def _on_clicked(self, item, column) -> None:
        """Open the component and select the part — the Outliner's click."""
        part = item.data(0, Qt.UserRole)
        cont = self._container
        if part is None or cont is None or part.hidden:
            return
        vp = self._window.viewport
        scene = self._scene()
        # Ctrl/Shift-click picks several rows: select every one of them.
        parts = [it.data(0, Qt.UserRole) for it in self.tree.selectedItems()]
        parts = [p for p in parts if p is not None and not p.hidden] or [part]
        if scene.edit_group is not cont:
            vp.begin_group_edit(cont)
        scene.selection.clear()
        scene.selection.update(parts)
        # Clicked here, so already in view: the refresh this triggers must
        # not scroll the list under the pointer.
        self._shown_selection = tuple(
            id(it.data(0, Qt.UserRole)) for it in self._items
            if it.data(0, Qt.UserRole) in scene.selection)
        scene.bump_view()
        vp.update()

    def _on_item_changed(self, item, column) -> None:
        if self._updating:
            return
        from core.history import HideCommand, RenameGroupCommand
        part = item.data(0, Qt.UserRole)
        if part is None:
            return
        history = self._window.viewport.history
        name = item.text(0).strip()
        if name and name != part.name:
            history.execute(RenameGroupCommand(part, name))
        hide = item.checkState(0) != Qt.Checked
        if hide != bool(part.hidden):
            history.execute(HideCommand([part], hidden=hide))
        self._window.viewport.update()
        self.refresh()

    def _on_split(self) -> None:
        cont = self._container
        if cont is None:
            return
        scene = self._scene()
        if scene.edit_group is cont:
            # Split works on a closed component: step out of it, keep it
            # selected, and split that.
            self._window.viewport.end_group_edit()
        scene.selection.clear()
        scene.selection.add(cont)
        self._window._on_split_into_pieces()
        self.refresh()

    # ---- Exploded view -----------------------------------------------------
    def _explode_target(self):
        """The container the slider drives, ready for its matrix to move:
        leaving an open container first, so the parts are pulled apart in
        the component's own frame rather than a baked world copy."""
        cont = self._container
        if cont is None or len(getattr(cont, "children", None) or ()) < 2:
            return None
        scene = self._scene()
        if scene.edit_group is cont:
            self._window.viewport.end_group_edit()
            scene.selection.clear()
            scene.selection.add(cont)
        return cont

    def _mode(self) -> str:
        return self._explode_mode.currentData() or "outward"

    def _run_explode(self, factor: float) -> None:
        from core.history import ExplodeViewCommand
        cont = self._explode_target()
        if cont is None:
            return
        self._window.viewport.history.execute(
            ExplodeViewCommand(cont, factor, self._mode()))
        self._window.viewport.update()

    def _on_explode_press(self) -> None:
        from core import explode
        cont = self._explode_target()
        if cont is None:
            return
        self._drag = (cont, explode.snapshot(cont),
                      explode.assembled_centres(cont))

    def _on_explode_value(self, value: int) -> None:
        self._explode_value.setText(f"{value}%")
        if self._drag is None:
            # A click on the track or an arrow key: one step, one command.
            self._run_explode(value / 100.0)
            return
        from core import explode
        cont, _snap, centres = self._drag
        explode.apply_explode(cont, value / 100.0, self._mode(), centres)
        scene = self._scene()
        scene.version += 1
        self._window.viewport.update()

    def _on_explode_release(self) -> None:
        if self._drag is None:
            return
        from core import explode
        cont, snap, _centres = self._drag
        self._drag = None
        explode.restore(cont, snap)      # the preview was not a step…
        self._run_explode(self._explode_slider.value() / 100.0)  # …this is

    def _on_explode_mode(self, _index: int) -> None:
        cont = self._container
        if cont is not None and getattr(cont, "exploded", None):
            self._run_explode(self._explode_slider.value() / 100.0)

    def _on_reassemble(self) -> None:
        self._run_explode(0.0)

    def _on_copy(self) -> None:
        from PySide6.QtGui import QGuiApplication
        from core.parts import cut_list, cut_list_text
        from core.units import fmt_len_fine
        lines = cut_list(self._rows,
                         by_material=self._by_material.isChecked())
        text = cut_list_text(lines, fmt_len_fine, [
            tr("Qty"), tr("Parts"), tr("Material"), tr("Length"),
            tr("Width"), tr("Thickness")], surface=tr("surface"))
        QGuiApplication.clipboard().setText(text)
        self._window.viewport.flash_status(tr(
            "Cut list copied: {n} lines, {parts} parts", n=len(lines),
            parts=sum(ln["qty"] for ln in lines)), 4000)


class MaterialsPanel(QWidget):
    """Swatch palette: pick a colour to paint with."""

    COLS = 5

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)

        # Active material preview. A flow, so the Default swatch drops to a
        # second line in a narrow tray instead of widening it.
        row = FlowLayout(spacing=6)
        row.addWidget(QLabel(tr("Active:")))
        self._preview = QLabel()
        self._preview.setFixedSize(_SWATCH, _SWATCH)
        self._preview.setFrameShape(QFrame.Box)
        row.addWidget(self._preview)
        # The «Default» swatch: paints the material OFF a side.
        default_btn = _swatch_button(
            _default_pixmap(),
            tr("Default material (no material) — paint with it to remove "
               "a face's or an object's material"))
        default_btn.clicked.connect(self._apply_default)
        root.addLayout(row)

        # Change the active colour in place: a named material is edited and
        # restamped on every face that wears it; a plain colour simply
        # becomes the next one to paint.
        recolour = QPushButton(tr("Change…"))
        recolour.setToolTip(tr("Change the active colour"))
        recolour.clicked.connect(self._on_change_active)
        row.addWidget(recolour)
        row.addWidget(default_btn)

        # The last materials painted with, so texturing a model does not
        # mean hunting for the same brick in the library every time.
        self._recent_heading = self._heading(tr("Recent"))
        root.addWidget(self._recent_heading)
        self._recent_grid = FlowLayout(spacing=2)
        root.addLayout(self._recent_grid)
        if not PaintTool.recent:
            PaintTool.recent = load_recent_materials()
        self._refresh_recent()

        root.addWidget(self._heading(tr("In model")))
        self._in_model_grid = FlowLayout(spacing=2)
        root.addLayout(self._in_model_grid)

        root.addWidget(self._heading(tr("Colors")))
        self._fill_colors(root)

        btns = FlowLayout(spacing=4)         # wraps in a narrow tray
        add_color = QPushButton(tr("+ Color…"))
        add_color.clicked.connect(self._add_color)
        purge = QPushButton(tr("Purge"))
        purge.setToolTip(tr("Delete every material no face wears"))
        purge.clicked.connect(self._on_purge)
        btns.addWidget(add_color)
        btns.addWidget(purge)
        root.addLayout(btns)
        root.addStretch(1)

        self._refresh_preview()
        self.refresh_in_model()

    def _heading(self, text: str) -> QLabel:
        lbl = QLabel(text)
        theme_style(lbl, "color:{muted}; margin-top:6px; font-size:11px;")
        return lbl

    # ---- Colours ---------------------------------------------------------------
    def _fill_colors(self, root) -> None:
        """The colour palette: RAL Classic in code order — which is family
        order, yellows through blacks. RAL is a paint you can actually name,
        so a colour picked here paints as a NAMED material ("RAL 3020 Traffic
        red") that the model and its exports carry."""
        import json as _json
        ral_colors = []
        if _RAL_FILE.exists():
            data = _json.loads(_RAL_FILE.read_text(encoding="utf-8"))
            for fam in data.get("families", []):
                ral_colors.extend(fam.get("colors", []))
        grid = FlowLayout(spacing=2)
        root.addLayout(grid)
        for row, c in enumerate(ral_colors):
            label = "%s · %s" % (c["code"], _ral_name(c))
            b = _swatch_button(_color_pixmap(c["rgb"]), label)
            b.clicked.connect(
                lambda _=False, col=c: self._apply_color(
                    col["rgb"], "%s %s" % (col["code"], _ral_name(col))))
            grid.addWidget(b, row // self.COLS, row % self.COLS)

    def _on_purge(self) -> None:
        """Sweep the registry materials no face wears.

        These are invisible here — the swatches above are built from painted
        faces, not from the registry — so an import's leftovers only ever
        show up as weight in the saved ``.igz``."""
        from PySide6.QtWidgets import QMessageBox
        from core.history import PurgeUnusedCommand
        scene = self._window.viewport.scene
        cmd = PurgeUnusedCommand(layers=False, materials=True)
        _, n_mats = cmd.counts(scene)
        if not n_mats:
            QMessageBox.information(
                self, tr("Purge"), tr("Every material is in use."))
            return
        names = [n for n, _m in (cmd._materials or [])]
        preview = ", ".join(names[:12]) + ("…" if len(names) > 12 else "")
        if QMessageBox.question(
                self, tr("Purge"),
                tr("Delete {n} materials no face wears?", n=n_mats)
                + f"\n\n{preview}") != QMessageBox.Yes:
            return
        self._window.viewport.history.execute(cmd)
        self.refresh_in_model()
        self._window.statusBar().showMessage(
            tr("{n} unused materials purged", n=n_mats), 3000)

    def refresh_in_model(self) -> None:
        """Rebuild the 'En el modelo' swatches from the materials in use."""
        # Keep the tray where the user left it. The old swatches only went
        # away at the next event-loop turn (deleteLater), so for a moment
        # the grid held both sets, grew, and the scroll area jumped — the
        # library list slid by itself each time a component was made
        # (Rafael, revision 4, 02:14 and 06:20).
        from PySide6.QtWidgets import QScrollArea
        area = self.parent()
        while area is not None and not isinstance(area, QScrollArea):
            area = area.parent()
        bar = area.verticalScrollBar() if area is not None else None
        keep = bar.value() if bar is not None else None
        while self._in_model_grid.count():
            item = self._in_model_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        colors: dict = {}
        names: dict = {}     # swatch key → material name (registry identity)
        scene = self._window.viewport.scene

        def in_use():
            for face in scene.render_faces():
                yield face.attrs
            # A group's paint lives on the group, not on its faces (#133,
            # @fafecm: it only showed up here once the group was exploded).
            from core.group import iter_placements
            for top in scene.groups:
                for g, _m in iter_placements(top):
                    paint = getattr(g, "material", None)
                    if paint:
                        yield paint

        for attrs in in_use():
            mat = attrs.get("mat")
            col = attrs.get("color")
            if col is not None:
                colors[tuple(col)] = col
                if mat:
                    names.setdefault(("c", tuple(col)), mat)
        i = 0
        for col in colors.values():
            # A named material shows its NAME (the registry identity the
            # .skp import now preserves); an anonymous paint stays "Color".
            name = names.get(("c", tuple(col)))
            label = name or tr("Color")
            b = _swatch_button(_color_pixmap(tuple(col)), label)
            b.clicked.connect(lambda _=False, c=tuple(col), n=name:
                              self._apply_color(c, name=n))
            if name:
                # Slice (b): edit the material once, restamp every face
                # that wears it — right-click the swatch; and its finish
                # for the render (#181).
                b.setContextMenuPolicy(Qt.CustomContextMenu)
                b.customContextMenuRequested.connect(
                    lambda _pos, n=name, c=tuple(col), w=b:
                    self._swatch_menu(w, n, color=c))
            self._in_model_grid.addWidget(b, i // self.COLS, i % self.COLS)
            i += 1
        if bar is not None and keep is not None:
            from PySide6.QtCore import QTimer
            bar.setValue(keep)
            # …and once more after the layout settles its new height.
            QTimer.singleShot(0, lambda b=bar, v=keep: b.setValue(v))

    # ---- Apply / add --------------------------------------------------------
    def _apply_color(self, rgb, name: str | None = None) -> None:
        PaintTool.current_is_default = False
        PaintTool.current_color = tuple(rgb)
        PaintTool.current_texture = None
        PaintTool.current_opacity = None
        PaintTool.current_material = self._material_for(
            name, color=tuple(rgb))
        self._window._activate_tool("paint")
        self._refresh_preview()

    def _swatch_menu(self, button, name: str, color=None) -> None:
        """Right-click on a named material: edit its colour, and choose its
        finish for Render with Blender (#181) — «Automatic» names the finish
        it would be guessed as, so the user sees what the name already says."""
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu
        from core import finish as fin
        scene = self._window.viewport.scene
        mat = scene.materials.get(name)
        menu = QMenu(button)
        if color is not None:
            # The dialog opens once the menu has closed: a modal opened
            # inside the menu's own event loop came back without a colour.
            from PySide6.QtCore import QTimer
            menu.addAction(tr("Edit colour…"),
                           lambda: QTimer.singleShot(
                               0, lambda: self._edit_named_color(name, color)))
        if mat is not None:
            sub = menu.addMenu(tr("Finish for the render"))
            pic = (mat.texture or {}).get("path")
            guessed = fin.guess(name, pic and Path(pic).name, mat.opacity)
            auto = sub.addAction(tr("Automatic: {finish}",
                                    finish=tr(fin.LABELS[guessed])))
            auto.setCheckable(True)
            auto.setChecked(mat.finish not in fin.FINISHES)
            auto.triggered.connect(lambda: self._set_finish(name, None))
            sub.addSeparator()
            for key in fin.FINISHES:
                act = sub.addAction(tr(fin.LABELS[key]))
                act.setCheckable(True)
                act.setChecked(mat.finish == key)
                act.triggered.connect(
                    lambda _c=False, k=key: self._set_finish(name, k))
        if not menu.isEmpty():
            menu.exec(QCursor.pos())

    def _set_finish(self, name: str, finish) -> None:
        from core.finish import LABELS
        from core.history import SetMaterialFinishCommand
        self._window.viewport.history.execute(
            SetMaterialFinishCommand(name, finish))
        label = tr("Automatic") if finish is None else tr(LABELS[finish])
        self._window.statusBar().showMessage(
            tr("Finish of '{name}' for the render: {finish}", name=name,
               finish=label), 3000)

    def _edit_named_color(self, name: str, current_rgb) -> None:
        """Slice (b) of the registry track: edit a named colour material
        and restamp every face wearing it, one undoable step."""
        from core.history import RestampMaterialCommand
        from core.materials import Material
        scene = self._window.viewport.scene
        existing = scene.materials.get(name)
        base = (existing.color if existing and existing.color
                else tuple(current_rgb))
        chosen = get_color(
            QColor.fromRgbF(*base[:3]), self,
            tr("Edit material: {name}", name=name))
        if not chosen.isValid():
            return
        new_mat = Material(
            name, color=(chosen.redF(), chosen.greenF(), chosen.blueF()),
            opacity=existing.opacity if existing else None,
            finish=existing.finish if existing else None)
        self._window.viewport.history.execute(
            RestampMaterialCommand(name, new_mat))
        self._window.viewport.notify_scene_changed()
        self._window.statusBar().showMessage(
            tr("Material '{name}' updated on every face that wears it",
               name=name), 3000)

    def _material_for(self, name, color=None, texture=None, opacity=None):
        """The Material identity for the active swatch: the registry's
        entry when the name already exists (keeps its full recipe), a fresh
        one otherwise — registered lazily by the paint command itself, so
        merely CLICKING a library swatch never pollutes the registry."""
        if not name:
            return None
        from core.materials import Material
        existing = self._window.viewport.scene.materials.get(name)
        return existing or Material(name, color=color, texture=texture,
                                    opacity=opacity)

    def _on_change_active(self) -> None:
        """«Change…»: pick a new value for the active colour."""
        if PaintTool.current_is_default:
            self._add_color()
            return
        chosen = get_color(QColor.fromRgbF(*PaintTool.current_color[:3]),
                           self, tr("Color"))
        if chosen.isValid() and self._recolour_active(
                (chosen.redF(), chosen.greenF(), chosen.blueF())):
            self._refresh_preview()

    def _recolour_active(self, rgb) -> bool:
        """Give the active plain colour ``rgb``: a named material is edited
        and restamped on every face and group that wears it (one undo
        step); an anonymous colour becomes the colour to paint next.
        False when there is no colour to change."""
        if rgb is None or PaintTool.current_is_default:
            return False
        rgb = tuple(float(c) for c in rgb[:3])
        mat = PaintTool.current_material
        scene = self._window.viewport.scene
        if mat is not None and mat.name in scene.materials:
            from core.history import RestampMaterialCommand
            from core.materials import Material
            old = scene.materials[mat.name]
            new_mat = Material(mat.name, color=rgb, opacity=old.opacity,
                               finish=old.finish)
            self._window.viewport.history.execute(
                RestampMaterialCommand(mat.name, new_mat))
            self._window.viewport.notify_scene_changed()
            PaintTool.current_material = new_mat
            PaintTool.current_color = rgb
            self._window.statusBar().showMessage(
                tr("Material '{name}' updated on every face that wears it",
                   name=mat.name), 3000)
            return True
        PaintTool.current_color = rgb
        if mat is not None:
            from core.materials import Material
            PaintTool.current_material = Material(mat.name, color=rgb)
        self._window.statusBar().showMessage(
            tr("Active colour changed — click faces to paint it"), 3000)
        return True

    def _add_color(self) -> None:
        r, g, b = PaintTool.current_color
        chosen = get_color(QColor.fromRgbF(r, g, b), self, tr("Color"))
        if chosen.isValid():
            # Optional identity: a named colour becomes a registry material
            # (registered on first paint) and shows in per-material takeoffs.
            name, ok = _prompts.get_text(
                self, tr("Color"), tr("Material name (optional):"))
            self._apply_color(
                (chosen.redF(), chosen.greenF(), chosen.blueF()),
                name=name.strip() if ok and name.strip() else None)

    # ---- Recent ----------------------------------------------------------
    def recent_materials_changed(self) -> None:
        """The Paint tool painted with a material: keep it and show it."""
        save_recent_materials(PaintTool.recent)
        self._refresh_recent()

    def _refresh_recent(self) -> None:
        while self._recent_grid.count():
            w = self._recent_grid.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for entry in PaintTool.recent:
            if entry.get("texture") or not entry.get("color"):
                continue
            pm = _color_pixmap(tuple(entry["color"]))
            b = _swatch_button(pm, entry.get("mat") or tr("Color"))
            b.clicked.connect(lambda _=False, e=entry: self._apply_recent(e))
            self._recent_grid.addWidget(b)
        shown = self._recent_grid.count() > 0
        self._recent_heading.setVisible(shown)

    def _apply_recent(self, entry: dict) -> None:
        """Make a recent material the active paint, exactly as it was
        painted: its colour, translucency and name."""
        PaintTool.current_is_default = False
        PaintTool.current_texture = None
        PaintTool.current_texture_plane = None
        PaintTool.current_color = tuple(entry.get("color") or (1, 1, 1))
        PaintTool.current_opacity = entry.get("opacity")
        PaintTool.current_material = self._material_for(
            entry.get("mat"), color=PaintTool.current_color,
            opacity=entry.get("opacity"))
        self._window._activate_tool("paint")
        self._refresh_preview()

    def sync_from_paint(self) -> None:
        """Mirror what the Paint tool holds NOW — called after the
        eyedropper sampled a face, so the «Activo» swatch says what the
        next click will paint (issue #47)."""
        self._refresh_preview()

    def _apply_default(self) -> None:
        """The «Default» material: paint with it to take a side's
        material off (@pacaeiro, #47)."""
        PaintTool.current_is_default = True
        PaintTool.current_texture = None
        PaintTool.current_texture_plane = None
        PaintTool.current_opacity = None
        PaintTool.current_material = None
        self._window._activate_tool("paint")
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if PaintTool.current_is_default:
            self._preview.setPixmap(_default_pixmap())
            self._preview.setToolTip(tr("Default material (no material)"))
            return
        self._preview.setToolTip("")
        self._preview.setPixmap(_color_pixmap(PaintTool.current_color))


_RECENT_KEY = "paint/recent_materials"


def load_recent_materials() -> list[dict]:
    """The «Recent» colours saved by the last session. Textured entries
    (from before Faci3D painted in colours only) are dropped."""
    import json
    raw = QSettings().value(_RECENT_KEY) or ""
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else []
    except ValueError:
        return []
    out = []
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict) or e.get("texture") or not e.get("color"):
            continue
        out.append(e)
    return out[:RECENT_MAX]


def save_recent_materials(entries: list[dict]) -> None:
    import json
    try:
        QSettings().setValue(_RECENT_KEY, json.dumps(entries[:RECENT_MAX]))
    except (TypeError, ValueError):
        pass                       # a value JSON cannot hold: keep the old


def _dialog_parent(panel) -> QWidget:
    """Where a dialog opened from a toolbar-dropdown panel must hang: the
    main window, with the dropdown closed first. Parented to the panel, the
    modal dialog's transient parent is the menu POPUP — Wayland never maps
    it, and exec() waits forever for a window no one sees («Añadir
    localización se queda cargando», Marco on the 0.5.1 Flatpak)."""
    w = panel.parentWidget()
    while w is not None:
        if isinstance(w, QMenu):
            w.close()
            break
        w = w.parentWidget()
    return panel._window



class StylesPanel(QWidget):
    """Live editor for ``scene.display_style`` — the Styles panel.

    The top combo picks a style (built-ins + the user's saved library); the
    controls below edit the ACTIVE style in place, live — the viewport reads
    it every frame, so there is nothing to "apply". «Save style…» snapshots
    the current look under a name into the user library (QSettings), where
    ``style_by_name`` — and with it the composer's per-frame style combo —
    resolves it like any preset. Edits are not undoable, same as the
    dimension-style panel: they change how the model draws, not what it is.
    """

    #: (mode key, translatable label) — labels, not the builtin style names:
    #: "Shaded" the style is a preset bundle, "Shaded" the mode is one field.
    _MODES = (("textures", "Textures"), ("shaded", "Shaded"),
              ("hidden_line", "Hidden line"), ("monochrome", "Monochrome"),
              ("wireframe", "Wireframe"), ("xray", "X-ray"))

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._updating = False
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 6, 8, 8)

        self._combo = QComboBox()
        self._combo.activated.connect(self._on_pick)
        grid.addWidget(self._combo, 0, 0, 1, 2)

        grid.addWidget(QLabel(tr("Face mode:")), 1, 0)
        self._mode = QComboBox()
        for key, label in self._MODES:
            self._mode.addItem(tr(label), key)
        self._mode.currentIndexChanged.connect(self._apply_edits)
        grid.addWidget(self._mode, 1, 1)

        self._edges = QCheckBox(tr("Edges"))
        self._edges.toggled.connect(self._apply_edits)
        grid.addWidget(self._edges, 2, 0)
        self._edge_c = self._swatch(tr("Edge color"), "edge_color")
        grid.addWidget(self._edge_c, 2, 1)

        self._profiles = QCheckBox(tr("Profiles"))
        self._profiles.toggled.connect(self._apply_edits)
        grid.addWidget(self._profiles, 3, 0)
        self._back_edges = QCheckBox(tr("Back edges"))
        self._back_edges.setToolTip(tr(
            "Draw the edges hidden behind faces as dashed lines."))
        self._back_edges.toggled.connect(self._apply_edits)
        grid.addWidget(self._back_edges, 3, 1)

        grid.addWidget(QLabel(tr("Front color:")), 4, 0)
        self._front_c = self._swatch(
            tr("Front color — paints faces in Hidden line and Monochrome"),
            "front_color")
        grid.addWidget(self._front_c, 4, 1)

        # Back color: the tint of faces seen from behind (the
        # inside of a solid, or a reversed face).
        grid.addWidget(QLabel(tr("Back color:")), 5, 0)
        self._back_c = self._swatch(
            tr("Back color — paints faces seen from behind"), "back_color")
        grid.addWidget(self._back_c, 5, 1)

        self._sky = QCheckBox(tr("Sky"))
        self._sky.toggled.connect(self._apply_edits)
        grid.addWidget(self._sky, 6, 0)
        self._sky_c = self._swatch(tr("Sky color"), "sky_color")
        grid.addWidget(self._sky_c, 6, 1)

        grid.addWidget(QLabel(tr("Ground:")), 7, 0)
        self._ground_c = self._swatch(tr("Ground color"), "ground_color")
        grid.addWidget(self._ground_c, 7, 1)

        grid.addWidget(QLabel(tr("Background:")), 8, 0)
        self._bg_c = self._swatch(
            tr("Background — visible with the sky off"), "background")
        grid.addWidget(self._bg_c, 8, 1)

        row = QHBoxLayout()
        save_btn = QPushButton(tr("Save style…"))
        save_btn.clicked.connect(self._on_save)
        row.addWidget(save_btn)
        self._del_btn = QPushButton(tr("Delete"))
        self._del_btn.clicked.connect(self._on_delete)
        row.addWidget(self._del_btn)
        grid.addLayout(row, 10, 0, 1, 2)

        self.refresh()

    # ---- Plumbing -----------------------------------------------------------
    def _style(self):
        return getattr(self._window.viewport.scene, "display_style", None)

    def _shown_color(self, attr: str):
        """The colour a swatch shows for ``attr``. Back color may be unset
        (automatic): show the tint that actually draws."""
        style = self._style()
        if attr == "back_color":
            from core.style import effective_back_color
            return effective_back_color(style, self._window.viewport.scene)
        return getattr(style, attr)

    def _swatch(self, title: str, attr: str) -> QPushButton:
        btn = QPushButton()
        btn.setToolTip(title)
        btn.clicked.connect(lambda: self._pick_color(title, attr))
        return btn

    @staticmethod
    def _css(color) -> str:
        r, g, b = (max(0, min(255, round(c * 255))) for c in color[:3])
        return (f"QAbstractButton {{ background: rgb({r},{g},{b}); "
                "min-height: 18px; }")

    def refresh(self) -> None:
        """Mirror the active style and the user library (called on loads,
        preset applies and saves via ``_sync_style_menu``)."""
        from core.style import BUILTIN_STYLES, user_styles
        style = self._style()
        users = user_styles()
        self._updating = True
        try:
            self._combo.clear()
            for p in BUILTIN_STYLES:
                self._combo.addItem(tr(p.name), p.name)
            if users:
                self._combo.insertSeparator(self._combo.count())
                for s in users:
                    self._combo.addItem(s.name, s.name)
            if style is None:
                return
            # -1 (nothing shown) when the active style matches no entry —
            # e.g. a document carrying a look that is in no library.
            self._combo.setCurrentIndex(self._combo.findData(style.name))
            self._mode.setCurrentIndex(
                self._mode.findData(style.face_mode))
            self._edges.setChecked(style.edges)
            self._profiles.setChecked(style.profiles)
            self._back_edges.setChecked(getattr(style, "back_edges", False))
            self._sky.setChecked(style.sky)
            self._edge_c.setStyleSheet(self._css(style.edge_color))
            self._front_c.setStyleSheet(self._css(style.front_color))
            self._back_c.setStyleSheet(
                self._css(self._shown_color("back_color")))
            self._sky_c.setStyleSheet(self._css(style.sky_color))
            self._ground_c.setStyleSheet(self._css(style.ground_color))
            self._bg_c.setStyleSheet(self._css(style.background))
            self._del_btn.setEnabled(
                any(s.name == self._combo.currentData() for s in users))
        finally:
            self._updating = False

    # ---- Actions ------------------------------------------------------------
    def _on_pick(self, index: int) -> None:
        from core.style import style_by_name
        picked = style_by_name(self._combo.itemData(index))
        if picked is None:
            return
        self._window.viewport.scene.display_style = picked
        self._window._sync_style_menu()          # menu + this panel
        self._window.viewport.update()

    def _apply_edits(self, *_a) -> None:
        style = self._style()
        if style is None or self._updating:
            return
        style.face_mode = self._mode.currentData()
        style.edges = self._edges.isChecked()
        style.profiles = self._profiles.isChecked()
        style.back_edges = self._back_edges.isChecked()
        style.sky = self._sky.isChecked()
        self._window._sync_style_menu()
        self._window.viewport.update()

    def _pick_color(self, title: str, attr: str) -> None:
        style = self._style()
        if style is None:
            return
        c = self._shown_color(attr)
        chosen = get_color(
            QColor.fromRgbF(*(float(v) for v in c[:3])), _dialog_parent(self), title)
        if not chosen.isValid():
            return
        setattr(style, attr, (chosen.redF(), chosen.greenF(), chosen.blueF()))
        self.refresh()
        self._window.viewport.update()
        # Every colour is editable in every mode (build the look, save it) —
        # but an edit that can't show RIGHT NOW says so, or it reads as
        # "styles don't work" (it did, live, 2026-08-31).
        hint = self._color_hint(attr)
        if hint:
            bar = getattr(self._window, "statusBar", None)
            if callable(bar):
                bar().showMessage(hint, 4000)

    def _color_hint(self, attr: str) -> str | None:
        """Why the colour just edited may not be visible right now (``None``
        when it should be showing)."""
        style = self._style()
        if style is None:
            return None
        mode = style.face_mode
        if attr == "front_color" and mode not in ("hidden_line", "monochrome"):
            return tr("Front color saved — it paints faces in Hidden line "
                      "and Monochrome modes.")
        if attr == "back_color" and mode in ("hidden_line", "wireframe"):
            return tr("Back color saved — it paints back faces in Textures, "
                      "Shaded, Monochrome and X-ray modes.")
        if attr == "background" and style.sky:
            return tr("Background saved — it shows with the sky off.")
        if attr in ("sky_color", "ground_color") and not style.sky:
            return tr("Sky and ground colors show with the sky on.")
        if attr == "edge_color" and not style.edges and mode != "wireframe":
            return tr("Edge color saved — this style has edges off.")
        return None

    def _on_save(self) -> None:
        style = self._style()
        if style is None:
            return
        from core.style import builtin_names, save_user_style
        suggested = "" if style.name in builtin_names() else style.name
        parent = _dialog_parent(self)
        name, ok = _prompts.get_text(
            parent, tr("Save style"), tr("Style name:"), text=suggested)
        name = name.strip()
        if not ok or not name:
            return
        if name in builtin_names():
            QMessageBox.warning(
                parent, tr("Save style"),
                tr("'{name}' is a built-in style — pick another name.",
                   name=name))
            return
        style.name = name        # the active style takes the saved identity
        save_user_style(style)
        self._window._sync_style_menu()
        self._window.statusBar().showMessage(
            tr("Style '{name}' saved.", name=name), 3000)

    def _on_delete(self) -> None:
        from core.style import delete_user_style
        name = self._combo.currentData()
        if not name:
            return
        if QMessageBox.question(
                _dialog_parent(self), tr("Delete style"),
                tr("Delete style '{name}'?", name=name)) != QMessageBox.Yes:
            return
        delete_user_style(name)
        self._window._sync_style_menu()



#: What a layer can be assigned to (faces, edges, objects and annotations
#: alike are tagged).
_TAGGABLE = (Face, Edge, Group, Dimension, TextLabel)


class EntityInfoPanel(QWidget):
    """Facts about the current selection, plus the one thing an Entity
    Info panel lets you CHANGE here: the layer (its Tag field). Rafael
    went looking for it exactly here — «debo de tener que ir a las
    propiedades del objeto… no sé cómo cambiarlo de aquí» (2026-09-16,
    39:00) — and found only the Layers panel's button, which he did not
    understand."""

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtWidgets import QComboBox, QHBoxLayout
        self._window = window
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        self._label = QLabel(tr("Nothing selected"))
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.RichText)
        self._label.setStyleSheet("font-size: 12px;")
        lay.addWidget(self._label)
        # The name of ONE group or component, edited here — where everyone
        # looks for it (issue #214: «there seems to be no way to name this
        # group»). The Parts panel could already rename, out of sight.
        from PySide6.QtWidgets import QLineEdit
        name_row = QHBoxLayout()
        self._name_caption = QLabel(tr("Name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setToolTip(
            tr("The name of the selected group or component — Enter keeps it"))
        self._name_edit.editingFinished.connect(self._on_name_edited)
        name_row.addWidget(self._name_caption)
        name_row.addWidget(self._name_edit, 1)
        lay.addLayout(name_row)
        self._named = None               # the group the field is showing
        row = QHBoxLayout()
        self._layer_caption = QLabel(tr("Layer:"))
        self._layer_box = QComboBox()
        self._layer_box.setToolTip(
            tr("The layer the selection is on — pick another to move it"))
        self._layer_box.currentIndexChanged.connect(self._on_layer_picked)
        row.addWidget(self._layer_caption)
        row.addWidget(self._layer_box, 1)
        lay.addLayout(row)
        # A steady height. Selecting something used to resize this panel —
        # one line for nothing, two for an edge, four and a layer row for a
        # face — and everything below it (layers, scenes, the materials
        # library) slid up and down with every click (Marco, 23-09, four
        # screenshots). The layer row keeps its place when hidden, and the
        # text keeps room for the four lines a face or a solid shows.
        for w in (self._layer_caption, self._layer_box,
                  self._name_caption, self._name_edit):
            pol = w.sizePolicy()
            pol.setRetainSizeWhenHidden(True)
            w.setSizePolicy(pol)
        from PySide6.QtGui import QFont, QFontMetrics
        font = QFont(self._label.font())
        font.setPixelSize(12)
        self._label.setMinimumHeight(QFontMetrics(font).lineSpacing() * 4 + 4)
        self._layer_caption.hide()
        self._layer_box.hide()
        self._name_caption.hide()
        self._name_edit.hide()

    def refresh(self) -> None:
        sel = list(self._window.viewport.scene.selection)
        self._label.setText(self._describe(sel))
        self._refresh_name(sel)
        self._refresh_layer(sel)

    # ---- Name field ---------------------------------------------------------
    def _refresh_name(self, sel: list) -> None:
        one = sel[0] if len(sel) == 1 and isinstance(sel[0], Group) else None
        self._name_caption.setVisible(one is not None)
        self._name_edit.setVisible(one is not None)
        changed = one is not self._named
        self._named = one
        if one is None:
            return
        # Not while typing into it — unless the selection moved on.
        if changed or not self._name_edit.hasFocus():
            self._name_edit.setText(one.name or "")

    def _on_name_edited(self) -> None:
        group = self._named
        if group is None:
            return
        name = self._name_edit.text().strip()
        if not name or name == (group.name or ""):
            self._name_edit.setText(group.name or "")    # empty: keep it
            return
        from core.history import RenameGroupCommand
        self._window.viewport.history.execute(RenameGroupCommand(group, name))
        self._window.viewport.update()

    # ---- Layer field --------------------------------------------------------
    def _refresh_layer(self, sel: list) -> None:
        from core.layers import layer_of
        tagged = [e for e in sel if isinstance(e, _TAGGABLE)]
        show = bool(tagged)
        self._layer_caption.setVisible(show)
        self._layer_box.setVisible(show)
        if not show:
            return
        scene = self._window.viewport.scene
        names = [ly.name for ly in scene.layers]
        current = {layer_of(e) for e in tagged}
        self._updating = True
        try:
            self._layer_box.clear()
            if len(current) > 1:
                # A mixed selection reads as such; picking a layer moves
                # everything onto it.
                self._layer_box.addItem(tr("(several)"), None)
            for name in names:
                self._layer_box.addItem(name, name)
            if len(current) == 1:
                idx = self._layer_box.findData(next(iter(current)))
                self._layer_box.setCurrentIndex(max(idx, 0))
            else:
                self._layer_box.setCurrentIndex(0)
        finally:
            self._updating = False

    def _on_layer_picked(self, _index: int) -> None:
        if self._updating:
            return
        name = self._layer_box.currentData()
        if not name:
            return
        from core.history import AssignLayerCommand
        from core.layers import layer_of
        scene = self._window.viewport.scene
        targets = [e for e in scene.selection
                   if isinstance(e, _TAGGABLE) and layer_of(e) != name]
        if not targets:
            return
        self._window.viewport.history.execute(AssignLayerCommand(targets, name))
        self._window.viewport.update()
        self._window.statusBar().showMessage(
            tr("{n} entities moved to '{layer}'", n=len(targets), layer=name),
            2500)

    def _describe(self, sel: list) -> str:
        if not sel:
            return tr("Nothing selected")
        if len(sel) == 1:
            e = sel[0]
            if isinstance(e, Face):
                mat = self._material_of(e)
                return (f"<b>{tr('Face')}</b><br>{tr('Area')}: {fmt_area(e.area())}<br>"
                        f"{tr('Vertices')}: {len(e.vertices)}<br>"
                        f"{tr('Material')}: {mat}")
            if isinstance(e, Edge):
                return (f"<b>{tr('Edge')}</b><br>"
                        f"{tr('Length')}: {fmt_len((e.b - e.a).length())}")
            if isinstance(e, Dimension):
                return f"<b>{tr('Dimension')}</b><br>{tr('Measure')}: {fmt_len(e.value())}"
            if isinstance(e, Group):
                # The usual «Solid Group» / «Solid Component» with its
                # volume, the Solid Tools' own test (core.solids).
                vol = self._solid_volume(e)
                solid = (f"<br>{tr('Volume')}: {fmt_volume(vol)}"
                         if vol is not None else "")
                if e.is_component():
                    # Entity Info usually tells a component from a group and
                    # says how many copies share the definition. Without it the
                    # two are indistinguishable here, which also made an import
                    # that flattened components impossible to spot.
                    kin = sum(1 for g in self._window.viewport.scene.groups
                              if g.mesh is e.mesh)
                    title = (tr("Solid Component") if vol is not None
                             else tr("Component"))
                    return (f"<b>{title}</b><br>"
                            f"{tr('Faces')}: {len(e.mesh.faces)}<br>"
                            f"{tr('In model')}: {kin}{solid}")
                title = tr("Solid Group") if vol is not None else tr("Group")
                return (f"<b>{title}</b><br>"
                        f"{tr('Faces')}: {len(e.mesh.faces)}{solid}")
            return f"<b>{tr('1 entity')}</b>"
        counts = {"faces": 0, "edges": 0, "dimensions": 0, "groups": 0}
        for e in sel:
            if isinstance(e, Face):
                counts["faces"] += 1
            elif isinstance(e, Edge):
                counts["edges"] += 1
            elif isinstance(e, Dimension):
                counts["dimensions"] += 1
            elif isinstance(e, Group):
                counts["groups"] += 1
        parts = [f"{n} {tr(k)}" for k, n in counts.items() if n]
        return f"<b>{tr('Selection')}</b><br>" + ", ".join(parts)

    def _solid_volume(self, group):
        """Cached per scene version: the panel refreshes on every change and
        the check walks the whole mesh."""
        from core.solids import solid_volume
        version = self._window.viewport.scene.version
        cache = getattr(self, "_solid_cache", None)
        if cache is None or cache[0] != version:
            cache = self._solid_cache = (version, {})
        if id(group) not in cache[1]:
            cache[1][id(group)] = solid_volume(group)
        return cache[1][id(group)]

    @staticmethod
    def _material_of(face) -> str:
        tex = face.attrs.get("texture")
        if tex and tex.get("path"):
            return Path(tex["path"]).stem
        col = face.attrs.get("color")
        if col is not None:
            return f"color {tuple(round(c, 2) for c in col)}"
        return "—"


class _ScrollAnchor(QObject):
    """Keeps what you are looking at still when a section ABOVE it changes
    height. Entity Info fills up when you select something, and everything
    below it — the materials library you had scrolled to — slid down by
    that much (Marco, 23-09: «la lista sigue saltando… cuando selecciono un
    componente se llena Info de entidad»). Browsers call it scroll
    anchoring: a section that grows or shrinks above the top of the view
    moves the scroll bar by the same amount."""

    def __init__(self, scroll: QScrollArea) -> None:
        super().__init__(scroll)
        self._scroll = scroll

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent, QTimer
        if event.type() == QEvent.Resize:
            delta = event.size().height() - event.oldSize().height()
            bar = self._scroll.verticalScrollBar()
            # Only a section wholly ABOVE the view: the one you are looking
            # at also resizes for a moment as the layout settles, and moving
            # for it too doubled the correction.
            if (delta and event.oldSize().height() > 0
                    and obj.y() + event.oldSize().height() <= bar.value()):
                target = bar.value() + delta
                # After the layout has taken the new height, or the bar's
                # range would clamp the move.
                QTimer.singleShot(0, lambda b=bar, t=target: b.setValue(t))
        return False


def _wrapping_check(text: str):
    """A check box whose text wraps: ``(checkbox, row widget)``. A long
    QCheckBox label is one line and sets the tray's minimum width; here the
    label is a word-wrapping QLabel beside a text-less box, and clicking the
    label toggles the box like a check box's own text would."""
    row = QWidget()
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    check = QCheckBox()
    label = QLabel(text)
    label.setWordWrap(True)
    label.mousePressEvent = lambda _e: check.isEnabled() and check.toggle()
    box.addWidget(check, 0, Qt.AlignTop)
    box.addWidget(label, 1)
    return check, row


#: Combo boxes in a tray ask for this many characters, not their longest
#: item: «Esri World Imagery (satellite)» would otherwise set the width.
_COMBO_MIN_CHARS = 8


def _let_narrow(widget: QWidget) -> None:
    """Keep a tray's combo boxes from sizing the dock area to their longest
    item; the popup still shows every item in full."""
    for combo in widget.findChildren(QComboBox):
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(_COMBO_MIN_CHARS)


def _scrolled(sections) -> QScrollArea:
    """A scroll area wrapping a vertical stack of collapsible sections."""
    inner = QWidget()
    col = QVBoxLayout(inner)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(2)
    scroll = QScrollArea()
    anchor = _ScrollAnchor(scroll)
    for title, widget in sections:
        section = _Section(title, widget)
        section.installEventFilter(anchor)
        col.addWidget(section)
    col.addStretch(1)
    _let_narrow(inner)
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner)
    scroll.setMinimumWidth(240)
    return scroll




class LayersPanel(QWidget):
    """Layers / tags (Fase 6): one row per layer with visibility and lock
    checkboxes; buttons to add / remove layers and to move the current
    selection onto a layer. Hiding layers of one model is the '2D that
    emerges' workflow: plan = top view + parallel projection + the right
    layers on."""

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtWidgets import (QHBoxLayout, QPushButton, QTreeWidget,
                                       QTreeWidgetItem, QVBoxLayout)
        self._window = window
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([tr("Name"), tr("Visible"), tr("Lock")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 120)
        self.tree.setColumnWidth(1, 52)
        self.tree.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.tree)
        row = QHBoxLayout()
        add_btn = QPushButton(tr("+ Layer"))
        add_btn.clicked.connect(self._on_add)
        del_btn = QPushButton(tr("−"))
        del_btn.setToolTip(tr("Delete layer (its entities go to the default)"))
        del_btn.clicked.connect(self._on_delete)
        purge_btn = QPushButton(tr("Purge"))
        purge_btn.setToolTip(tr("Delete every layer no entity carries "
                                "(a layer a scene hides is kept)"))
        purge_btn.clicked.connect(self._on_purge)
        assign_btn = QPushButton(tr("Assign selection"))
        assign_btn.setToolTip(tr("Move the selected entities onto the layer "
                                 "highlighted in the list (also: Entity "
                                 "info ▸ Layer, or right-click ▸ Layer)"))
        assign_btn.clicked.connect(self._on_assign)
        # A flow, not a row: the four buttons wrap when the tray is narrow
        # instead of setting the whole right-hand dock area's minimum width.
        row = FlowLayout(spacing=4)
        row.addWidget(add_btn)
        row.addWidget(del_btn)
        row.addWidget(purge_btn)
        row.addWidget(assign_btn)
        lay.addLayout(row)
        self.refresh()

    # ---- Model → view --------------------------------------------------------
    def refresh(self) -> None:
        from PySide6.QtWidgets import QTreeWidgetItem
        from core.layers import DEFAULT_LAYER
        self._updating = True
        self.tree.clear()
        for ly in self._window.viewport.scene.layers:
            item = QTreeWidgetItem([ly.name, "", ""])
            item.setData(0, Qt.UserRole, ly.name)
            flags = item.flags() | Qt.ItemIsUserCheckable
            if ly.name != DEFAULT_LAYER:
                flags |= Qt.ItemIsEditable
            item.setFlags(flags)
            item.setCheckState(1, Qt.Checked if ly.visible else Qt.Unchecked)
            item.setCheckState(2, Qt.Checked if ly.locked else Qt.Unchecked)
            self.tree.addTopLevelItem(item)
        fit_rows(self.tree, max_rows=12)
        self._updating = False

    # ---- View → model --------------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def _on_item_changed(self, item, column) -> None:
        if self._updating:
            return
        scene = self._scene()
        old_name = item.data(0, Qt.UserRole)
        ly = scene.layer(old_name)
        if ly is None:
            return
        if column == 0:
            new_name = item.text(0).strip()
            if new_name and new_name != old_name \
                    and scene.layer(new_name) is None:
                self._rename(ly, old_name, new_name)
            self.refresh()
            self._touch()
            return
        ly.visible = item.checkState(1) == Qt.Checked
        ly.locked = item.checkState(2) == Qt.Checked
        if not ly.visible or ly.locked:
            self._prune_selection(ly.name)
        self._touch()

    def _rename(self, ly, old_name: str, new_name: str) -> None:
        from core.layers import layer_of, assign_layer
        scene = self._scene()
        ly.name = new_name
        for ent in list(scene.mesh.faces) + list(scene.mesh.edges) \
                + list(scene.groups):
            if layer_of(ent) == old_name:
                assign_layer(ent, new_name)

    def _prune_selection(self, name: str) -> None:
        from core.layers import layer_of
        scene = self._scene()
        dead = [s for s in scene.selection
                if isinstance(s, (Face, Edge, Group)) and layer_of(s) == name]
        for s in dead:
            scene.selection.discard(s)

    def _on_add(self) -> None:
        from core.layers import Layer
        scene = self._scene()
        base = tr("Layer")
        n = 1
        while scene.layer(f"{base} {n}") is not None:
            n += 1
        scene.layers.append(Layer(f"{base} {n}"))
        self.refresh()
        self._touch()

    def _on_delete(self) -> None:
        from core.layers import DEFAULT_LAYER, layer_of, assign_layer
        scene = self._scene()
        item = self.tree.currentItem()
        if item is None:
            return
        name = item.data(0, Qt.UserRole)
        if name == DEFAULT_LAYER:
            return                                  # the default is permanent
        ly = scene.layer(name)
        if ly is None:
            return
        # Every mesh in the document, nested placements included — walking
        # scene.groups as a flat list left the faces INSIDE a group tagged
        # with a layer that no longer existed.
        from core.purge import iter_groups, iter_meshes
        for mesh in iter_meshes(scene):
            for ent in list(mesh.faces) + list(mesh.edges):
                if layer_of(ent) == name:
                    assign_layer(ent, DEFAULT_LAYER)
        for ent in list(iter_groups(scene.groups)) \
                + list(getattr(scene, "dimensions", []) or []) \
                + list(getattr(scene, "text_labels", []) or []) \
                + list(getattr(scene, "image_planes", []) or []):
            if layer_of(ent) == name:
                assign_layer(ent, DEFAULT_LAYER)
        scene.layers.remove(ly)
        self.refresh()
        self._touch()

    def _on_purge(self) -> None:
        """The classic "Purge Unused" for tags: sweep the layers nothing
        carries. One undoable step, and it says what it did — a silent
        sweep of a panel the user did not look at is how a deliberate
        empty layer disappears without anyone noticing."""
        from PySide6.QtWidgets import QMessageBox
        from core.history import PurgeUnusedCommand
        scene = self._scene()
        cmd = PurgeUnusedCommand(layers=True, materials=False)
        n_layers, _ = cmd.counts(scene)
        if not n_layers:
            QMessageBox.information(
                self, tr("Purge"), tr("Every layer is in use."))
            return
        names = [ly.name for _i, ly in (cmd._layers or [])]
        preview = ", ".join(names[:12]) + ("…" if len(names) > 12 else "")
        if QMessageBox.question(
                self, tr("Purge"),
                tr("Delete {n} layers no entity carries?", n=n_layers)
                + f"\n\n{preview}") != QMessageBox.Yes:
            return
        self._window.viewport.history.execute(cmd)
        self.refresh()
        self._window.viewport.update()
        self._window.statusBar().showMessage(
            tr("{n} unused layers purged", n=n_layers), 3000)

    def _on_assign(self) -> None:
        """Move the selection onto the HIGHLIGHTED layer — and say so when
        there is nothing to move or no layer picked: the button used to do
        nothing in silence, which is how it read as broken («Asignar
        selección funcionó a la segunda», Rafael, 2026-09-16)."""
        from core.history import AssignLayerCommand
        scene = self._scene()
        item = self.tree.currentItem()
        if item is None:
            self._window.statusBar().showMessage(
                tr("Click a layer in the list first, then Assign."), 3000)
            return
        name = item.data(0, Qt.UserRole)
        # Annotations are tagged too: a "Anotaciones" layer a
        # scene hides gives a clean plan without duplicating the model.
        targets = [ent for ent in scene.selection
                   if isinstance(ent, (Face, Edge, Group, Dimension, TextLabel))]
        if not targets:
            self._window.statusBar().showMessage(
                tr("Select something in the model first, then Assign."), 3000)
            return
        self._window.viewport.history.execute(AssignLayerCommand(targets, name))
        self._window.viewport.update()
        self._window.statusBar().showMessage(
            tr("{n} entities moved to '{layer}'", n=len(targets), layer=name),
            2500)

    def _touch(self) -> None:
        scene = self._scene()
        scene.version += 1
        self._window.viewport.update()




#: Kill-switch: set INGETRAZO_SCENE_ALWAYS_BUMP=1 to bump ``scene.version``
#: on every scene recall, as before — also one that only moves the camera.
_SCENE_ALWAYS_BUMP = os.environ.get("INGETRAZO_SCENE_ALWAYS_BUMP", "") == "1"




class Tray(QDockWidget):
    """Right-side **Properties** dock: what you're working with — the selection's
    info, materials, and annotation styles (context, not geo workspace)."""

    def __init__(self, window) -> None:
        super().__init__(tr("Properties"), window)
        self.setObjectName("tray_properties")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        # Closable: without it Qt greys out the Window-menu entry, and a
        # tray the sidebar fold left hidden had no way back (Marco, 0.5.1).
        # The empty title bar shows no close button either way.
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable
                         | QDockWidget.DockWidgetClosable)

        self.entity_info = EntityInfoPanel(window)
        self.materials = MaterialsPanel(window)
        self.components = ComponentsPanel(window)
        self.parts = PartsPanel(window)
        self.layers = LayersPanel(window)
        # Styles, Shadows and Dimension style are NOT here: they live in
        # their own on-demand docks (toolbar toggles) — the always-open tray
        # was drowning.
        self.setWidget(_scrolled([
            (tr("Entity info"), self.entity_info),
            (tr("Layers"), self.layers),
            (tr("Materials"), self.materials),
            (tr("Components"), self.components),
            (tr("Parts"), self.parts),
        ]))

    def on_scene_changed(self) -> None:
        self.entity_info.refresh()
        # The materials panel scans every render face for its swatches —
        # ~0.5 s on an exploded 28k-face mesh, paid per EDIT when run
        # inline. Debounced: one refresh 300 ms after the last edit.
        timer = getattr(self, "_mat_refresh_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer
            timer = self._mat_refresh_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self.materials.refresh_in_model)
        timer.start(300)
        self.layers.refresh()
        self.components.on_scene_changed()
        self.parts.refresh()




