# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Outliner (#219): the model's groups and components as a tree.

Every model here is generated: boxes, nested containers, component copies
and a seeded random tree of ten thousand nodes for the timing."""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

from core import outliner
from core.group import Group, copy_group
from core.mesh import Mesh
from views.outliner import COL_EYE, COL_LAYER, COL_LOCK, COL_TYPE

_app = QApplication.instance() or QApplication([])

_QUADS = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6),
          (0, 2, 6, 4), (1, 5, 7, 3)]


def _box(at=(0.0, 0.0, 0.0), size=0.1) -> Mesh:
    mesh = Mesh()
    x0, y0, z0 = at
    c = [QVector3D(x0 + dx * size, y0 + dy * size, z0 + dz * size)
         for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)]
    for q in _QUADS:
        mesh.add_face([c[k] for k in q])
    return mesh


def _group(name, at=(0.0, 0.0, 0.0)) -> Group:
    return Group(_box(at), name=name)


def _container(name, kids) -> Group:
    """A group of groups — what Make Group over groups builds."""
    g = Group(name=name)
    g.adopt(kids)
    g.component = False
    return g


def _building():
    """Building ▸ Level 1 ▸ (Wall, Slab) and Level 2 ▸ (Wall), plus a
    loose Tree beside it."""
    wall1, slab = _group("Wall", (0, 0, 0)), _group("Slab", (1, 0, 0))
    level1 = _container("Level 1", [wall1, slab])
    level2 = _container("Level 2", [_group("Wall", (0, 0, 3))])
    building = _container("Building", [level1, level2])
    tree = _group("Tree", (5, 0, 0))
    return building, tree


def _window_with(*groups):
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    scene.groups[:] = groups        # without the template's scale figure
    scene.version += 1
    panel = win.project_browser.outliner
    panel.refresh()
    return win, scene, panel


def _close(win):
    win.viewport.scene.end_group_edit()
    win._saved_version = win.viewport.scene.version


def _row(panel, group):
    return panel._items[id(group)]


def _eye(panel, group):
    """Click the row's eye."""
    panel._on_item_clicked(_row(panel, group), COL_EYE)


def _shown(panel, group) -> bool:
    return not _row(panel, group).data(COL_EYE, Qt.UserRole)


def _random_tree(n: int, seed: int = 7) -> list:
    """``n`` groups hung at random under the ones made before them."""
    rnd = random.Random(seed)
    roots: list = []
    made: list = []
    for i in range(n):
        g = Group(Mesh(), name=f"Node {i}")
        g.component = False
        if made and rnd.random() < 0.8:
            parent = rnd.choice(made)
            parent.adopt(list(parent.children) + [g])
            parent.component = False
        else:
            roots.append(g)
        made.append(g)
    return roots


# ---- core/outliner.py ------------------------------------------------------

def test_walk_lists_every_group_at_every_depth():
    building, tree = _building()
    rows = [(g.name, p.name if p else None, d)
            for g, p, d in outliner.walk([building, tree])]
    assert rows == [("Building", None, 0), ("Level 1", "Building", 1),
                    ("Wall", "Level 1", 2), ("Slab", "Level 1", 2),
                    ("Level 2", "Building", 1), ("Wall", "Level 2", 2),
                    ("Tree", None, 0)]


def test_path_to_names_the_containers_to_open():
    building, tree = _building()
    level1 = building.children[0]
    wall = level1.children[0]
    groups = [building, tree]
    assert outliner.path_to(groups, wall) == [building, level1]
    assert outliner.path_to(groups, tree) == []
    assert outliner.path_to(groups, Group(name="elsewhere")) is None


def test_a_random_tree_keeps_every_path_consistent():
    roots = _random_tree(2000)
    nodes = list(outliner.walk(roots))
    assert len(nodes) == 2000
    up = outliner.parents(roots)
    for g, parent, depth in nodes:
        path = outliner.path_to(roots, g)
        assert len(path) == depth
        assert (path[-1] if path else None) is parent is up[id(g)]


def test_the_shape_ignores_names_and_visibility_not_structure():
    building, tree = _building()
    groups = [building, tree]
    shape = outliner.structure(groups)
    building.name = "Tower"
    tree.hidden = True
    assert outliner.structure(groups) == shape
    level2 = building.children[1]
    level2.adopt(list(level2.children) + [_group("Roof")])
    assert outliner.structure(groups) != shape


def test_kind_class_and_copies():
    proto = Group(_box(), name="Chair")
    proto.xform = QMatrix4x4()
    copies = [proto] + [copy_group(proto, QVector3D(i, 0, 0))
                        for i in (1, 2)]
    building, _tree = _building()
    assert outliner.kind(proto) == "component"
    assert outliner.kind(building) == "group"
    assert outliner.instance_counts(copies + [building]) == {
        id(proto.mesh): 3}


# ---- The tray panel --------------------------------------------------------

def test_the_tree_shows_the_whole_model_nested():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    t = panel.tree
    assert t.topLevelItemCount() == 1            # the document
    doc = t.topLevelItem(0)
    assert doc.text(0) == "Untitled" and doc.isExpanded()
    assert doc.childCount() == 2
    top = doc.child(0)
    assert top.text(0) == "Building" and top.text(COL_TYPE) == "Group"
    assert top.text(COL_LAYER) == outliner.layer_name(building)
    assert [top.child(i).text(0) for i in range(top.childCount())] == [
        "Level 1", "Level 2"]
    wall = top.child(0).child(0)
    assert wall.text(0) == "Wall" and wall.text(COL_TYPE) == "Group"
    assert wall.data(COL_TYPE, Qt.UserRole) == "group"
    assert top.data(COL_TYPE, Qt.UserRole) == "group"
    assert not top.icon(0).isNull() and not top.icon(COL_EYE).isNull()
    assert _shown(panel, building)
    _close(win)


def test_component_copies_are_counted():
    proto = Group(_box(), name="Chair")
    proto.xform = QMatrix4x4()
    other = copy_group(proto, QVector3D(1, 0, 0))
    win, scene, panel = _window_with(proto, other)
    assert _row(panel, proto).text(COL_TYPE) == "Component (2 copies)"
    assert _row(panel, proto).data(COL_TYPE, Qt.UserRole) == "component"
    _close(win)


def test_clicking_a_nested_row_opens_its_containers_and_selects_it():
    building, tree = _building()
    level1 = building.children[0]
    wall = level1.children[0]
    win, scene, panel = _window_with(building, tree)
    t = panel.tree
    t.setCurrentItem(_row(panel, wall))
    assert outliner.open_path(scene) == [building, level1]
    assert scene.selection == {wall}
    panel.refresh()
    assert _row(panel, building).font(0).bold()
    assert _row(panel, level1).font(0).bold()
    assert not _row(panel, wall).font(0).bold()
    # A top-level row closes what was open.
    t.setCurrentItem(_row(panel, tree))
    assert scene.edit_group is None
    assert scene.selection == {tree}
    panel.refresh()
    assert not _row(panel, building).font(0).bold()
    _close(win)


def test_moving_to_a_sibling_branch_steps_out_only_where_it_differs():
    building, tree = _building()
    level1, level2 = building.children
    win, scene, panel = _window_with(building, tree)
    panel.tree.setCurrentItem(_row(panel, level1.children[1]))
    assert outliner.open_path(scene) == [building, level1]
    panel.tree.setCurrentItem(_row(panel, level2.children[0]))
    assert outliner.open_path(scene) == [building, level2]
    assert scene.selection == {level2.children[0]}
    _close(win)


def test_a_selection_in_the_view_is_found_in_the_tree():
    building, tree = _building()
    level2 = building.children[1]
    win, scene, panel = _window_with(building, tree)
    assert not _row(panel, building).isExpanded()
    scene.begin_group_edit(building)
    scene.begin_group_edit(level2)
    scene.selection.add(level2.children[0])
    scene.version += 1
    panel.refresh()
    row = _row(panel, level2.children[0])
    assert row.isSelected()
    assert _row(panel, building).isExpanded()
    assert _row(panel, level2).isExpanded()
    assert panel.tree.currentItem() is row
    _close(win)


def test_rename_in_the_tree_is_one_undo_step_and_keeps_the_uid():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    uid = tree.uid
    _row(panel, tree).setText(0, "Oak")
    assert tree.name == "Oak" and tree.uid == uid
    win.viewport.history.undo()
    panel.refresh()
    assert tree.name == "Tree"
    assert _row(panel, tree).text(0) == "Tree"
    _close(win)


def test_the_eye_hides_every_selected_row_at_once():
    building, tree = _building()
    level1 = building.children[0]
    wall, slab = level1.children
    win, scene, panel = _window_with(building, tree)
    panel.tree.setCurrentItem(_row(panel, wall))
    _row(panel, slab).setSelected(True)
    _eye(panel, slab)
    assert wall.hidden and slab.hidden
    assert not _shown(panel, wall) and not _shown(panel, slab)
    win.viewport.history.undo()
    assert not wall.hidden and not slab.hidden
    _close(win)


def test_double_click_opens_and_esc_steps_out_one_level():
    building, tree = _building()
    level1 = building.children[0]
    win, scene, panel = _window_with(building, tree)
    panel.open_item(_row(panel, level1))
    assert outliner.open_path(scene) == [building, level1]
    panel.step_out()
    assert outliner.open_path(scene) == [building]
    panel.step_out()
    assert scene.edit_group is None
    _close(win)


def test_the_keyboard_alone_hides_opens_and_steps_out():
    from PySide6.QtTest import QTest
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    t = panel.tree
    t.setCurrentItem(_row(panel, tree))
    QTest.keyClick(t, Qt.Key_Space)
    assert tree.hidden
    QTest.keyClick(t, Qt.Key_Space)
    assert not tree.hidden
    t.setCurrentItem(_row(panel, building))
    QTest.keyClick(t, Qt.Key_Return)
    assert scene.edit_group is building
    QTest.keyClick(t, Qt.Key_Escape)
    assert scene.edit_group is None
    _close(win)


def test_the_tree_keys_win_over_the_window_shortcuts():
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    for key in (Qt.Key_Space, Qt.Key_Escape, Qt.Key_F2, Qt.Key_Return):
        ev = QKeyEvent(QEvent.ShortcutOverride, key, Qt.NoModifier)
        assert panel.tree.event(ev) and ev.isAccepted()
    ev = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Z, Qt.ControlModifier)
    panel.tree.event(ev)
    assert not ev.isAccepted()          # Ctrl+Z stays the window's undo
    _close(win)


def test_a_hidden_container_cannot_be_entered_from_the_tree():
    building, tree = _building()
    level1 = building.children[0]
    building.hidden = True
    win, scene, panel = _window_with(building, tree)
    panel.tree.setCurrentItem(_row(panel, level1))
    assert scene.edit_group is None
    assert not scene.selection
    _close(win)


def test_rows_update_in_place_and_rebuild_only_when_groups_change():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    row = _row(panel, tree)
    _row(panel, building).setExpanded(True)
    tree.name = "Pine"
    tree.hidden = True
    panel.refresh()
    assert _row(panel, tree) is row
    assert row.text(0) == "Pine" and not _shown(panel, tree)
    extra = _group("Fence", (9, 0, 0))
    scene.groups.append(extra)
    panel.refresh()
    assert _row(panel, tree) is not row             # rebuilt…
    assert _row(panel, building).isExpanded()       # …keeping what was open
    assert _row(panel, extra).text(0) == "Fence"
    scene.groups.remove(extra)
    panel.refresh()
    assert id(extra) not in panel._items
    _close(win)


def test_a_folded_section_waits_until_it_shows():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    assert not panel.isVisible()
    scene.groups.append(_group("Late"))
    win.project_browser.on_scene_changed()
    assert panel._stale
    assert panel.tree.topLevelItem(0).childCount() == 2
    panel.refresh()
    assert panel.tree.topLevelItem(0).childCount() == 3
    _close(win)


def test_an_empty_model_says_so():
    win, scene, panel = _window_with()
    assert panel._empty.isVisibleTo(panel)
    assert panel.tree.topLevelItem(0).childCount() == 0
    _close(win)


def test_ten_thousand_nodes_build_once_and_refresh_quickly():
    roots = _random_tree(10_000)
    win, scene, panel = _window_with()
    scene.groups.extend(roots)
    t0 = time.perf_counter()
    panel.refresh()
    build = time.perf_counter() - t0
    assert len(panel._items) == 10_000
    t0 = time.perf_counter()
    panel.refresh()
    again = time.perf_counter() - t0
    print(f"\n10 000 nodes: build {build * 1000:.0f} ms, "
          f"refresh {again * 1000:.0f} ms")
    assert build < 5.0
    assert again < 1.0
    _close(win)


def test_the_filter_keeps_the_path_to_every_match():
    building, tree = _building()
    level1, level2 = building.children
    win, scene, panel = _window_with(building, tree)
    panel.search.setText("slab")
    assert not _row(panel, level1.children[1]).isHidden()     # the match
    assert not _row(panel, level1).isHidden()                 # its path
    assert _row(panel, level1).isExpanded()
    assert _row(panel, level1.children[0]).isHidden()
    assert _row(panel, level2).isHidden()
    assert _row(panel, tree).isHidden()
    panel.search.setText("")
    assert not any(item.isHidden() for item in panel._items.values())
    _close(win)


def test_the_filter_follows_a_rename():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    panel.search.setText("oak")
    assert _row(panel, tree).isHidden()
    tree.name = "Oak"
    panel.refresh()
    assert not _row(panel, tree).isHidden()
    _close(win)


def test_filter_keep_in_the_core():
    building, tree = _building()
    keep, hit = outliner.filter_keep([building, tree], "wall")
    walls = {id(w) for lvl in building.children for w in lvl.children
             if w.name == "Wall"}
    assert hit == walls
    assert keep == walls | {id(building)} | {id(lvl)
                                             for lvl in building.children}


# ---- Isolate, footer --------------------------------------------------------

def test_isolate_in_the_core_hides_the_siblings_on_the_way_down():
    building, tree = _building()
    level1, level2 = building.children
    wall, slab = level1.children
    hide = outliner.isolate_hides([building, tree], [wall])
    assert {g.name for g in hide} == {"Slab", "Level 2", "Tree"}
    assert outliner.isolate_hides([building, tree], [building]) == [tree]


def test_isolate_and_show_all_are_one_undo_step_each():
    building, tree = _building()
    level1, level2 = building.children
    wall, slab = level1.children
    win, scene, panel = _window_with(building, tree)
    panel.tree.setCurrentItem(_row(panel, wall))
    panel.isolate()
    assert slab.hidden and level2.hidden and tree.hidden
    assert not wall.hidden and not level1.hidden and not building.hidden
    win.viewport.history.undo()
    assert not (slab.hidden or level2.hidden or tree.hidden)
    panel.isolate()
    panel.show_all()
    assert not any(g.hidden for g, _p, _d in outliner.walk(scene.groups))
    win.viewport.history.undo()
    assert tree.hidden
    _close(win)


def test_the_footer_counts_and_follows_the_filter():
    building, tree = _building()
    proto = Group(_box(), name="Chair")
    proto.xform = QMatrix4x4()
    tree.hidden = True
    win, scene, panel = _window_with(building, tree, proto)
    assert panel.summary.text() == "7 groups · 1 components · 1 hidden"
    panel.search.setText("wall")
    assert panel.summary.text() == "2 of 8 match"
    _close(win)


# ---- Re-nesting (drag and drop, Tab / Shift+Tab) ----------------------------

def _world_points(groups, group) -> list:
    """Every vertex of ``group``'s own mesh, in world coordinates, rounded."""
    m = outliner.world_matrix(groups, group)
    out = []
    for v in group.mesh.vertices:
        p = m.map(v.position) if m is not None else v.position
        out.append((round(p.x(), 6), round(p.y(), 6), round(p.z(), 6)))
    return sorted(out)


def _moved_container():
    """A container moved and turned: its frame is not the world's."""
    m = QMatrix4x4()
    m.translate(QVector3D(10, 5, 0))
    m.rotate(30, 0, 0, 1)
    kid = Group(_box((0, 0, 0)), name="Kid")
    kid.xform = QMatrix4x4()
    kid.component = False
    box = _container("Shelf", [kid])
    box.xform = m
    return box


def test_a_classic_group_dropped_into_a_turned_group_stays_put():
    from core.history import ReparentGroupsCommand
    from core.scene import Scene
    scene = Scene()
    shelf = _moved_container()
    loose = _group("Loose", (3, 4, 0))
    scene.groups[:] = [shelf, loose]
    before = _world_points(scene.groups, loose)
    mesh0 = loose.mesh
    cmd = ReparentGroupsCommand([loose], shelf)
    cmd.do(scene)
    assert loose in shelf.children and loose not in scene.groups
    assert _world_points(scene.groups, loose) == before
    cmd.undo(scene)
    assert scene.groups == [shelf, loose] and shelf.children[-1] is not loose
    assert loose.mesh is mesh0 and loose.xform is None


def test_an_instance_taken_out_keeps_its_place_and_children():
    from core.history import ReparentGroupsCommand
    from core.scene import Scene
    scene = Scene()
    shelf = _moved_container()
    kid = shelf.children[0]
    scene.groups[:] = [shelf]
    before = _world_points(scene.groups, kid)
    cmd = ReparentGroupsCommand([kid], None)
    cmd.do(scene)
    assert scene.groups == [shelf, kid] and not shelf.children
    assert _world_points(scene.groups, kid) == before
    cmd.undo(scene)
    assert shelf.children == [kid] and scene.groups == [shelf]
    assert _world_points(scene.groups, kid) == before


def test_a_plain_target_becomes_a_group_of_groups_not_a_component():
    from core.history import ReparentGroupsCommand
    from core.scene import Scene
    scene = Scene()
    a, b = _group("A"), _group("B", (2, 0, 0))
    scene.groups[:] = [a, b]
    cmd = ReparentGroupsCommand([b], a)
    cmd.do(scene)
    assert a.xform is not None and not a.is_component()
    assert outliner.kind(a) == "group"
    cmd.undo(scene)
    assert a.xform is None


def test_moving_a_group_and_its_child_moves_the_group_once():
    building, tree = _building()
    level1 = building.children[0]
    assert outliner.topmost([building, tree],
                            [level1.children[0], level1, tree]) == [
        level1, tree]


def test_what_cannot_be_re_nested():
    building, tree = _building()
    level1 = building.children[0]
    groups = [building, tree]
    assert outliner.reparent_problem(groups, [building], level1) == "cycle"
    assert outliner.reparent_problem(groups, [level1], level1) == "cycle"
    chair = Group(_box(), name="Chair")
    chair.xform = QMatrix4x4()
    part = Group(_box(), name="Seat")
    part.xform = QMatrix4x4()
    part.component = False
    chair.adopt([part])
    chair.component = True
    groups = [building, tree, chair]
    assert outliner.reparent_problem(groups, [tree], chair) == "component"
    assert outliner.reparent_problem(groups, [part], None) == "component"
    tree.locked = True
    assert outliner.reparent_problem(groups, [tree], building) == "locked"
    assert outliner.reparent_problem(groups, [level1], None) is None


def test_dropping_rows_on_a_group_is_one_undo_step():
    building, tree = _building()
    level2 = building.children[1]
    win, scene, panel = _window_with(building, tree)
    assert panel.reparent([tree], level2)
    assert tree in level2.children
    assert _row(panel, tree).parent() is _row(panel, level2)
    assert _row(panel, level2).isExpanded()
    win.viewport.history.undo()
    panel.refresh()
    assert tree in scene.groups
    assert _row(panel, tree).parent() is panel.tree.topLevelItem(0)
    _close(win)


def test_a_refused_drop_changes_nothing():
    building, tree = _building()
    level1 = building.children[0]
    win, scene, panel = _window_with(building, tree)
    steps = len(win.viewport.history.undo_stack)
    assert not panel.reparent([building], level1)
    assert level1 in building.children and building in scene.groups
    assert len(win.viewport.history.undo_stack) == steps
    _close(win)


def test_tab_and_shift_tab_move_in_and_out():
    from PySide6.QtTest import QTest
    building, tree = _building()
    fence = _group("Fence", (8, 0, 0))
    win, scene, panel = _window_with(building, tree, fence)
    t = panel.tree
    t.setCurrentItem(_row(panel, fence))
    QTest.keyClick(t, Qt.Key_Tab)              # into «Tree», the row above
    assert fence in tree.children
    t.setCurrentItem(_row(panel, fence))
    QTest.keyClick(t, Qt.Key_Backtab)          # back out to the model
    assert fence in scene.groups and fence not in tree.children
    _close(win)


# ---- Lock --------------------------------------------------------------------

def test_a_locked_group_cannot_be_picked_nor_what_it_holds():
    from core.scene import Scene
    building, tree = _building()
    scene = Scene()
    scene.groups[:] = [building, tree]
    building.locked = True
    assert not scene.entity_selectable(building)
    proxy = Group(name="placement")
    proxy.owner = building                     # what the viewport picks
    assert not scene.entity_selectable(proxy)
    assert scene.entity_selectable(tree)


def test_the_padlock_locks_and_unlocks_in_one_undo_step():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    panel._on_item_clicked(_row(panel, tree), COL_LOCK)
    assert tree.locked
    assert _row(panel, tree).data(COL_LOCK, Qt.UserRole)
    panel.tree.setCurrentItem(_row(panel, tree))
    assert not scene.selection                 # a locked row selects nothing
    win.viewport.history.undo()
    panel.refresh()
    assert not tree.locked
    assert not _row(panel, tree).data(COL_LOCK, Qt.UserRole)
    _close(win)


def test_nothing_opens_through_a_locked_group():
    building, tree = _building()
    level1 = building.children[0]
    building.locked = True
    win, scene, panel = _window_with(building, tree)
    panel.tree.setCurrentItem(_row(panel, level1.children[0]))
    assert scene.edit_group is None and not scene.selection
    panel.open_item(_row(panel, building))
    assert scene.edit_group is None
    _close(win)


def test_the_lock_is_saved_in_the_igz_and_kept_by_copies(tmp_path):
    from core.scene import Scene
    from formats.igz import load_into, save_scene
    building, tree = _building()
    tree.locked = True
    assert copy_group(tree).locked
    scene = Scene()
    scene.groups[:] = [building, tree]
    path = tmp_path / "locked.igz"
    save_scene(scene, path)
    back = Scene()
    load_into(back, path)
    by_name = {g.name: g for g, _p, _d in outliner.walk(back.groups)}
    assert by_name["Tree"].locked and not by_name["Building"].locked


# ---- Column widths -----------------------------------------------------------


def test_the_name_column_width_is_the_users_and_is_remembered():
    from PySide6.QtWidgets import QHeaderView
    win, scene, panel = _window_with()
    head = panel.tree.header()
    assert head.sectionResizeMode(0) == QHeaderView.Interactive
    head.resizeSection(0, 321)
    _close(win)
    win2, scene2, panel2 = _window_with()
    assert panel2.tree.header().sectionSize(0) == 321
    _close(win2)


# ---- 8 · What an extension says a group is ------------------------------------

def test_an_extension_names_its_groups_in_the_type_column():
    from views.extension_api import ExtensionApp
    building, tree = _building()
    tree.ext = {"stairs": {"steps": 14}}
    win, scene, panel = _window_with(building, tree)
    app = ExtensionApp(win, "stairs")
    app.add_outliner_kind(lambda g: {
        "type": "Stair", "props": [("Steps", g.ext["stairs"]["steps"])]}
        if "stairs" in (g.ext or {}) else None)
    row = _row(panel, tree)
    assert row.text(COL_TYPE) == "Stair"
    assert row.toolTip(COL_TYPE) == "Steps: 14"
    assert _row(panel, building).text(COL_TYPE) == "Group"   # not its own
    panel.search.setText("stair")
    assert not row.isHidden() and _row(panel, building).isHidden()
    _close(win)


def test_a_failing_kind_provider_is_skipped():
    building, tree = _building()
    win, scene, panel = _window_with(building, tree)
    win._outliner_kinds = [lambda g: 1 / 0,
                           lambda g: {"type": "Thing"}]
    panel._shape = None
    panel.refresh()
    assert _row(panel, tree).text(COL_TYPE) == "Thing"
    assert outliner.custom_kind(tree, [lambda g: None]) is None
    assert outliner.custom_kind(tree, [lambda g: {"props": []}]) is None
    _close(win)


# ---- 9 · Columns and several rows at once -------------------------------------

def test_the_header_shows_and_hides_columns_and_remembers():
    from views.outliner import COL_COPIES, COL_MATERIAL
    building, tree = _building()
    proto = Group(_box(), name="Chair")
    proto.xform = QMatrix4x4()
    other = copy_group(proto, QVector3D(1, 0, 0))
    tree.material = {"color": [1.0, 0.0, 0.0]}
    win, scene, panel = _window_with(building, tree, proto, other)
    t = panel.tree
    assert t.isColumnHidden(COL_MATERIAL)
    assert not t.isColumnHidden(COL_TYPE)
    panel.set_column_shown(COL_MATERIAL, True)
    panel.set_column_shown(COL_COPIES, True)
    panel.set_column_shown(COL_LAYER, False)
    assert _row(panel, tree).text(COL_MATERIAL) == "#ff0000"
    assert _row(panel, proto).text(COL_COPIES) == "2"
    _close(win)
    win2, scene2, panel2 = _window_with()
    assert not panel2.tree.isColumnHidden(COL_MATERIAL)
    assert panel2.tree.isColumnHidden(COL_LAYER)
    panel2.set_column_shown(COL_LAYER, True)           # leave it as found
    for col in (COL_MATERIAL, COL_COPIES):
        panel2.set_column_shown(col, False)
    _close(win2)


def test_several_rows_go_to_a_layer_in_one_step():
    building, tree = _building()
    level1 = building.children[0]
    wall, slab = level1.children
    win, scene, panel = _window_with(building, tree)
    panel.assign_layer([wall, slab], "Structure")
    assert outliner.layer_name(wall) == "Structure" == \
        outliner.layer_name(slab)
    assert _row(panel, slab).text(COL_LAYER) == "Structure"
    win.viewport.history.undo()
    assert outliner.layer_name(wall) != "Structure"
    _close(win)


def test_several_rows_painted_and_unpainted_in_one_step():
    building, tree = _building()
    level1 = building.children[0]
    wall, slab = level1.children
    win, scene, panel = _window_with(building, tree)
    red = {"color": [0.8, 0.1, 0.1]}
    panel.paint_groups([wall, slab], material=red)
    assert wall.material == red and slab.material == red
    panel.paint_groups([wall, slab], clear=True)
    assert wall.material is None and slab.material is None
    win.viewport.history.undo()
    assert wall.material == red and slab.material == red
    _close(win)


# ---- World bounds ------------------------------------------------------------


def test_world_bounds_follow_the_matrices_down_the_tree():
    shelf = _moved_container_for_bounds()
    lo, hi = outliner.world_bounds([shelf], shelf.children[0])
    assert abs(lo[0] - 10.0) < 1e-6 and abs(lo[2] - 2.0) < 1e-6
    assert abs(hi[0] - 10.1) < 1e-6
    assert outliner.world_bounds([Group(name="empty")],
                                 Group(name="empty")) is None


def _moved_container_for_bounds():
    m = QMatrix4x4()
    m.translate(QVector3D(10, 0, 2))
    kid = Group(_box((0, 0, 0)), name="Kid")
    kid.xform = QMatrix4x4()
    kid.component = False
    box = _container("Shelf", [kid])
    box.xform = m
    return box
