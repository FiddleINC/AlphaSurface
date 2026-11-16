import uuid

from .colors import normalize_color
from .placement import find_free_spot
from .state import canvas_action_queue, canvas_state, full_id

_VALID_GEO = {
    "cloud", "rectangle", "ellipse", "triangle", "diamond", "pentagon",
    "hexagon", "octagon", "star", "rhombus", "rhombus-2", "oval",
    "trapezoid", "arrow-right", "arrow-left", "arrow-up", "arrow-down",
    "x-box", "check-box", "heart",
}

_GEO_ALIASES = {
    "rounded-rectangle": "rectangle",
    "roundedrect": "rectangle",
    "roundedrectangle": "rectangle",
    "rect": "rectangle",
    "box": "rectangle",
    "square": "rectangle",
    "circle": "ellipse",
}

_VALID_FILL = {"none", "semi", "solid", "pattern", "fill", "lined-fill"}

_FILL_ALIASES = {
    "filled": "solid",
    "outline": "none",
    "transparent": "none",
    "half": "semi",
}


def normalize_geo(geo: str, default: str = "rectangle") -> str:
    """Map a shape name ("circle", "rounded_rect", …) to a tldraw geo type."""
    g = (geo or default).strip().lower().replace("_", "-").replace(" ", "-")
    g = _GEO_ALIASES.get(g, _GEO_ALIASES.get(g.replace("-", ""), g))
    return g if g in _VALID_GEO else default


def _normalize_fill(fill: str) -> str:
    f = (fill or "semi").strip().lower().replace("_", "-")
    f = _FILL_ALIASES.get(f, f)
    return f if f in _VALID_FILL else "semi"


def new_shape_id(prefix: str) -> str:
    return f"shape:{prefix}_{uuid.uuid4().hex[:10]}"


def _ids(shape_ids: list[str]) -> list[str]:
    return [full_id(i) for i in shape_ids if str(i).strip()]


def _normalize_linked_to(linked_to) -> list[str]:
    if isinstance(linked_to, list):
        return [str(item).strip() for item in linked_to if str(item).strip()]
    if isinstance(linked_to, str):
        return [item.strip() for item in linked_to.split(",") if item.strip()]
    return []


def _semantic_meta(semantic_role: str, source: str, confidence: float, linked_to) -> dict:
    return {
        "semanticRole": semantic_role,
        "source": source,
        "confidence": float(confidence),
        "linked_to": _normalize_linked_to(linked_to),
        "addedBy": source,
    }


def add_geo_to_canvas(text: str, geo: str, x: int, y: int,
                      w: int, h: int, color: str, fill: str,
                      semantic_role: str = "geo",
                      source: str = "live_agent",
                      confidence: float = 0.8,
                      linked_to: str = "") -> str:
    """
    Create a geometric shape with a text label at an exact position. Prefer place_near / place_in_empty_space unless you computed coordinates.

    geo: rectangle | ellipse | diamond | triangle | cloud | star | hexagon | pentagon | octagon | heart
    color: black | grey | blue | light-blue | green | light-green | red | light-red | orange | yellow | violet | light-violet | white
    fill: none | semi | solid | pattern
    """
    final_w = int(w or 200)
    final_h = int(h or 120)
    x, y = find_free_spot(int(x), int(y), final_w, final_h, canvas_state["shapes"], step=(260, 160), pad=28)
    shape_id = new_shape_id("geo")
    geo = normalize_geo(geo)
    canvas_action_queue.put_nowait({
        "type": "add_geo",
        "payload": {
            "id": shape_id,
            "text": text, "geo": geo,
            "x": x, "y": y, "w": final_w, "h": final_h,
            "color": normalize_color(color, "blue"), "fill": _normalize_fill(fill),
            "meta": _semantic_meta(semantic_role, source, confidence, linked_to),
        }
    })
    return f"{geo} placed id={shape_id}"


def bind_arrow(from_shape_id: str, to_shape_id: str,
               label: str, color: str) -> str:
    """
    Draw a straight arrow that stays attached to two shapes (by shapeId). Use for clean typed diagrams; use ink_connect for hand-drawn arrows.
    """
    canvas_action_queue.put_nowait({
        "type": "bind_arrow",
        "payload": {"fromShapeId": full_id(from_shape_id), "toShapeId": full_id(to_shape_id),
                    "label": label or "", "color": normalize_color(color, "black")}
    })
    return f"Bound arrow {from_shape_id}→{to_shape_id}"


def move_shape(shape_id: str, x: int, y: int) -> str:
    """
    Move a shape so its top-left corner is at (x, y) in page coordinates.
    """
    canvas_action_queue.put_nowait({
        "type": "move_shape",
        "payload": {"shapeId": full_id(shape_id), "x": x, "y": y}
    })
    return f"Moved {shape_id} to ({x},{y})"


def update_shape(shape_id: str, text: str, color: str) -> str:
    """
    Change the text and/or color of an existing shape. Pass an empty string to keep a value unchanged.
    """
    payload: dict = {"shapeId": full_id(shape_id)}
    if text:
        payload["text"] = text
    if color:
        payload["color"] = normalize_color(color, "black")
    canvas_action_queue.put_nowait({"type": "update_shape", "payload": payload})
    return f"Updated {shape_id}"


def delete_shapes(shape_ids: list[str]) -> str:
    """
    Delete shapes by id. Never delete the user's own work unless they asked.
    """
    ids = _ids(shape_ids)
    canvas_action_queue.put_nowait({"type": "delete_shapes", "payload": {"shapeIds": ids}})
    return f"Deleted {len(ids)} shape(s)"


def zoom_to_fit() -> str:
    """
    Zoom the canvas viewport so ALL shapes are visible at once.

    ONLY call this when:
    - The user explicitly says "zoom out", "show everything", "fit to screen"
    - A fully complete multi-shape layout has just been placed (e.g. a complete diagram with 5+ shapes)

    DO NOT call this:
    - After placing one to three shapes
    - Repeatedly during a sequence of placements
    - As a reflex after every canvas action
    """
    canvas_action_queue.put_nowait({"type": "zoom_to_fit", "payload": {}})
    return "Zoomed to fit"


def undo_last_action() -> str:
    """Undo the most recent canvas action the agent or user just made (Ctrl+Z)."""
    canvas_action_queue.put_nowait({"type": "undo", "payload": {}})
    return "Undo applied"
