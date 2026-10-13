# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SVG import — a 2D drawing (a logo, a name, a cut outline) brought in as
flat geometry on the ground, ready for Push/Pull.

What comes in:

- ``path`` (every command, absolute and relative, arcs included), ``rect``
  (rounded corners too), ``circle``, ``ellipse``, ``line``, ``polyline``,
  ``polygon`` and ``use``, through nested ``g``/``svg`` and their
  ``transform``\\ s;
- every **closed** contour becomes the boundary of a **face** on z = 0,
  nested by the even-odd rule: a contour inside another is its hole (the
  counter of an "O"), a contour inside that hole is a face again;
- **open** paths become plain edges.

Left out: anything hidden (``display:none``), ``defs``/``clipPath``/
``mask``/``pattern``/``marker`` content (unless placed by ``use``), images,
and ``text`` — convert text to paths first (Inkscape: Path ▸ Object to
Path). Overlapping, separate shapes are not merged: each keeps its own face.

Sizes are real: the root's ``width``/``height`` with their unit and its
``viewBox`` say how many millimetres a user unit is; without units a user
unit is a CSS pixel, 1/96 in. SVG's y runs down, the model's y runs up, so
the drawing is mirrored back to read the right way seen from above.

Curves are flattened to straight segments no farther than ``tolerance`` mm
from the true curve, and the segments of each curved run are tagged as one
curve, so Push/Pull makes their sides smooth. Points closer than the
engine's 0.1 mm weld are merged.

Pure Python (no third-party parser); ``defusedxml`` is used when present.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Millimetres per unit for the root's width/height (CSS units).
_UNIT_MM = {"": 25.4 / 96.0, "px": 25.4 / 96.0, "pt": 25.4 / 72.0,
            "pc": 25.4 / 6.0, "mm": 1.0, "cm": 10.0, "in": 25.4,
            "q": 0.25}

#: Closer than this (mm) two points are one: the engine welds at 0.1 mm.
MIN_STEP = 0.15
#: Contours smaller than this (mm, bounding-box side) are specks: skipped.
MIN_SIZE = 0.3
#: Default flattening tolerance (mm).
TOLERANCE = 0.05

_SKIP_TAGS = {"defs", "clipPath", "mask", "pattern", "marker", "symbol",
              "linearGradient", "radialGradient", "filter", "style",
              "script", "metadata", "title", "desc", "text", "image",
              "foreignObject"}

Affine = tuple  # (a, b, c, d, e, f): x' = a x + c y + e, y' = b x + d y + f
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


class SvgError(ValueError):
    """The file is not an SVG we can read; the message is for the user."""


@dataclass
class Contour:
    """A polyline in millimetres (y up). ``curved[i]`` says whether the
    segment from point ``i`` to the next came from a curve."""

    points: list = field(default_factory=list)
    curved: list = field(default_factory=list)
    closed: bool = False


@dataclass
class Drawing:
    contours: list
    skipped: dict

    def bounds(self):
        xs = [p[0] for c in self.contours for p in c.points]
        ys = [p[1] for c in self.contours for p in c.points]
        if not xs:
            return None
        return (min(xs), min(ys)), (max(xs), max(ys))

    def size(self) -> tuple[float, float]:
        b = self.bounds()
        if b is None:
            return 0.0, 0.0
        return b[1][0] - b[0][0], b[1][1] - b[0][1]


# ---- Affine transforms -----------------------------------------------------

def _mul(m: Affine, n: Affine) -> Affine:
    """``m`` after ``n`` (apply ``n`` first)."""
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2,
            a * c2 + c * d2, b * c2 + d * d2,
            a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _apply(m: Affine, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_NUM_RE = re.compile(_NUM)
_TRANSFORM_RE = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)"
                           r"\s*\(([^)]*)\)")


def parse_transform(text: str | None) -> Affine:
    m = _IDENTITY
    if not text:
        return m
    for name, args in _TRANSFORM_RE.findall(text):
        v = [float(x) for x in _NUM_RE.findall(args)]
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate" and v:
            t = (1.0, 0.0, 0.0, 1.0, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale" and v:
            t = (v[0], 0.0, 0.0, v[1] if len(v) > 1 else v[0], 0.0, 0.0)
        elif name == "rotate" and v:
            r = math.radians(v[0])
            cs, sn = math.cos(r), math.sin(r)
            t = (cs, sn, -sn, cs, 0.0, 0.0)
            if len(v) == 3:
                cx, cy = v[1], v[2]
                t = _mul((1, 0, 0, 1, cx, cy), _mul(t, (1, 0, 0, 1, -cx, -cy)))
        elif name == "skewX" and v:
            t = (1.0, 0.0, math.tan(math.radians(v[0])), 1.0, 0.0, 0.0)
        elif name == "skewY" and v:
            t = (1.0, math.tan(math.radians(v[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        m = _mul(m, t)
    return m


# ---- Path data -------------------------------------------------------------

_CMD_RE = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|(" + _NUM + r")|([,\s]+)")
_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2,
         "A": 7, "Z": 0}


def _tokens(d: str):
    """Commands and numbers; an arc's two flags may be written run
    together ("a5 5 0 105 5"), so numbers are split per flag where due."""
    pos = 0
    out = []
    while pos < len(d):
        m = _CMD_RE.match(d, pos)
        if m is None:
            raise SvgError(f"Unreadable path data near «{d[pos:pos + 12]}»")
        if m.group(1):
            out.append(m.group(1))
        elif m.group(2):
            out.append(float(m.group(2)))
            out[-1] = (out[-1], m.group(2))
        pos = m.end()
    return out


def _path_segments(d: str):
    """Yield subpaths of ``("M", p) / ("L", p) / ("C", c1, c2, p) /
    ("Z",)`` in user units (quadratics raised to cubics, arcs converted)."""
    toks = _tokens(d)
    i = 0
    cmd = None
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    last_c = None          # last cubic control point (for S)
    last_q = None          # last quadratic control point (for T)
    out = []

    def nums(n):
        nonlocal i
        vals = []
        while len(vals) < n:
            if i >= len(toks) or isinstance(toks[i], str):
                raise SvgError("A path command is missing its numbers")
            vals.append(toks[i][0])
            i += 1
        return vals

    def arc_args():
        """rx ry rot large sweep x y — the flags may be glued to what
        follows them ("0 105" → 1, 0, 5)."""
        nonlocal i
        vals = nums(3)
        flags = []
        while len(flags) < 2:
            if i >= len(toks) or isinstance(toks[i], str):
                raise SvgError("An arc is missing its flags")
            value, text = toks[i]
            text = text.lstrip("+")
            if text and text[0] in "01" and len(text) > 1 and \
                    not text.startswith(("0.", "1.")):
                flags.append(float(text[0]))
                rest = text[1:]
                toks[i] = (float(rest), rest)
            else:
                flags.append(value)
                i += 1
        return vals + flags + nums(2)

    while i < len(toks):
        t = toks[i]
        if isinstance(t, str):
            cmd = t
            i += 1
            if cmd in "Zz":
                out.append(("Z",))
                cur = start
                last_c = last_q = None
                continue
        elif cmd is None:
            raise SvgError("Path data must start with a move (M)")
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = cur if rel else (0.0, 0.0)
        if c == "M":
            x, y = nums(2)
            cur = start = (x + ox, y + oy)
            out.append(("M", cur))
            cmd = "l" if rel else "L"        # further pairs are lines
            last_c = last_q = None
        elif c == "L":
            x, y = nums(2)
            cur = (x + ox, y + oy)
            out.append(("L", cur))
            last_c = last_q = None
        elif c == "H":
            (x,) = nums(1)
            cur = (x + ox, cur[1])
            out.append(("L", cur))
            last_c = last_q = None
        elif c == "V":
            (y,) = nums(1)
            cur = (cur[0], y + (cur[1] if rel else 0.0))
            out.append(("L", cur))
            last_c = last_q = None
        elif c == "C":
            v = nums(6)
            c1 = (v[0] + ox, v[1] + oy)
            c2 = (v[2] + ox, v[3] + oy)
            p = (v[4] + ox, v[5] + oy)
            out.append(("C", c1, c2, p))
            cur, last_c, last_q = p, c2, None
        elif c == "S":
            v = nums(4)
            c1 = (2 * cur[0] - last_c[0], 2 * cur[1] - last_c[1]) \
                if last_c else cur
            c2 = (v[0] + ox, v[1] + oy)
            p = (v[2] + ox, v[3] + oy)
            out.append(("C", c1, c2, p))
            cur, last_c, last_q = p, c2, None
        elif c in "QT":
            if c == "Q":
                v = nums(4)
                q = (v[0] + ox, v[1] + oy)
                p = (v[2] + ox, v[3] + oy)
            else:
                v = nums(2)
                q = (2 * cur[0] - last_q[0], 2 * cur[1] - last_q[1]) \
                    if last_q else cur
                p = (v[0] + ox, v[1] + oy)
            c1 = (cur[0] + 2 / 3 * (q[0] - cur[0]),
                  cur[1] + 2 / 3 * (q[1] - cur[1]))
            c2 = (p[0] + 2 / 3 * (q[0] - p[0]), p[1] + 2 / 3 * (q[1] - p[1]))
            out.append(("C", c1, c2, p))
            cur, last_q, last_c = p, q, None
        elif c == "A":
            rx, ry, rot, large, sweep, x, y = arc_args()
            p = (x + ox, y + oy)
            for seg in _arc_to_cubics(cur, p, rx, ry, rot, bool(large),
                                      bool(sweep)):
                out.append(seg)
            cur = p
            last_c = last_q = None
    return out


def _arc_to_cubics(p0, p1, rx, ry, phi_deg, large, sweep):
    """SVG endpoint arc → cubic Béziers (at most 90° each)."""
    if p0 == p1:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-12 or ry < 1e-12:
        return [("L", p1)]
    phi = math.radians(phi_deg % 360.0)
    cs, sn = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1 = cs * dx + sn * dy
    y1 = -sn * dx + cs * dy
    lam = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
    if lam > 1.0:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    k = math.sqrt(max(0.0, num / den)) if den > 0 else 0.0
    if large == sweep:
        k = -k
    cx1, cy1 = k * rx * y1 / ry, -k * ry * x1 / rx
    cx = cs * cx1 - sn * cy1 + (p0[0] + p1[0]) / 2.0
    cy = sn * cx1 + cs * cy1 + (p0[1] + p1[1]) / 2.0

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = ang(1.0, 0.0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = ang((x1 - cx1) / rx, (y1 - cy1) / ry,
             (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(1, int(math.ceil(abs(dt) / (math.pi / 2) - 1e-9)))
    step = dt / n
    alpha = 4.0 / 3.0 * math.tan(step / 4.0)

    def pt(t):
        x, y = rx * math.cos(t), ry * math.sin(t)
        return (cs * x - sn * y + cx, sn * x + cs * y + cy)

    def deriv(t):
        x, y = -rx * math.sin(t), ry * math.cos(t)
        return (cs * x - sn * y, sn * x + cs * y)

    out = []
    t = t1
    for k_ in range(n):
        a, b = t, t + step
        pa, pb = pt(a), pt(b)
        da, db = deriv(a), deriv(b)
        c1 = (pa[0] + alpha * da[0], pa[1] + alpha * da[1])
        c2 = (pb[0] - alpha * db[0], pb[1] - alpha * db[1])
        end = p1 if k_ == n - 1 else pb
        out.append(("C", c1, c2, end))
        t = b
    return out


# ---- Basic shapes as path segments -----------------------------------------

def _f(el, name, default=0.0) -> float:
    v = el.get(name)
    if v is None:
        return default
    m = _NUM_RE.match(v.strip())
    return float(m.group(0)) if m else default


def _ellipse_segments(cx, cy, rx, ry):
    k = 0.5522847498307936
    p = [(cx + rx, cy), (cx, cy + ry), (cx - rx, cy), (cx, cy - ry)]
    out = [("M", p[0])]
    for i in range(4):
        a, b = p[i], p[(i + 1) % 4]
        da = ((a[1] - cy) / ry * -rx if ry else 0.0,
              (a[0] - cx) / rx * ry if rx else 0.0)
        db = ((b[1] - cy) / ry * -rx if ry else 0.0,
              (b[0] - cx) / rx * ry if rx else 0.0)
        out.append(("C", (a[0] + k * da[0], a[1] + k * da[1]),
                    (b[0] - k * db[0], b[1] - k * db[1]), b))
    out.append(("Z",))
    return out


def _shape_segments(el, tag: str):
    if tag == "path":
        return _path_segments(el.get("d") or "")
    if tag == "rect":
        x, y = _f(el, "x"), _f(el, "y")
        w, h = _f(el, "width"), _f(el, "height")
        if w <= 0 or h <= 0:
            return []
        rx = el.get("rx")
        ry = el.get("ry")
        rxv = _f(el, "rx") if rx is not None else None
        ryv = _f(el, "ry") if ry is not None else None
        if rxv is None:
            rxv = ryv or 0.0
        if ryv is None:
            ryv = rxv
        rxv, ryv = min(max(rxv, 0.0), w / 2), min(max(ryv, 0.0), h / 2)
        if rxv <= 0 or ryv <= 0:
            return [("M", (x, y)), ("L", (x + w, y)), ("L", (x + w, y + h)),
                    ("L", (x, y + h)), ("Z",)]
        d = (f"M{x + rxv},{y} H{x + w - rxv} "
             f"A{rxv},{ryv} 0 0 1 {x + w},{y + ryv} V{y + h - ryv} "
             f"A{rxv},{ryv} 0 0 1 {x + w - rxv},{y + h} H{x + rxv} "
             f"A{rxv},{ryv} 0 0 1 {x},{y + h - ryv} V{y + ryv} "
             f"A{rxv},{ryv} 0 0 1 {x + rxv},{y} Z")
        return _path_segments(d)
    if tag == "circle":
        r = _f(el, "r")
        return _ellipse_segments(_f(el, "cx"), _f(el, "cy"), r, r) \
            if r > 0 else []
    if tag == "ellipse":
        rx, ry = _f(el, "rx"), _f(el, "ry")
        return _ellipse_segments(_f(el, "cx"), _f(el, "cy"), rx, ry) \
            if rx > 0 and ry > 0 else []
    if tag == "line":
        return [("M", (_f(el, "x1"), _f(el, "y1"))),
                ("L", (_f(el, "x2"), _f(el, "y2")))]
    if tag in ("polyline", "polygon"):
        v = [float(x) for x in _NUM_RE.findall(el.get("points") or "")]
        pts = list(zip(v[0::2], v[1::2]))
        if len(pts) < 2:
            return []
        out = [("M", pts[0])] + [("L", p) for p in pts[1:]]
        if tag == "polygon":
            out.append(("Z",))
        return out
    return []


# ---- Flattening ------------------------------------------------------------

def _flatten_cubic(p0, c1, c2, p3, tol, out, depth=0):
    """Append points (excluding ``p0``) approximating the cubic within
    ``tol``, by recursive subdivision on control-point flatness."""
    dx, dy = p3[0] - p0[0], p3[1] - p0[1]
    d1 = abs((c1[0] - p3[0]) * dy - (c1[1] - p3[1]) * dx)
    d2 = abs((c2[0] - p3[0]) * dy - (c2[1] - p3[1]) * dx)
    norm2 = dx * dx + dy * dy
    flat = ((d1 + d2) ** 2 <= tol * tol * 16.0 * norm2) if norm2 > 1e-18 \
        else (math.dist(p0, c1) + math.dist(c1, c2) + math.dist(c2, p3)
              <= tol)
    if flat or depth >= 16:
        out.append(p3)
        return
    m01 = ((p0[0] + c1[0]) / 2, (p0[1] + c1[1]) / 2)
    m12 = ((c1[0] + c2[0]) / 2, (c1[1] + c2[1]) / 2)
    m23 = ((c2[0] + p3[0]) / 2, (c2[1] + p3[1]) / 2)
    a = ((m01[0] + m12[0]) / 2, (m01[1] + m12[1]) / 2)
    b = ((m12[0] + m23[0]) / 2, (m12[1] + m23[1]) / 2)
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    _flatten_cubic(p0, m01, a, mid, tol, out, depth + 1)
    _flatten_cubic(mid, b, m23, p3, tol, out, depth + 1)


def _contours(segments, m: Affine, tol: float,
              min_step: float = MIN_STEP) -> list[Contour]:
    """Segments in user units → contours in mm (y up) under ``m``."""
    out: list[Contour] = []
    cur: Contour | None = None

    def tp(p):
        x, y = _apply(m, p[0], p[1])
        return (x, -y)                      # SVG y down → model y up

    def push(p, curved):
        if cur.points and math.dist(cur.points[-1], p) < min_step:
            return
        cur.points.append(p)
        cur.curved.append(curved)

    for seg in segments:
        kind = seg[0]
        if kind == "M":
            if cur is not None and len(cur.points) >= 2:
                out.append(cur)
            cur = Contour()
            cur.points.append(tp(seg[1]))
            cur.curved.append(False)
            continue
        if cur is None:
            cur = Contour(points=[(0.0, 0.0)], curved=[False])
        if kind == "L":
            push(tp(seg[1]), False)
        elif kind == "C":
            pts: list = []
            _flatten_cubic(cur.points[-1], tp(seg[1]), tp(seg[2]),
                           tp(seg[3]), tol, pts)
            for p in pts:
                push(p, True)
        elif kind == "Z":
            cur.closed = True
            if len(cur.points) >= 2:
                out.append(cur)
            start = cur.points[0] if cur.points else (0.0, 0.0)
            cur = Contour(points=[start], curved=[False])
    if cur is not None and len(cur.points) >= 2:
        out.append(cur)
    # A closed contour whose last point came back onto the first: one point.
    for c in out:
        if c.closed and len(c.points) > 2 and \
                math.dist(c.points[0], c.points[-1]) < min_step:
            c.curved[0] = c.curved[0] or c.curved[-1]
            c.points.pop()
            c.curved.pop()
        # curved[i] describes the segment LEAVING point i: shift the flags,
        # which were recorded on arrival.
        c.curved = c.curved[1:] + [c.curved[0] if c.closed else False]
    return out


# ---- Document walk ---------------------------------------------------------

def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _style(el) -> dict:
    out = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    for k in ("display", "visibility"):
        if el.get(k) is not None and k not in out:
            out[k] = el.get(k).strip()
    return out


def _hidden(el) -> bool:
    st = _style(el)
    return st.get("display") == "none" or st.get("visibility") in (
        "hidden", "collapse")


def _length_mm(text: str | None):
    if not text:
        return None
    m = re.match(r"\s*(" + _NUM + r")\s*([a-zA-Z%]*)", text)
    if m is None:
        return None
    unit = m.group(2).lower()
    if unit == "%" or unit not in _UNIT_MM:
        return None
    return float(m.group(1)) * _UNIT_MM[unit]


def _root_transform(root) -> Affine:
    """User units → millimetres for the outermost <svg>."""
    vb = [float(v) for v in _NUM_RE.findall(root.get("viewBox") or "")]
    w_mm = _length_mm(root.get("width"))
    h_mm = _length_mm(root.get("height"))
    px = _UNIT_MM["px"]
    if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
        sx = (w_mm / vb[2]) if w_mm else (h_mm / vb[3] if h_mm else px)
        sy = (h_mm / vb[3]) if h_mm else sx
        if not w_mm:
            sx = sy
        return (sx, 0.0, 0.0, sy, -vb[0] * sx, -vb[1] * sy)
    return (px, 0.0, 0.0, px, 0.0, 0.0)


def _parse_xml(path: Path):
    try:
        from defusedxml import ElementTree as ET  # type: ignore
    except ImportError:                                # pragma: no cover
        import xml.etree.ElementTree as ET
    try:
        return ET.parse(str(path)).getroot()
    except Exception as exc:  # noqa: BLE001 - any parse failure is the file's
        raise SvgError(f"Not a readable SVG file: {exc}") from exc


def parse_svg(path, tolerance: float = TOLERANCE,
              scale: float = 1.0) -> Drawing:
    """Read the SVG at ``path`` into contours in millimetres (y up), at
    its own size. ``scale`` is the size it will be built at: the
    flattening tolerance and the weld-sized steps are kept true at THAT
    size, so a drawing shrunk ten times does not collapse into welds."""
    scale = scale if scale > 0 else 1.0
    tolerance = tolerance / scale
    min_step = MIN_STEP / scale
    min_size = MIN_SIZE / scale
    root = _parse_xml(Path(path))
    if _local(root.tag) != "svg":
        raise SvgError("Not an SVG file (no <svg> root element).")
    by_id = {el.get("id"): el for el in root.iter() if el.get("id")}
    contours: list[Contour] = []
    skipped: dict = {}

    def walk(el, m: Affine, depth: int):
        tag = _local(el.tag)
        if depth > 64 or _hidden(el):
            return
        if tag in _SKIP_TAGS:
            if tag in ("text", "image"):
                skipped[tag] = skipped.get(tag, 0) + 1
            return
        m = _mul(m, parse_transform(el.get("transform")))
        if tag in ("svg", "g", "a", "switch") or el is root:
            for child in el:
                walk(child, m, depth + 1)
            return
        if tag == "use":
            href = el.get("href") or el.get("{http://www.w3.org/1999/xlink}"
                                            "href") or ""
            target = by_id.get(href.lstrip("#"))
            if target is None or target is el:
                return
            m2 = _mul(m, (1, 0, 0, 1, _f(el, "x"), _f(el, "y")))
            if _local(target.tag) == "symbol":
                for child in target:
                    walk(child, m2, depth + 1)
            else:
                walk(target, m2, depth + 1)
            return
        segs = _shape_segments(el, tag)
        if segs:
            contours.extend(_contours(segs, m, tolerance, min_step))

    root_m = _root_transform(root)
    root_m = _mul(root_m, parse_transform(root.get("transform")))
    for child in root:
        walk(child, root_m, 1)
    # Specks and degenerate closed contours go.
    kept = []
    for c in contours:
        xs = [p[0] for p in c.points]
        ys = [p[1] for p in c.points]
        big = max(max(xs) - min(xs), max(ys) - min(ys)) >= min_size
        if c.closed and (len(c.points) < 3 or
                         abs(_area(c.points)) < 0.01 / (scale * scale)):
            c.closed = False
        if big and len(c.points) >= 2:
            kept.append(c)
    if not kept:
        raise SvgError("The SVG has no shapes to import (text must be "
                       "converted to paths first).")
    return Drawing(kept, skipped)


# ---- Faces ------------------------------------------------------------------

def _area(pts) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _inside(pt, poly) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and \
                x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _probe(poly) -> tuple[float, float]:
    """A point just inside ``poly``'s first edge (to the left of it, for a
    counter-clockwise loop), so loops that share a vertex nest right."""
    (x1, y1), (x2, y2) = poly[0], poly[1]
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy) or 1.0
    eps = 1e-3
    sgn = 1.0 if _area(poly) > 0 else -1.0
    return mx - dy / n * eps * sgn, my + dx / n * eps * sgn


def nest(loops: list[list]) -> list[tuple[list, list[list]]]:
    """Even-odd nesting: ``[(outer, [holes…]), …]`` with every outer
    counter-clockwise (its face looks up) and holes clockwise."""
    info = []
    for pts in loops:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        info.append((pts, abs(_area(pts)), (min(xs), min(ys), max(xs),
                                            max(ys))))
    order = sorted(range(len(info)), key=lambda i: -info[i][1])
    parent: dict = {}
    depth: dict = {}
    for rank, i in enumerate(order):
        pts, area, bb = info[i]
        probe = _probe(pts)
        best = None
        for j in reversed(order[:rank]):         # smallest bigger first
            ojp, oarea, obb = info[j]
            if oarea <= area:
                continue
            if not (obb[0] <= bb[0] and obb[1] <= bb[1] and
                    obb[2] >= bb[2] and obb[3] >= bb[3]):
                continue
            if _inside(probe, ojp):
                best = j
                break
        parent[i] = best
        depth[i] = 0 if best is None else depth[best] + 1
    faces: dict = {}
    for i in order:
        pts = info[i][0]
        if depth[i] % 2 == 0:
            outer = pts if _area(pts) > 0 else pts[::-1]
            faces[i] = (outer, [])
    for i in order:
        if depth[i] % 2 == 1 and parent[i] in faces:
            pts = info[i][0]
            faces[parent[i]][1].append(pts if _area(pts) < 0 else pts[::-1])
    return [faces[i] for i in order if i in faces]


# ---- Into the scene -----------------------------------------------------------

@dataclass
class ImportStats:
    faces: int = 0
    edges: int = 0
    size_mm: tuple = (0.0, 0.0)
    skipped: dict = field(default_factory=dict)
    new_faces: list = field(default_factory=list)


def place_offset(scene, drawing: Drawing, scale: float) -> tuple[float, float]:
    """Where the drawing's centre goes (mm): the origin, or — when loose
    geometry is already there, which it would weld into — beside it."""
    (x0, y0), (x1, y1) = drawing.bounds()
    cx, cy = (x0 + x1) / 2 * scale, (y0 + y1) / 2 * scale
    verts = list(scene.loose_mesh.vertices)
    if not verts:
        return -cx, -cy
    max_x = max(v.position.x() for v in verts) * 1000.0
    half_w = (x1 - x0) / 2 * scale
    return max_x + 10.0 + half_w - cx, -cy


def add_to_scene(scene, drawing: Drawing, scale: float = 1.0) -> ImportStats:
    """Build ``drawing`` (mm) on the ground of ``scene``'s editing mesh,
    scaled by ``scale``. Meant to run inside an undoable snapshot
    (``core.history.SnapshotImport``)."""
    from PySide6.QtGui import QVector3D
    mesh = scene.mesh
    ox, oy = place_offset(scene, drawing, scale)

    def v(p):
        return QVector3D((p[0] * scale + ox) * 0.001,
                         (p[1] * scale + oy) * 0.001, 0.0)

    stats = ImportStats(size_mm=tuple(s * scale for s in drawing.size()),
                        skipped=dict(drawing.skipped))
    closed = [c for c in drawing.contours if c.closed]
    for outer, holes in nest([c.points for c in closed]):
        face = mesh.add_face([v(p) for p in outer],
                             [[v(p) for p in h] for h in holes] or None)
        stats.faces += 1
        stats.new_faces.append(face)
    # Curved runs become one curve each, so Push/Pull smooths their sides.
    for c in closed:
        _tag_curved_runs(mesh, c, v)
    for c in drawing.contours:
        if c.closed:
            continue
        pts = [v(p) for p in c.points]
        for a, b in zip(pts, pts[1:]):
            if (a - b).length() > 1e-6:
                scene.add_edge(a, b)
                stats.edges += 1
        _tag_curved_runs(mesh, c, v)
    scene.version += 1
    return stats


def _tag_curved_runs(mesh, c: Contour, v) -> None:
    n = len(c.points)
    if n < 2 or not any(c.curved):
        return
    segs = n if c.closed else n - 1
    if c.closed and all(c.curved[:segs]):
        mesh.tag_curve([v(p) for p in c.points], closed=True)
        return
    # Start after a straight segment so a run never wraps around the seam.
    start = 0
    if c.closed:
        start = next(i for i in range(segs) if not c.curved[i]) + 1
    run: list = []
    for k in range(segs + 1):
        i = (start + k) % n
        seg_i = (start + k) % segs if segs else 0
        if k < segs and c.curved[seg_i]:
            if not run:
                run.append(v(c.points[i]))
            run.append(v(c.points[(i + 1) % n]))
        else:
            if len(run) >= 3:
                mesh.tag_curve(run, closed=False)
            run = []
