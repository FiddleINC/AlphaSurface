"""
Hand-drawn geometry for AI ink.

Generates jittered point lists that look like quick pen marks — circles that
overshoot their start, slightly wavy underlines, ticks, crosses, brackets and
curved connector arrows. Points are page-space {x, y} dicts and are rendered
by the frontend's `draw_freehand` action as real tldraw draw shapes.
"""

from __future__ import annotations

import math
import random
from typing import Iterable

Bounds = dict  # {"x", "y", "w", "h"}


def _full_id(shape_id: str) -> str:
    sid = str(shape_id).strip()
    return sid if sid.startswith("shape:") else f"shape:{sid}"


def union_bounds(shapes: Iterable[dict]) -> Bounds | None:
    shapes = [s for s in shapes if isinstance(s, dict)]
    if not shapes:
        return None
    x1 = min(float(s.get("x", 0)) for s in shapes)
    y1 = min(float(s.get("y", 0)) for s in shapes)
    x2 = max(float(s.get("x", 0)) + float(s.get("w", 0)) for s in shapes)
    y2 = max(float(s.get("y", 0)) + float(s.get("h", 0)) for s in shapes)
    return {"x": x1, "y": y1, "w": max(1.0, x2 - x1), "h": max(1.0, y2 - y1)}


def resolve_targets(target: str, shapes: list[dict]) -> tuple[list[dict], Bounds | None]:
    """
    Resolve a target string to canvas shapes.

    `target` may be a single shape id, comma-separated ids (with or without the
    "shape:" prefix), an explicit region "x,y,w,h", or text to search for
    (matches typed text and recognized handwriting).
    """
    target = (target or "").strip()
    if not target:
        return [], None

    # Explicit region: four numbers.
    parts = [p.strip() for p in target.split(",")]
    if len(parts) == 4:
        try:
            x, y, w, h = (float(p) for p in parts)
            return [], {"x": x, "y": y, "w": max(1.0, w), "h": max(1.0, h)}
        except ValueError:
            pass

    by_id = {str(s.get("id")): s for s in shapes if isinstance(s, dict)}
    matched = [by_id[_full_id(p)] for p in parts if p and _full_id(p) in by_id]
    if matched:
        return matched, union_bounds(matched)

    needle = target.lower()
    text_hits = [
        s for s in shapes
        if isinstance(s, dict) and needle in str(s.get("text", "")).lower()
    ]
    if text_hits:
        # Prefer the tightest match (shortest text) to avoid circling a whole paragraph.
        text_hits.sort(key=lambda s: len(str(s.get("text", ""))))
        return text_hits[:1], union_bounds(text_hits[:1])

    return [], None


def _rng(seed: int | None) -> random.Random:
    return random.Random(seed)


def _pt(x: float, y: float) -> dict:
    return {"x": int(round(x)), "y": int(round(y))}


def mark_points(mark: str, b: Bounds, seed: int | None = None) -> list[list[dict]]:
    """
    Return one or more strokes (lists of points) for a mark around bounds `b`.
    """
    r = _rng(seed)
    x, y, w, h = float(b["x"]), float(b["y"]), float(b["w"]), float(b["h"])
    cx, cy = x + w / 2, y + h / 2
    pad = max(10.0, min(28.0, 0.12 * max(w, h)))

    if mark == "circle":
        rx, ry = w / 2 + pad, h / 2 + pad
        start = r.uniform(-2.6, -2.0)  # start top-left, like a right-handed loop
        turns = r.uniform(1.06, 1.14)
        n = 48
        stroke = []
        for i in range(n + 1):
            t = start + (2 * math.pi * turns) * i / n
            wobble = 1 + 0.035 * math.sin(3 * t + r.uniform(0, 0.3)) + r.uniform(-0.012, 0.012)
            grow = 1 + 0.06 * (i / n)  # second pass drifts outward a bit
            stroke.append(_pt(cx + rx * wobble * grow * math.cos(t), cy + ry * wobble * grow * math.sin(t)))
        return [stroke]

    if mark == "underline":
        y0 = y + h + max(6.0, pad * 0.5)
        n = 14
        stroke = []
        for i in range(n + 1):
            t = i / n
            px = x - pad * 0.3 + (w + pad * 0.6) * t
            py = y0 + 3 * math.sin(t * math.pi * 1.5) + r.uniform(-1.2, 1.2) + 4 * t
            stroke.append(_pt(px, py))
        return [stroke]

    if mark == "double_underline":
        first = mark_points("underline", b, seed)[0]
        second = [_pt(p["x"] + r.uniform(-3, 3), p["y"] + 10) for p in first]
        return [first, second]

    if mark == "box":
        x1, y1, x2, y2 = x - pad, y - pad, x + w + pad, y + h + pad
        corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1 + 8, y1 - 3)]
        stroke = []
        for (ax, ay), (bx, by) in zip(corners, corners[1:]):
            for i in range(8):
                t = i / 8
                stroke.append(_pt(ax + (bx - ax) * t + r.uniform(-1.5, 1.5),
                                  ay + (by - ay) * t + r.uniform(-1.5, 1.5)))
        stroke.append(_pt(*corners[-1]))
        return [stroke]

    if mark == "check":
        s = max(28.0, min(70.0, h * 0.9))
        ox, oy = x + w + pad + 6, cy - s * 0.1
        return [[
            _pt(ox, oy),
            _pt(ox + s * 0.18, oy + s * 0.2),
            _pt(ox + s * 0.35, oy + s * 0.42),
            _pt(ox + s * 0.6, oy - s * 0.1),
            _pt(ox + s * 0.85, oy - s * 0.55),
            _pt(ox + s * 1.0, oy - s * 0.75),
        ]]

    if mark == "cross":
        x1, y1, x2, y2 = x - pad * 0.4, y - pad * 0.4, x + w + pad * 0.4, y + h + pad * 0.4
        a = [_pt(x1 + (x2 - x1) * t + r.uniform(-2, 2), y1 + (y2 - y1) * t + r.uniform(-2, 2))
             for t in (0, 0.25, 0.5, 0.75, 1)]
        bb = [_pt(x2 - (x2 - x1) * t + r.uniform(-2, 2), y1 + (y2 - y1) * t + r.uniform(-2, 2))
              for t in (0, 0.25, 0.5, 0.75, 1)]
        return [a, bb]

    if mark == "star":
        s = max(14.0, min(30.0, h * 0.45))
        ox, oy = x - pad - s, cy
        stroke = []
        for i in range(6):
            ang = -math.pi / 2 + i * (4 * math.pi / 5)
            stroke.append(_pt(ox + s * math.cos(ang) + r.uniform(-1.5, 1.5),
                              oy + s * math.sin(ang) + r.uniform(-1.5, 1.5)))
        return [stroke]

    if mark == "bracket":
        bx = x - pad
        top, bot = y - pad * 0.3, y + h + pad * 0.3
        return [[
            _pt(bx + 14, top), _pt(bx + 2, top + 6), _pt(bx, cy - 8),
            _pt(bx - 10, cy), _pt(bx, cy + 8), _pt(bx + 2, bot - 6), _pt(bx + 14, bot),
        ]]

    if mark == "question":
        # A small hand-drawn "?" to the right of the target.
        s = max(18.0, min(40.0, h * 0.6))
        ox, oy = x + w + pad + s * 0.5, cy - s * 0.6
        hook = []
        for i in range(10):
            t = math.pi + i * (1.3 * math.pi / 9)
            hook.append(_pt(ox + s * 0.4 * math.cos(t), oy + s * 0.4 * math.sin(t)))
        hook += [_pt(ox + 2, oy + s * 0.55), _pt(ox, oy + s * 0.8)]
        dot = [_pt(ox, oy + s * 1.05), _pt(ox + 1, oy + s * 1.1)]
        return [hook, dot]

    raise ValueError(f"unknown mark '{mark}'")


VALID_MARKS = (
    "circle", "underline", "double_underline", "box", "check",
    "cross", "star", "bracket", "question",
)


def _edge_point(b: Bounds, toward: tuple[float, float], gap: float = 12.0) -> tuple[float, float]:
    """Point on the (padded) boundary of `b` in the direction of `toward`."""
    cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == 0 and dy == 0:
        return cx, cy
    hw, hh = b["w"] / 2 + gap, b["h"] / 2 + gap
    scale = min(hw / abs(dx) if dx else math.inf, hh / abs(dy) if dy else math.inf)
    return cx + dx * scale, cy + dy * scale


def connector_points(a: Bounds, b: Bounds, bend: float = 0.18, seed: int | None = None) -> list[dict]:
    """A curved hand-drawn arrow from bounds `a` to bounds `b`, arrowhead included."""
    r = _rng(seed)
    acx, acy = a["x"] + a["w"] / 2, a["y"] + a["h"] / 2
    bcx, bcy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    sx, sy = _edge_point(a, (bcx, bcy))
    ex, ey = _edge_point(b, (acx, acy))

    dx, dy = ex - sx, ey - sy
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    mx, my = (sx + ex) / 2 + nx * length * bend, (sy + ey) / 2 + ny * length * bend

    pts = []
    n = max(8, int(length / 24))
    for i in range(n + 1):
        t = i / n
        px = (1 - t) ** 2 * sx + 2 * (1 - t) * t * mx + t ** 2 * ex
        py = (1 - t) ** 2 * sy + 2 * (1 - t) * t * my + t ** 2 * ey
        jitter = 0 if i in (0, n) else 1.2
        pts.append(_pt(px + r.uniform(-jitter, jitter), py + r.uniform(-jitter, jitter)))

    # Arrowhead: tip → wing → tip → wing, along the curve's final tangent.
    tx, ty = ex - mx, ey - my
    tl = math.hypot(tx, ty) or 1.0
    ux, uy = tx / tl, ty / tl
    head = max(12.0, min(22.0, length * 0.12))
    for sign in (1, -1):
        ang = math.radians(28) * sign
        wx = ex - head * (ux * math.cos(ang) - uy * math.sin(ang))
        wy = ey - head * (ux * math.sin(ang) + uy * math.cos(ang))
        pts.append(_pt(wx, wy))
        pts.append(_pt(ex, ey))
    return pts
