"""Find empty space on the board for new shapes (shared by tools and sub-agents)."""

from __future__ import annotations

from typing import Iterable


def overlaps(x: float, y: float, w: float, h: float, shapes: Iterable[dict], pad: float) -> bool:
    """True if the rect (x, y, w, h), grown by `pad`, touches any shape."""
    for s in shapes:
        if not isinstance(s, dict):
            continue
        sx, sy = float(s.get("x", 0)), float(s.get("y", 0))
        sw, sh = float(s.get("w", 220)), float(s.get("h", 120))
        if x < sx + sw + pad and x + w > sx - pad and y < sy + sh + pad and y + h > sy - pad:
            return True
    return False


def find_free_spot(
    x: int, y: int, w: int, h: int, shapes: list[dict],
    step: tuple[int, int] = (280, 180), pad: int = 30, rings: int = 12,
) -> tuple[int, int]:
    """
    The preferred (x, y) if it is free, else the nearest free spot found by
    searching rings of candidates around it (right, down, left, up, diagonals).
    """
    if not overlaps(x, y, w, h, shapes, pad):
        return int(x), int(y)
    sx, sy = step
    for ring in range(1, rings + 1):
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
            tx, ty = x + dx * ring * sx, y + dy * ring * sy
            if not overlaps(tx, ty, w, h, shapes, pad):
                return int(tx), int(ty)
    return int(x + sx), int(y + sy)
