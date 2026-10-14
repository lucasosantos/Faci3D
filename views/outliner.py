# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Browser: the model's tree.

**The Browser** (a sidebar tab of the model window) is the Outliner
(#219): every group and component at every depth, under the document's
name. An icon says what each row is (group, component, image, 3D text, or
what an extension says it is); the eye shows or hides it, the padlock
locks it; the filter keeps the rows whose name, type or layer match, with
the containers on the way to them. A click
selects in the view — opening the groups around it, as double-clicking down
to it would — and a double-click (or Enter) opens it for editing. A
selection made in the view is found in the tree, its branch unfolded, and
the groups open for editing read in bold, so the tree always says where you
are.

The Outliner is built on the Project Structure plugin Carlos Martins
(@fafecm) shared in #87 — the tree mirrored with the view both ways, the
eye per node, entering a nested group through its path — and on the scope
Roy Méndez Castro (@roymendezcastro) wrote down in #219. Its drag and
drop and its padlock are here too: re-nesting keeps every group where it
stands in the world, whatever frame the new parent has, and the lock is
saved in the document.

The model stays the only source of truth: rows hold their group, and
renames and hides are the usual undoable commands.
"""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QPainter, QPalette, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QDockWidget, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QStyle,
                               QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from core import outliner
from core.group import Group
from core.i18n import tr

# Model tab columns.
(COL_NAME, COL_EYE, COL_LOCK, COL_TYPE, COL_LAYER, COL_MATERIAL,
 COL_COPIES) = range(7)
#: Columns the header's right-click shows or hides, and which start shown.
OPTIONAL_COLUMNS = ((COL_TYPE, "Type", True), (COL_LAYER, "Layer", True),
                    (COL_MATERIAL, "Material", False),
                    (COL_COPIES, "Copies", False))

# Keys the tree answers itself while it has the focus, instead of the
# window's single-key shortcuts (Space is Select, Esc cancels a tool…).
_TREE_KEYS = {Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape,
              Qt.Key_F2, Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
              Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown}


# ---- Icons ---------------------------------------------------------------------
# Drawn, like the tool icons (views/icons.py), in the palette's own ink so
# they read in the light and the dark theme alike.

_ICONS: dict = {}


def _ink() -> QColor:
    from PySide6.QtWidgets import QApplication
    return QApplication.palette().text().color()


def _accent() -> QColor:
    from PySide6.QtWidgets import QApplication
    return QApplication.palette().highlight().color()


def _cube(p, ink, fill=None) -> None:
    """A small box in cavalier view: the group's mark."""
    front = QRectF(2.5, 6.5, 9, 8)
    if fill is not None:
        p.setBrush(fill)
    p.drawPolygon([QPointF(2.5, 6.5), QPointF(6.5, 2.5), QPointF(15.5, 2.5),
                   QPointF(15.5, 10.5), QPointF(11.5, 14.5),
                   QPointF(2.5, 14.5)])
    p.setBrush(Qt.NoBrush)
    p.drawRect(front)
    p.drawLine(QPointF(11.5, 6.5), QPointF(15.5, 2.5))


def _draw(key: str):
    ink = _ink()
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(ink, 1.2))
    if key == "group":
        _cube(p, ink)
    elif key == "component":
        # A component is a box FILLED: the definition its copies share.
        fill = QColor(_accent())
        fill.setAlpha(110)
        _cube(p, ink, fill)
    elif key == "document":
        p.drawPolygon([QPointF(2, 9), QPointF(9, 3), QPointF(16, 9)])
        p.drawRect(QRectF(4, 9, 10, 7))
    elif key in ("lock", "lock_open"):
        # The shackle closed over the body, or swung up and open.
        p.drawRoundedRect(QRectF(4, 8.5, 10, 7.5), 1.5, 1.5)
        if key == "lock":
            p.drawArc(QRectF(5.5, 2.5, 7, 10), 0, 180 * 16)
            p.drawLine(QPointF(5.5, 7.5), QPointF(5.5, 8.5))
            p.drawLine(QPointF(12.5, 7.5), QPointF(12.5, 8.5))
        else:
            faint = QColor(ink)
            faint.setAlpha(110)
            p.setPen(QPen(faint, 1.2))
            p.drawRoundedRect(QRectF(4, 8.5, 10, 7.5), 1.5, 1.5)
            p.drawArc(QRectF(8.5, 1.5, 7, 9), 0, 180 * 16)
            p.drawLine(QPointF(8.5, 6), QPointF(8.5, 8.5))
    elif key in ("eye", "eye_off"):
        if key == "eye_off":
            p.setPen(QPen(QColor(ink.red(), ink.green(), ink.blue(), 110),
                          1.2))
        p.drawEllipse(QRectF(2, 5.5, 14, 7))
        p.setBrush(p.pen().color())
        p.drawEllipse(QRectF(7, 7, 4, 4))
        if key == "eye_off":
            p.setPen(QPen(ink, 1.4))
            p.drawLine(QPointF(3, 15), QPointF(15, 3))
    p.end()
    return QIcon(pm)


def node_icon(key: str) -> QIcon:
    """The icon for a row kind — ``group``, ``component``, ``image``,
    ``text``, ``document``, ``eye``, ``eye_off``, ``warning``."""
    if key not in _ICONS:
        if key in ("image", "text"):
            from views.icons import tool_icon
            _ICONS[key] = tool_icon({"image": "image", "text": "text3d"}[key])
        elif key == "warning":
            from PySide6.QtWidgets import QApplication
            _ICONS[key] = QApplication.style().standardIcon(
                QStyle.SP_MessageBoxWarning)
        elif key == "folder":
            from PySide6.QtWidgets import QApplication
            _ICONS[key] = QApplication.style().standardIcon(QStyle.SP_DirIcon)
        else:
            _ICONS[key] = _draw(key)
    return _ICONS[key]



def _remember_widths(header, key: str, columns) -> None:
    """Give ``columns`` the widths the user left them at, and keep them
    as they are dragged (per user, not per document)."""
    from PySide6.QtCore import QSettings
    saved = QSettings().value(key)
    if isinstance(saved, str):
        saved = saved.split(",")
    if isinstance(saved, (list, tuple)) and len(saved) == len(columns):
        for col, width in zip(columns, saved):
            try:
                if int(width) >= 40:
                    header.resizeSection(col, int(width))
            except (TypeError, ValueError):
                pass

    def save(*_args) -> None:
        QSettings().setValue(key, ",".join(
            str(header.sectionSize(c)) for c in columns))

    header.sectionResized.connect(save)


def _tool_button(text: str, tip: str, slot) -> QToolButton:
    btn = QToolButton()
    btn.setText(text)
    btn.setToolTip(tip)
    btn.setAutoRaise(True)
    btn.clicked.connect(slot)
    return btn


# ---- Model 3D ------------------------------------------------------------------

class _Tree(QTreeWidget):
    """The tree, with the keyboard of an outliner: Space shows or hides the
    selected rows, Enter opens the current one, Esc steps out one level,
    Tab puts the selection into the group above it and Shift+Tab takes it
    out one level. Rows dragged onto a group go into it; dropped between
    rows, they go beside them."""

    def __init__(self, panel) -> None:
        super().__init__()
        self._panel = panel
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def event(self, ev) -> bool:
        from PySide6.QtCore import QEvent
        editing = self.state() == QAbstractItemView.EditingState
        if (ev.type() == QEvent.ShortcutOverride and not editing
                and (ev.key() in _TREE_KEYS
                     or ev.key() in (Qt.Key_Tab, Qt.Key_Backtab))
                and not (ev.modifiers() & (Qt.ControlModifier
                                           | Qt.AltModifier))):
            ev.accept()
            return True
        # Tab moves the focus before keyPressEvent ever sees it.
        if (ev.type() == QEvent.KeyPress and not editing
                and ev.key() in (Qt.Key_Tab, Qt.Key_Backtab)):
            if ev.key() == Qt.Key_Backtab or \
                    ev.modifiers() & Qt.ShiftModifier:
                self._panel.outdent()
            else:
                self._panel.indent()
            return True
        return super().event(ev)

    def dropEvent(self, ev) -> None:
        """Re-nest through the panel — one undoable command — and never let
        Qt move the rows itself: the tree follows the model, not the other
        way round."""
        item = self.itemAt(ev.position().toPoint())
        if item is not None and \
                self.dropIndicatorPosition() != QAbstractItemView.OnItem:
            item = item.parent()            # between rows: beside them
        ev.setDropAction(Qt.IgnoreAction)
        ev.accept()
        self._panel.reparent(self._panel._selected_groups(),
                             self._panel._group_of(item))

    def keyPressEvent(self, ev) -> None:
        if self.state() != QAbstractItemView.EditingState:
            key = ev.key()
            if key == Qt.Key_Space:
                self._panel.toggle_hidden()
                return
            if key in (Qt.Key_Return, Qt.Key_Enter):
                item = self.currentItem()
                if item is not None:
                    self._panel.open_item(item)
                return
            if key == Qt.Key_Escape:
                self._panel.step_out()
                return
        super().keyPressEvent(ev)


class OutlinerPanel(QWidget):
    """The model's tree of groups and components (the Model 3D tab)."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._updating = False
        self._stale = False
        self._shape: tuple | None = None
        self._items: dict = {}              # id(group) -> its row
        self._groups: dict = {}             # id(group) -> the group
        self._state: dict = {}              # id(group) -> what its row shows
        self._shown_selection: tuple = ()
        self._shown_path: tuple = ()
        self._query = ""
        self._kind_providers: tuple = ()
        self._root = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Filter by name, type or layer…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(_tool_button("◎", tr(
            "Isolate: hide everything but the selected groups"),
            self.isolate))
        bar.addWidget(_tool_button("◉", tr("Show all groups"),
                                   self.show_all))
        bar.addWidget(_tool_button("⊞", tr("Expand all"), self._expand_all))
        bar.addWidget(_tool_button("⊟", tr("Collapse all"),
                                   self._collapse_all))
        lay.addLayout(bar)
        self.tree = _Tree(self)
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels([tr("Name"), "", "", tr("Type"),
                                   tr("Layer"), tr("Material"), tr("Copies")])
        head = self.tree.header()
        # The Name column is the user's to size — drag its edge in the
        # header; the width is remembered. The Layer column takes the rest.
        head.setStretchLastSection(True)
        head.setSectionResizeMode(COL_NAME, QHeaderView.Interactive)
        head.resizeSection(COL_NAME, 200)
        head.setSectionResizeMode(COL_EYE, QHeaderView.Fixed)
        head.resizeSection(COL_EYE, 26)
        head.setSectionResizeMode(COL_LOCK, QHeaderView.Fixed)
        head.resizeSection(COL_LOCK, 26)
        head.setSectionResizeMode(COL_TYPE, QHeaderView.Interactive)
        head.resizeSection(COL_TYPE, 110)
        head.setSectionResizeMode(COL_LAYER, QHeaderView.Interactive)
        head.resizeSection(COL_LAYER, 80)
        _remember_widths(head, "browser/model_columns",
                         (COL_NAME, COL_TYPE))
        for col, width in ((COL_MATERIAL, 100), (COL_COPIES, 60)):
            head.setSectionResizeMode(col, QHeaderView.Interactive)
            head.resizeSection(col, width)
        # Right-click on the header: which columns show (remembered).
        head.setContextMenuPolicy(Qt.CustomContextMenu)
        head.customContextMenuRequested.connect(self._on_header_menu)
        self._apply_column_choice()
        self.tree.headerItem().setIcon(COL_EYE, node_icon("eye"))
        self.tree.headerItem().setToolTip(COL_EYE, tr("Visible"))
        self.tree.headerItem().setIcon(COL_LOCK, node_icon("lock"))
        self.tree.headerItem().setToolTip(COL_LOCK, tr(
            "Locked: drawn, but it cannot be picked, selected or opened"))
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Double-click OPENS a group, as in the view: renaming is F2 or the
        # context menu.
        self.tree.setEditTriggers(QAbstractItemView.EditKeyPressed)
        self.tree.setToolTip(tr(
            "Click to select in the model; double-click or Enter opens the "
            "group. The eye (or Space) shows or hides, the padlock locks; "
            "F2 renames; Esc steps out one level. Drag rows onto a group, "
            "or press Tab / Shift+Tab, to move them in or out of it."))
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self._root = None
        lay.addWidget(self.tree, 1)
        self._empty = QLabel(tr(
            "No groups or components in the model yet."))
        self._empty.setWordWrap(True)
        self._empty.setEnabled(False)
        lay.addWidget(self._empty)
        self.summary = QLabel()
        self.summary.setEnabled(False)
        lay.addWidget(self.summary)
        self._matches = 0
        self.refresh()

    # ---- Model → view --------------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def on_scene_changed(self) -> None:
        """The dock's per-change call: refreshed when on screen, on
        showing otherwise — a hidden tab costs nothing per edit. On screen,
        one refresh 300 ms after the last edit: every row's state is read
        again (17 ms per edit on the Plaza, release_check 09-10), and a
        burst of edits pays it once."""
        if not self.isVisible():
            if not self._stale and self._holds_departed_groups():
                self._forget_rows()     # New / Open: let the old one go
            self._stale = True
            return
        timer = getattr(self, "_refresh_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer
            timer = self._refresh_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self.refresh)
        timer.start(300)

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if self._stale:
            self.refresh()

    def _document_name(self) -> str:
        w = self._window
        path = getattr(w, "_current_path", None)
        if path is not None:
            return path.name
        return getattr(w, "_import_name", None) or tr("Untitled")

    def refresh(self) -> None:
        """Bring the tree up to date: rows rebuilt only when groups came or
        went, otherwise updated in place — a refresh follows every edit and
        every click, and a rebuild would lose the scroll and the branches
        the user unfolded."""
        if self.tree.state() == QAbstractItemView.EditingState:
            return                      # a rename in progress: leave it be
        self._stale = False
        self._kind_providers = tuple(
            getattr(self._window, "_outliner_kinds", None) or ())
        scene = self._scene()
        shape = outliner.structure(scene.groups)
        if shape != self._shape:
            self._rebuild(scene)
            self._shape = shape
        self._update_rows(scene)
        if self._query:
            self._apply_filter()
        self._sync_selection(scene)
        self._empty.setVisible(not self._items)
        self._update_summary()

    def _holds_departed_groups(self) -> bool:
        """Whether a row still holds a group the model no longer has —
        after New or Open (both load into the same scene), or a delete."""
        if not self._groups:
            return False
        live = {id(g) for g, _p, _d in outliner.walk(self._scene().groups)}
        return any(key not in live for key in self._groups)

    def _forget_rows(self) -> None:
        """Drop the rows of a document that is no longer open. Each row
        holds its group, so a hidden Browser waiting to be shown kept the
        whole previous document in memory after Open (release_check
        10-10); the next refresh builds the rows of the new one."""
        self._kept_expanded = {self._groups[key].uid
                               for key, item in self._items.items()
                               if item.isExpanded()}
        self.tree.clear()
        self._items = {}
        self._groups = {}
        self._state = {}
        self._root = None
        self._shape = None

    def _update_summary(self) -> None:
        """The footer: what the model holds, or what the filter found."""
        total = len(self._state)
        if self._query:
            text = tr("{shown} of {total} match", shown=self._matches,
                      total=total)
        else:
            comps = sum(1 for st in self._state.values()
                        if st[3] == "component")
            hidden = sum(1 for st in self._state.values() if st[4])
            text = tr("{groups} groups · {components} components · "
                      "{hidden} hidden", groups=total - comps,
                      components=comps, hidden=hidden)
        if self.summary.text() != text:
            self.summary.setText(text)

    def _rebuild(self, scene) -> None:
        """Rows for every group, each born with its texts and icons: one
        constructor call does what a setText per column would, and the
        cache it fills tells ``_update_rows`` there is nothing left to do."""
        expanded = {self._groups[key].uid
                    for key, item in self._items.items() if item.isExpanded()}
        expanded |= self.__dict__.pop("_kept_expanded", set())
        scroll = self.tree.verticalScrollBar().value()
        counts = outliner.instance_counts(scene.groups)
        opened = {id(g) for g in outliner.open_path(scene)}
        self._updating = True
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            self._items = {}
            self._groups = {}
            self._state = {}
            root = self._root = QTreeWidgetItem(["", "", "", "", ""])
            root.setIcon(COL_NAME, node_icon("document"))
            root.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDropEnabled)
            font = QFont(root.font(COL_NAME))
            font.setBold(True)
            root.setFont(COL_NAME, font)
            self.tree.addTopLevelItem(root)
            editable = Qt.ItemIsEditable
            for g, parent, _depth in outliner.walk(scene.groups):
                key = id(g)
                state = self._row_state(g, counts, opened)
                item = QTreeWidgetItem([state[0], "", "", state[1],
                                        state[2], state[7], state[8]])
                item.setData(COL_NAME, Qt.UserRole, g)
                item.setFlags(item.flags() | editable)
                self._paint(item, None, state)
                (root if parent is None
                 else self._items[id(parent)]).addChild(item)
                self._items[key] = item
                self._groups[key] = g
                self._state[key] = state
            root.setExpanded(True)
            for key, item in self._items.items():
                if self._groups[key].uid in expanded:
                    item.setExpanded(True)
        finally:
            self.tree.blockSignals(False)
            self._updating = False
        self._shown_selection = ()
        self._shown_path = ()
        self.tree.verticalScrollBar().setValue(scroll)

    def _kind(self, group) -> str:
        return outliner.kind(group)

    def _providers(self):
        # Read once per refresh (see refresh): asked per row, the lookup of
        # a missing attribute on the Qt window cost ~1 s on 10 000 rows.
        return self._kind_providers

    def _type_text(self, group, counts) -> str:
        custom = outliner.custom_kind(group, self._providers())
        if custom is not None:
            return custom["type"]
        kind = outliner.kind(group)
        if kind == "component":
            n = counts.get(id(group.mesh), 1)
            return (tr("Component") if n < 2
                    else tr("Component ({n} copies)", n=n))
        return {"group": tr("Group"), "image": tr("Image"),
                "text": tr("3D Text")}[kind]

    def _row_state(self, g, counts, opened) -> tuple:
        """Everything a row shows: ``(name, type, layer, kind, hidden,
        open, locked, material, copies, properties)`` — compared
        as one tuple, so an unchanged row costs no Qt call at all."""
        custom = outliner.custom_kind(g, self._providers())
        props = "\n".join(f"{k}: {v}" for k, v in custom["props"]) \
            if custom else ""
        copies = (str(counts.get(id(g.mesh), 1)) if g.is_component()
                  else "")
        return (g.name or tr("Unnamed group"),
                custom["type"] if custom else self._type_text(g, counts),
                outliner.layer_name(g), self._kind(g), bool(g.hidden),
                id(g) in opened, bool(getattr(g, "locked", False)),
                outliner.material_name(g), copies, props)

    def _paint(self, item, old, new) -> None:
        """Bring ``item`` from the ``old`` state (``None``: just made, texts
        already in) to ``new``, touching only what differs."""
        if old is not None:
            for col, i in ((COL_NAME, 0), (COL_TYPE, 1), (COL_LAYER, 2),
                           (COL_MATERIAL, 7), (COL_COPIES, 8)):
                if old[i] != new[i]:
                    item.setText(col, new[i])
        if old is None or old[9] != new[9]:
            item.setToolTip(COL_TYPE, new[9])
        kind, hidden, bold = new[3], new[4], new[5]
        if old is None or old[3] != kind:
            item.setData(COL_TYPE, Qt.UserRole, kind)
            item.setIcon(COL_NAME, node_icon(kind))
        if old is None or old[4] != hidden:
            item.setData(COL_EYE, Qt.UserRole, hidden)
            item.setIcon(COL_EYE, node_icon("eye_off" if hidden else "eye"))
            if hidden or old is not None:
                item.setForeground(COL_NAME, self.tree.palette().brush(
                    QPalette.PlaceholderText if hidden else QPalette.Text))
        if (old is None and bold) or (old is not None and old[5] != bold):
            font = QFont(item.font(COL_NAME))
            font.setBold(bold)
            item.setFont(COL_NAME, font)
            item.setToolTip(COL_NAME, tr("Open for editing") if bold else "")
        locked = new[6]
        if old is None or old[6] != locked:
            item.setData(COL_LOCK, Qt.UserRole, locked)
            item.setIcon(COL_LOCK, node_icon("lock" if locked
                                             else "lock_open"))

    def _update_rows(self, scene) -> None:
        counts = outliner.instance_counts(scene.groups)
        opened = {id(g) for g in outliner.open_path(scene)}
        self._updating = True
        try:
            name = self._document_name()
            if self._root.text(COL_NAME) != name:
                self._root.setText(COL_NAME, name)
            state_of = self._state
            for key, g in self._groups.items():
                state = self._row_state(g, counts, opened)
                old = state_of[key]
                if state != old:
                    self._paint(self._items[key], old, state)
                    state_of[key] = state
        finally:
            self._updating = False

    def _reveal(self, item) -> None:
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()

    def _sync_selection(self, scene) -> None:
        """Highlight what is selected in the view and, when that changed,
        unfold its branch and scroll it into sight; unfold the groups open
        for editing too, so the context is on screen."""
        path = tuple(id(g) for g in outliner.open_path(scene))
        if path != self._shown_path:
            for key in path:
                item = self._items.get(key)
                if item is not None:
                    self._reveal(item)
                    item.setExpanded(True)
            self._shown_path = path
        chosen = tuple(id(g) for g in scene.selection
                       if id(g) in self._items)
        self.tree.blockSignals(True)
        try:
            wanted = set(chosen)
            for key, item in self._items.items():
                if item.isSelected() != (key in wanted):
                    item.setSelected(key in wanted)
            if chosen and set(chosen) != set(self._shown_selection):
                first = self._items[chosen[0]]
                self._reveal(first)
                self.tree.setCurrentItem(first, COL_NAME,
                                         QItemSelectionModel.NoUpdate)
                self.tree.scrollToItem(first)
        finally:
            self.tree.blockSignals(False)
        self._shown_selection = chosen

    # ---- Filter --------------------------------------------------------------
    def _on_filter(self, text: str) -> None:
        self._query = text.strip().casefold()
        self._apply_filter()
        self._update_summary()

    def _apply_filter(self) -> None:
        """Hide the rows the filter leaves out — no rebuild: a filter typed
        letter by letter over thousands of rows only flips their flag."""
        if not self._query:
            self._matches = len(self._items)
            for item in self._items.values():
                if item.isHidden():
                    item.setHidden(False)
            return
        scene = self._scene()
        counts = outliner.instance_counts(scene.groups)
        keep, hit = outliner.filter_keep(
            scene.groups, self._query,
            lambda g: self._type_text(g, counts))
        self._matches = len(hit)
        for key, item in self._items.items():
            item.setHidden(key not in keep)
            if key in keep and key not in hit:
                item.setExpanded(True)

    def _expand_all(self) -> None:
        self.tree.expandAll()

    def _collapse_all(self) -> None:
        self.tree.collapseAll()
        if self._root is not None:
            self._root.setExpanded(True)

    # ---- View → model --------------------------------------------------------
    def _open_to(self, path) -> bool:
        """Leave the view with exactly ``path`` open — stepping out of the
        levels that differ, then into the rest, one level at a time, as the
        view's own double-click and Esc do. False when a group on the way
        is hidden (it cannot be entered)."""
        if any(g.hidden or getattr(g, "locked", False) for g in path):
            return False
        vp = self._window.viewport
        scene = self._scene()
        current = outliner.open_path(scene)
        same = 0
        while (same < min(len(current), len(path))
               and current[same] is path[same]):
            same += 1
        for _ in range(len(current) - same):
            vp.end_one_group_edit()
        for g in path[same:]:
            vp.begin_group_edit(g)
        return outliner.open_path(scene) == list(path)

    def _group_of(self, item):
        data = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        return data if isinstance(data, Group) else None

    def _selected_groups(self) -> list:
        return [g for g in (self._group_of(item)
                            for item in self.tree.selectedItems())
                if g is not None]

    def _on_tree_selection(self) -> None:
        """Rows picked in the tree become the view's selection. The view
        selects inside ONE context, so the rows that count are the current
        row's siblings; the groups above them open."""
        if self._updating:
            return
        current = self.tree.currentItem()
        group = (self._group_of(current)
                 if current is not None and current.isSelected() else None)
        if group is None:
            picked = self._selected_groups()
            if not picked:
                return
            group = picked[0]
        scene = self._scene()
        path = outliner.path_to(scene.groups, group)
        if path is None:
            return
        siblings = [g for g in self._selected_groups()
                    if outliner.path_to(scene.groups, g) == path]
        if not self._open_to(path):
            self._window.viewport.flash_status(tr(
                "A group around it is hidden or locked: show or unlock "
                "it to select inside"),
                3500)
            return
        picks = [g for g in siblings if scene.entity_selectable(g)]
        scene.selection.clear()
        scene.selection.update(picks)
        # Clicked here, so already in sight: the refresh this triggers must
        # not scroll the tree under the pointer.
        self._shown_selection = tuple(id(g) for g in picks)
        self._shown_path = tuple(id(g) for g in outliner.open_path(scene))
        scene.bump_view()
        self._window.viewport.update()

    def _on_item_clicked(self, item, column) -> None:
        group = self._group_of(item)
        if group is None or column not in (COL_EYE, COL_LOCK):
            return
        # The eye or the padlock clicked on one of several selected rows
        # acts on all of them, as in an outliner.
        selected = self._selected_groups()
        targets = selected if group in selected else [group]
        if column == COL_EYE:
            self.toggle_hidden(targets)
        else:
            self.toggle_locked(targets)

    def _on_double_clicked(self, item, column) -> None:
        if column not in (COL_EYE, COL_LOCK):
            self.open_item(item)

    def open_item(self, item) -> None:
        """Open the row's group for editing — double-click or Enter."""
        group = self._group_of(item)
        if group is None or group.hidden or getattr(group, "locked", False):
            return
        scene = self._scene()
        path = outliner.path_to(scene.groups, group)
        if path is None:
            return
        if self._open_to(path + [group]):
            scene.bump_view()
            self._window.viewport.update()
            self.refresh()

    def step_out(self) -> None:
        """Esc: leave the innermost open group."""
        if self._scene().edit_group is None:
            return
        self._window.viewport.end_one_group_edit()
        self._window.viewport.update()
        self.refresh()

    def toggle_hidden(self, groups=None) -> None:
        """Show the rows when any of them is hidden, hide them otherwise —
        one undoable step."""
        from core.history import HideCommand
        if groups is None:
            # Hiding drops the rows from the selection: the current row is
            # what a second Space shows again.
            groups = self._selected_groups()
            current = self._group_of(self.tree.currentItem())
            if not groups and current is not None:
                groups = [current]
        groups = list(groups)
        if not groups:
            return
        hide = not any(g.hidden for g in groups)
        self._window.viewport.history.execute(HideCommand(groups,
                                                          hidden=hide))
        self._window.viewport.update()
        self.refresh()

    def toggle_locked(self, groups=None) -> None:
        """Unlock the rows when any of them is locked, lock them otherwise —
        one undoable step."""
        from core.history import LockCommand
        if groups is None:
            groups = self._selected_groups()
            current = self._group_of(self.tree.currentItem())
            if not groups and current is not None:
                groups = [current]
        groups = list(groups)
        if not groups:
            return
        lock = not any(getattr(g, "locked", False) for g in groups)
        if lock and any(g is self._scene().edit_group
                        or g in outliner.open_path(self._scene())
                        for g in groups):
            self._window.viewport.end_group_edit()
        self._window.viewport.history.execute(LockCommand(groups, lock))
        self._window.viewport.update()
        self.refresh()

    _REPARENT_REFUSED = {
        "cycle": "A group cannot go inside itself or a group it holds",
        "component": "Components keep their parts: Make Unique first to "
                     "change what is inside one",
        "locked": "Unlock it first",
    }

    def reparent(self, groups, target) -> bool:
        """Put ``groups`` into ``target`` (``None``: the model) — one
        undoable step, nothing moves in the world."""
        from core.history import ReparentGroupsCommand
        scene = self._scene()
        moving = outliner.needs_moving(scene.groups, groups, target)
        if not moving:
            return False
        problem = outliner.reparent_problem(scene.groups, moving, target)
        if problem is not None:
            self._window.viewport.flash_status(
                tr(self._REPARENT_REFUSED[problem]), 4000)
            return False
        # The tools work on what is open: re-nesting under them is not
        # safe, and the view closes them as a click outside would.
        self._window.viewport.end_group_edit()
        self._window.viewport.history.execute(
            ReparentGroupsCommand(moving, target))
        self._window.viewport.update()
        self.refresh()
        if target is not None:
            self._items[id(target)].setExpanded(True)
        first = self._items.get(id(moving[0]))
        if first is not None:
            self._reveal(first)
            self.tree.setCurrentItem(first, COL_NAME,
                                     QItemSelectionModel.NoUpdate)
            self.tree.scrollToItem(first)
        return True

    def indent(self) -> None:
        """Tab: into the group just above, at the same level."""
        current = self.tree.currentItem()
        group = self._group_of(current)
        if group is None:
            return
        parent = current.parent()
        index = parent.indexOfChild(current) if parent is not None else -1
        above = None
        while index > 0:
            index -= 1
            candidate = parent.child(index)
            if not candidate.isHidden():
                above = self._group_of(candidate)
                break
        if above is None:
            return
        self.reparent(self._selected_groups() or [group], above)

    def outdent(self) -> None:
        """Shift+Tab: out of the group it is in, one level up."""
        group = self._group_of(self.tree.currentItem())
        if group is None:
            return
        scene = self._scene()
        path = outliner.path_to(scene.groups, group)
        if not path:
            return
        self.reparent(self._selected_groups() or [group],
                      path[-2] if len(path) > 1 else None)

    # ---- Columns ---------------------------------------------------------
    def _hidden_columns(self) -> set:
        from PySide6.QtCore import QSettings
        raw = QSettings().value("browser/model_hidden_columns")
        if raw is None:
            return {c for c, _l, shown in OPTIONAL_COLUMNS if not shown}
        if isinstance(raw, str):
            raw = [x for x in raw.split(",") if x]
        out = set()
        for x in raw or ():
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                pass
        return out

    def _apply_column_choice(self) -> None:
        hidden = self._hidden_columns()
        for col, _label, _shown in OPTIONAL_COLUMNS:
            self.tree.setColumnHidden(col, col in hidden)

    def set_column_shown(self, col: int, shown: bool) -> None:
        from PySide6.QtCore import QSettings
        hidden = self._hidden_columns()
        (hidden.discard if shown else hidden.add)(col)
        QSettings().setValue("browser/model_hidden_columns",
                             ",".join(str(c) for c in sorted(hidden)) or ",")
        self._apply_column_choice()

    def _on_header_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        hidden = self._hidden_columns()
        for col, label, _shown in OPTIONAL_COLUMNS:
            act = menu.addAction(tr(label), lambda c=col, on=col in hidden:
                                 self.set_column_shown(c, on))
            act.setCheckable(True)
            act.setChecked(col not in hidden)
        menu.exec(self.tree.header().mapToGlobal(pos))

    # ---- Several rows at once --------------------------------------------
    def assign_layer(self, groups, layer: str) -> None:
        """Put the rows on ``layer`` (made if new) — one undo step."""
        from core.history import AssignLayerCommand
        groups = [g for g in groups if g is not None]
        if not groups or not layer:
            return
        self._window.viewport.history.execute(
            AssignLayerCommand(groups, layer))
        self._window.viewport.update()
        self.refresh()

    def _ask_new_layer(self, groups) -> None:
        from views import prompts
        name, ok = prompts.get_text(self, tr("New layer"),
                                    tr("Layer name:"))
        if ok and name.strip():
            self.assign_layer(groups, name.strip())

    def paint_groups(self, groups, material=None, clear=False) -> None:
        """Paint the rows as a whole with ``material`` (the Paint tool's
        current one by default), or take their paint off — the same as
        painting a group from outside it; one undo step."""
        from core.history import (CompoundCommand, SetFaceMaterialTagCommand,
                                  SetGroupMaterialCommand)
        groups = [g for g in groups if g is not None]
        if not groups:
            return
        if clear:
            cmds = [SetGroupMaterialCommand(g, None) for g in groups]
        else:
            from tools.paint import PaintTool
            if material is None:
                if PaintTool.current_is_default:
                    cmds = [SetGroupMaterialCommand(g, None) for g in groups]
                else:
                    mat = PaintTool.current_material
                    material = PaintTool._current_as_material()
                    cmds = [SetFaceMaterialTagCommand(
                        [], mat.name if mat is not None else None, mat)]
                    cmds += [SetGroupMaterialCommand(g, material)
                             for g in groups]
            else:
                cmds = [SetGroupMaterialCommand(g, material) for g in groups]
        self._window.viewport.history.execute(CompoundCommand(cmds))
        self._window.viewport.update()
        self.refresh()

    def _batch_menu(self, menu, targets) -> None:
        layers = menu.addMenu(tr("Layer"))
        current = {outliner.layer_name(g) for g in targets}
        for ly in self._scene().layers:
            act = layers.addAction(ly.name, lambda n=ly.name:
                                   self.assign_layer(targets, n))
            act.setCheckable(True)
            act.setChecked(current == {ly.name})
        layers.addSeparator()
        from PySide6.QtCore import QTimer
        layers.addAction(tr("New layer…"), lambda: QTimer.singleShot(
            0, lambda: self._ask_new_layer(targets)))
        menu.addAction(tr("Paint with the active material"),
                       lambda: self.paint_groups(targets))
        if any(getattr(g, "material", None) for g in targets):
            menu.addAction(tr("Remove paint"),
                           lambda: self.paint_groups(targets, clear=True))

    def _isolate_targets(self) -> list:
        from core.group import Group
        picked = self._selected_groups()
        if not picked:
            picked = [g for g in self._scene().selection
                      if isinstance(g, Group)]
        return picked

    def isolate(self) -> None:
        """Hide every group but the selected ones and those holding them —
        one undoable step; Show all groups (or undo) brings them back.
        Loose geometry, dimensions and texts stay (#272)."""
        from core.history import HideCommand
        keep = self._isolate_targets()
        if not keep:
            self._window.viewport.flash_status(tr(
                "Select the groups to keep in view first"), 3000)
            return
        hide = outliner.isolate_hides(self._scene().groups, keep)
        if hide:
            self._window.viewport.history.execute(HideCommand(hide,
                                                              hidden=True))
            self._window.viewport.update()
        self.refresh()

    def show_all(self) -> None:
        """Show every hidden group of the tree — one undoable step."""
        from core.history import HideCommand
        hidden = [g for g, _p, _d in outliner.walk(self._scene().groups)
                  if g.hidden]
        if hidden:
            self._window.viewport.history.execute(HideCommand(hidden,
                                                              hidden=False))
            self._window.viewport.update()
        self.refresh()

    def _on_item_changed(self, item, column) -> None:
        if self._updating or column != COL_NAME:
            return
        from core.history import RenameGroupCommand
        group = self._group_of(item)
        if group is None:
            return
        name = item.text(COL_NAME).strip()
        if name and name != group.name:
            self._window.viewport.history.execute(
                RenameGroupCommand(group, name))
            self._window.viewport.update()
        self.refresh()

    def _on_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        item = self.tree.itemAt(pos)
        group = self._group_of(item)
        menu = QMenu(self)
        if group is not None:
            menu.addAction(tr("Rename…"), lambda: self.tree.editItem(
                item, COL_NAME))
            selected = self._selected_groups()
            targets = selected if group in selected else [group]
            menu.addAction(tr("Show") if group.hidden else tr("Hide"),
                           lambda: self.toggle_hidden(targets))
            menu.addAction(tr("Unlock") if getattr(group, "locked", False)
                           else tr("Lock"),
                           lambda: self.toggle_locked(targets))
            menu.addAction(tr("Open for editing"),
                           lambda: self.open_item(item))
            if outliner.path_to(self._scene().groups, group):
                menu.addAction(tr("Move out of the group (Shift+Tab)"),
                               lambda: self.outdent())
            menu.addSeparator()
            self._batch_menu(menu, targets)
        if self._scene().edit_group is not None:
            menu.addAction(tr("Close group"), self.step_out)
        if self._scene().selection:
            menu.addAction(tr("Zoom Selection"),
                           self._window._on_zoom_selection)
        menu.addSeparator()
        if group is not None or self._isolate_targets():
            menu.addAction(tr("Isolate"), self.isolate)
        menu.addAction(tr("Show all groups"), self.show_all)
        menu.addSeparator()
        menu.addAction(tr("Expand all"), self._expand_all)
        menu.addAction(tr("Collapse all"), self._collapse_all)
        menu.exec(self.tree.viewport().mapToGlobal(pos))


# ---- The dock ------------------------------------------------------------------

class ProjectBrowser(QDockWidget):
    """Sidebar tab **Browser**: the model's tree."""

    def __init__(self, window) -> None:
        super().__init__(tr("Browser"), window)
        self.setObjectName("tray_project_browser")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetClosable)
        self._window = window
        self.outliner = OutlinerPanel(window)
        self.setWidget(self.outliner)
        self.setMinimumWidth(240)

    def on_scene_changed(self) -> None:
        self.outliner.on_scene_changed()
