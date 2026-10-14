# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The model's tree of groups and components, read for the Browser.

Qt-free: the browser's tabs (``views/outliner.py``) ask these questions and
the tests ask them without a window. Nothing here changes the model —
renaming, hiding and opening go through the usual commands and the
viewport, so the Outliner never has a state of its own to fall out of
step with.

A node IS its :class:`~core.group.Group`. Rows are matched to groups by
``uid``, the identity that survives save, load, rename and undo (scenes
remember their hidden objects by it too), never by their place in the
tree.
"""
from __future__ import annotations


def walk(groups, parent=None, depth: int = 0):
    """``(group, parent, depth)`` for every group, depth first, in the
    order the document holds them."""
    for g in groups:
        yield g, parent, depth
        yield from walk(getattr(g, "children", None) or (), g, depth + 1)


def parents(groups) -> dict:
    """``{id(group): parent}`` for every group (``None`` at the top)."""
    return {id(g): p for g, p, _d in walk(groups)}


def path_to(groups, target) -> list | None:
    """The containers from the top of the model down to ``target``'s
    parent — what has to be open for ``target`` to be picked — or ``None``
    when ``target`` is not in the model."""
    up = parents(groups)
    if id(target) not in up:
        return None
    path = []
    p = up[id(target)]
    while p is not None:
        path.append(p)
        p = up.get(id(p))
    path.reverse()
    return path


def structure(groups) -> tuple:
    """A fingerprint of the tree's SHAPE: which groups, under which parent,
    in which order. Equal fingerprints mean the rows can be updated in
    place; a different one means rows came or went."""
    return tuple((id(g), id(p) if p is not None else 0)
                 for g, p, _d in walk(groups))


def open_path(scene) -> list:
    """The groups open for editing, outermost first (empty at the model)."""
    return [lvl["group"] for lvl in (getattr(scene, "_edit_stack", None)
                                     or ())]


def kind(group) -> str:
    """What a node is, as a short key: ``"component"`` or ``"group"`` —
    and the more specific ``"image"`` and ``"text"`` for the containers
    the Face-me image and 3D text tools make."""
    if getattr(group, "billboard", False):
        return "image"
    if getattr(group, "text3d", None):
        return "text"
    return "component" if group.is_component() else "group"



def instance_counts(groups) -> dict:
    """``{id(mesh): copies}`` over the whole tree — how many placements
    draw each component definition."""
    counts: dict = {}
    for g, _p, _d in walk(groups):
        if g.is_component():
            counts[id(g.mesh)] = counts.get(id(g.mesh), 0) + 1
    return counts


def layer_name(group) -> str:
    """The layer the group is on (the default layer's name when none)."""
    from core.layers import layer_of
    return layer_of(group)


def matches(group, query: str, type_text: str = "") -> bool:
    """Whether ``query`` (already casefolded) is in the group's name, its
    type as the tree shows it or its layer."""
    if not query:
        return True
    return any(query in str(text).casefold() for text in (
        group.name or "", type_text, layer_name(group)))


def filter_keep(groups, query: str, type_of=lambda g: "") -> tuple:
    """``(keep, hit)``: the ids of the groups a filter by ``query`` shows —
    every match and the containers on the way down to it — and of the
    matches themselves (their containers unfold to reveal them)."""
    nodes = list(walk(groups))
    hit = {id(g) for g, _p, _d in nodes if matches(g, query, type_of(g))}
    keep = set(hit)
    for g, p, _d in reversed(nodes):        # children before their parents
        if id(g) in keep and p is not None:
            keep.add(id(p))
    return keep, hit


# ---- Sheets (the 2D side) ---------------------------------------------------








def isolate_hides(groups, keep) -> list:
    """What Isolate hides so only ``keep`` (and what holds it) shows: at
    every level on the way down to a kept group, the siblings that hold
    nothing kept. Groups already hidden are left as they are."""
    keep_ids = {id(g) for g in keep}
    up = parents(groups)
    holders = set(keep_ids)
    for g in keep:
        p = up.get(id(g))
        while p is not None:
            holders.add(id(p))
            p = up.get(id(p))
    hide = []
    for g, p, _d in walk(groups):
        if id(g) in holders or g.hidden:
            continue
        if p is None or (id(p) in holders and id(p) not in keep_ids):
            hide.append(g)
    return hide


# ---- Re-nesting -------------------------------------------------------------

def world_matrix(groups, group):
    """The matrix that takes ``group``'s own coordinates to the world, or
    ``None`` when nothing on its chain is transformed (the model itself,
    ``group=None``, is the world)."""
    if group is None:
        return None
    from core.group import iter_placements
    for top in groups:
        for placed, m in iter_placements(top):
            if placed is group:
                return m
    return None


def compose(a, b):
    """``a * b`` where ``None`` stands for the identity."""
    if a is None:
        return b
    if b is None:
        return a
    return a * b


def topmost(groups, chosen) -> list:
    """``chosen`` without the ones inside another chosen group — those
    travel with it — in document order."""
    ids = {id(g) for g in chosen}
    up = parents(groups)
    out = []
    for g, _p, _d in walk(groups):
        if id(g) not in ids:
            continue
        p = up.get(id(g))
        while p is not None and id(p) not in ids:
            p = up.get(id(p))
        if p is None:
            out.append(g)
    return out


def in_component(groups, group) -> bool:
    """Whether ``group`` is a component or sits inside one."""
    up = parents(groups)
    g = group
    while g is not None:
        if g.is_component():
            return True
        g = up.get(id(g))
    return False


def reparent_problem(groups, chosen, target) -> str | None:
    """Why ``chosen`` cannot go into ``target`` (``None``: the model) —
    ``"cycle"``, ``"component"``, ``"locked"`` — or ``None`` when it can
    (also when there is nothing to move)."""
    up = parents(groups)
    moving = topmost(groups, chosen)
    p = target
    while p is not None:
        if any(p is g for g in moving):
            return "cycle"
        p = up.get(id(p))
    if target is not None and in_component(groups, target):
        return "component"
    for g in moving:
        old = up.get(id(g))
        if old is not None and in_component(groups, old):
            return "component"
        if getattr(g, "locked", False):
            return "locked"
    if target is not None and getattr(target, "locked", False):
        return "locked"
    return None


def needs_moving(groups, chosen, target) -> list:
    """The groups of ``chosen`` (topmost) not already directly in
    ``target``."""
    up = parents(groups)
    return [g for g in topmost(groups, chosen) if up.get(id(g)) is not target]


def locked_on_path(groups, group) -> bool:
    """Whether ``group`` or a container above it is locked."""
    up = parents(groups)
    g = group
    while g is not None:
        if getattr(g, "locked", False):
            return True
        g = up.get(id(g))
    return False


# ---- Section planes -----------------------------------------------------------

#: A plane's four modes, as ``(cut, frame)``.
SECTION_MODES = {"both": (True, True), "cut": (True, False),
                 "frame": (False, True), "off": (False, False)}




# ---- What extensions say a group is -----------------------------------------

def custom_kind(group, providers) -> dict | None:
    """What an extension says ``group`` is — the first provider that
    answers: ``{"type": "Window", "props": [("Panes", "3 × 2"), ...]}``
    (``props`` optional). A provider that raises is logged and skipped:
    an extension cannot break the tree."""
    for fn in providers or ():
        try:
            out = fn(group)
        except Exception:                           # noqa: BLE001
            import logging
            logging.getLogger("ingetrazo.plugins").exception(
                "outliner kind provider failed")
            continue
        if isinstance(out, dict) and out.get("type"):
            props = []
            for pair in out.get("props") or ():
                try:
                    label, value = pair
                except (TypeError, ValueError):
                    continue
                props.append((str(label), str(value)))
            return {"type": str(out["type"]), "props": props}
    return None


def material_name(group) -> str:
    """The paint the container wears as a whole, as a person names it
    ('' when it has none)."""
    from core.parts import _material_label
    return _material_label(getattr(group, "material", None)) or ""


# ---- A plan of a group ----------------------------------------------------------

def world_bounds(groups, group):
    """``(lo, hi)`` world corners of ``group`` and everything it holds, as
    ``(x, y, z)`` tuples — or ``None`` when it holds no geometry."""
    import numpy as np
    from core.group import iter_placements
    up = parents(groups)
    base = world_matrix(groups, up.get(id(group)))
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for g, m in iter_placements(group, base):
        verts = getattr(g.mesh, "vertices", None) or ()
        if not verts:
            continue
        pts = [m.map(v.position) if m is not None else v.position
               for v in verts]
        arr = np.array([(p.x(), p.y(), p.z()) for p in pts])
        lo = np.minimum(lo, arr.min(axis=0))
        hi = np.maximum(hi, arr.max(axis=0))
    if not np.isfinite(lo).all():
        return None
    return tuple(lo.tolist()), tuple(hi.tolist())


def unique_name(base: str, taken) -> str:
    """``base``, or ``base 2``, ``base 3``… — the first one not taken."""
    taken = set(taken)
    if base not in taken:
        return base
    n = 2
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"
