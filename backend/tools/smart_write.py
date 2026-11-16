from .basic_write import new_shape_id, normalize_geo
from .colors import normalize_color
from .placement import find_free_spot, overlaps
from .state import canvas_action_queue, canvas_state, full_id

# ── Shape type normalization ───────────────────────────────────────────────────
# Maps anything the model might say to one of our three output types: note/geo/text
_SHAPE_TYPE_MAP = {
    "note": "note",
    "sticky": "note",
    "sticky_note": "note",
    "text": "text",
    "label": "text",
}

# ── Local placement registry ──────────────────────────────────────────────────
# Tracks shapes placed in the current session so overlap detection works
# even before the next canvas_snapshot arrives (snapshots come every 3 s).
# Cleared when the board is cleared (see state.update_canvas_state).
_local_placed: list[dict] = []


def _clear_local_registry():
    _local_placed.clear()


def _register_local(x: int, y: int, w: int, h: int, shape_id: str):
    _local_placed.append({"id": shape_id, "x": x, "y": y, "w": w, "h": h})


def _all_shapes() -> list[dict]:
    """Combined view: canvas_state shapes + locally placed shapes not yet in state."""
    known_ids = {s.get("id") for s in canvas_state["shapes"] if isinstance(s, dict)}
    local_unseen = [s for s in _local_placed if s["id"] not in known_ids]
    return list(canvas_state["shapes"]) + local_unseen


def _normalize_shape_type(shape_type: str) -> str:
    """Normalize any shape type string to note/geo/text."""
    raw = (shape_type or "geo").strip().lower().replace("-", "_").replace(" ", "_")
    return _SHAPE_TYPE_MAP.get(raw, "geo")


def _geo_subtype(shape_type: str) -> str:
    """"ellipse", "diamond", … → that geo; generic names ("geo", "shape") → rectangle."""
    return normalize_geo(shape_type)


def _is_occupied(px: int, py: int, pw: int = 220, ph: int = 120, gap: int = 30) -> bool:
    return overlaps(px, py, pw, ph, _all_shapes(), gap)


def _find_free_position(preferred_x: int, preferred_y: int,
                        w: int = 220, h: int = 120) -> tuple[int, int]:
    return find_free_spot(preferred_x, preferred_y, w, h, _all_shapes(), step=(280, 180), pad=30, rings=15)


def _find_anchor(anchor_shape_id: str) -> dict | None:
    """Find anchor shape, tolerating IDs with or without 'shape:' prefix."""
    fid = full_id(anchor_shape_id)
    return next((s for s in _all_shapes() if isinstance(s, dict) and s.get("id") == fid), None)


def _emit_shape(shape_type: str, text: str, x: int, y: int,
                w: int, h: int, color: str, geo_type: str = "rectangle") -> str:
    """Queue a canvas action and register in local placement registry."""
    shape_id = new_shape_id(shape_type)

    if shape_type == "note":
        payload = {"text": text, "x": x, "y": y, "color": normalize_color(color, "yellow"), "size": "m"}
        action = "add_note"
    elif shape_type == "geo":
        payload = {"text": text, "geo": geo_type, "x": x, "y": y, "w": w, "h": h,
                   "color": normalize_color(color, "blue"), "fill": "semi"}
        action = "add_geo"
    else:  # text
        payload = {"text": text, "x": x, "y": y, "color": normalize_color(color, "black"), "size": "m"}
        action = "add_text"
        w, h = 260, 60

    canvas_action_queue.put_nowait({"type": action, "payload": {"id": shape_id, **payload}})
    _register_local(x, y, w, h, shape_id)
    return shape_id


def _size_for(shape_type: str) -> tuple[int, int]:
    return (280, 180) if shape_type == "note" else (220, 120)


def place_in_empty_space(
    text: str,
    shape_type: str,
    color: str,
    preferred_x: int,
    preferred_y: int,
) -> str:
    """
    Place a shape in empty space near a preferred position.
    shape_type: note | text | rectangle | ellipse | diamond | triangle | cloud | star | hexagon
    Pass 0 for preferred_x / preferred_y to start from the visible area.
    Returns the shape ID so you can reference it later (e.g. for bind_arrow).
    """
    vp = canvas_state["viewport"]
    if int(preferred_x) <= 0:
        preferred_x = int(vp["x"] + vp["w"] * 0.3)
    if int(preferred_y) <= 0:
        preferred_y = int(vp["y"] + vp["h"] * 0.3)

    normalized_type = _normalize_shape_type(shape_type)
    w, h = _size_for(normalized_type)
    final_x, final_y = _find_free_position(int(preferred_x), int(preferred_y), w, h)
    shape_id = _emit_shape(normalized_type, text, final_x, final_y, w, h, color, _geo_subtype(shape_type))
    return f"Placed {normalized_type} at ({final_x},{final_y}) id={shape_id}"


def place_near(
    anchor_shape_id: str,
    text: str,
    shape_type: str,
    direction: str,
    color: str,
) -> str:
    """
    Place a shape adjacent to an existing shape.
    shape_type: note | text | rectangle | ellipse | diamond | triangle | cloud | star | hexagon
    direction: right | left | above | below | around (auto-picks emptiest side)
    Returns the shape ID.
    """
    anchor = _find_anchor(anchor_shape_id)
    if not anchor:
        # Fall back to empty space placement if the anchor is not found.
        vp = canvas_state["viewport"]
        return place_in_empty_space(
            text, shape_type, color,
            int(vp["x"] + vp["w"] * 0.4),
            int(vp["y"] + vp["h"] * 0.4),
        )

    ax, ay = int(anchor.get("x", 300)), int(anchor.get("y", 300))
    aw, ah = int(anchor.get("w", 220)), int(anchor.get("h", 120))
    gap = 40
    normalized_type = _normalize_shape_type(shape_type)
    W, H = _size_for(normalized_type)

    positions = {
        "right": (ax + aw + gap,          ay + ah // 2 - H // 2),
        "left":  (ax - W - gap,           ay + ah // 2 - H // 2),
        "above": (ax + aw // 2 - W // 2,  ay - H - gap),
        "below": (ax + aw // 2 - W // 2,  ay + ah + gap),
    }

    # Auto-pick the side with the fewest shapes nearby.
    if direction not in positions:
        others = [s for s in _all_shapes() if isinstance(s, dict) and s.get("id") != anchor.get("id")]

        def density(px, py):
            return sum(1 for s in others if abs(s.get("x", 0) - px) < 280 and abs(s.get("y", 0) - py) < 180)

        direction = min(positions, key=lambda d: density(*positions[d]))

    nx, ny = _find_free_position(*positions[direction], W, H)
    shape_id = _emit_shape(normalized_type, text, nx, ny, W, H, color, _geo_subtype(shape_type))
    return f"Placed {normalized_type} {direction} of {anchor_shape_id} at ({nx},{ny}) id={shape_id}"
