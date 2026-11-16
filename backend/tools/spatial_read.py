from .state import canvas_state


def get_viewport_context() -> dict:
    """
    What is visible on screen right now: viewport bounds, zoom and every visible shape (id, type, position, size, text). Recognized handwriting appears as type "ink" with its transcription in text. Call this first when you need shape ids.
    """
    vp = canvas_state["viewport"]
    shapes = canvas_state["shapes"]

    cx = vp["x"] + vp["w"] / 2
    cy = vp["y"] + vp["h"] / 2

    quadrant_counts = {"top-left": 0, "top-right": 0, "bottom-left": 0, "bottom-right": 0}
    min_x = min_y = float('inf')
    max_x = max_y = float('-inf')

    for s in shapes:
        if not isinstance(s, dict):
            continue
        sx, sy = s.get("x", 0), s.get("y", 0)
        sw, sh = s.get("w", 100), s.get("h", 60)
        scx, scy = sx + sw / 2, sy + sh / 2

        min_x = min(min_x, sx)
        min_y = min(min_y, sy)
        max_x = max(max_x, sx + sw)
        max_y = max(max_y, sy + sh)

        if scx < cx and scy < cy:
            quadrant_counts["top-left"] += 1
        elif scx >= cx and scy < cy:
            quadrant_counts["top-right"] += 1
        elif scx < cx and scy >= cy:
            quadrant_counts["bottom-left"] += 1
        else:
            quadrant_counts["bottom-right"] += 1

    empty_quadrants = [q for q, count in quadrant_counts.items() if count == 0]

    emptiest = min(quadrant_counts, key=quadrant_counts.get)
    suggestions = {
        "top-left":     (vp["x"] + vp["w"] * 0.25, vp["y"] + vp["h"] * 0.25),
        "top-right":    (vp["x"] + vp["w"] * 0.75, vp["y"] + vp["h"] * 0.25),
        "bottom-left":  (vp["x"] + vp["w"] * 0.25, vp["y"] + vp["h"] * 0.75),
        "bottom-right": (vp["x"] + vp["w"] * 0.75, vp["y"] + vp["h"] * 0.75),
    }
    suggested_x, suggested_y = suggestions[emptiest]

    content_bounds = None
    if shapes:
        content_bounds = {
            "x": int(min_x), "y": int(min_y),
            "w": int(max_x - min_x), "h": int(max_y - min_y)
        }

    return {
        "viewport": vp,
        "center": {"x": int(cx), "y": int(cy)},
        "content_bounds": content_bounds,
        "empty_quadrants": empty_quadrants,
        "shape_density": quadrant_counts,
        "suggested_placement": {"x": int(suggested_x), "y": int(suggested_y)},
        "total_shapes": len(shapes),
        "zoom": vp.get("zoom", 1.0),
    }


def find_shape_by_text(query: str) -> dict:
    """
    Find shapes whose text (typed or recognized handwriting) contains `query`. Returns matching shape ids with positions.
    """
    query_lower = query.lower().strip()
    matches = []

    for s in canvas_state["shapes"]:
        if not isinstance(s, dict):
            continue
        text = (s.get("text") or "").lower()
        if query_lower in text:
            score = 2 if text == query_lower else 1
            matches.append({
                "id": s.get("id"),
                "type": s.get("type"),
                "text": s.get("text", "")[:120],
                "color": s.get("color", ""),
                "x": s.get("x"), "y": s.get("y"),
                "inViewport": s.get("inViewport", True),
                "score": score,
            })

    matches.sort(key=lambda x: (-x["score"], x.get("x", 0)))
    return {
        "query": query,
        "matches": matches,
        "count": len(matches),
    }


def get_selected_shapes() -> dict:
    """
    The shapes the user currently has selected, with ids, positions and text.
    """
    selected_ids = list(dict.fromkeys(canvas_state.get("selected_shape_ids", [])))
    if not selected_ids:
        return {"selected": [], "count": 0, "message": "No shapes currently selected"}

    shape_map = {s.get("id"): s for s in canvas_state["shapes"]
                 if isinstance(s, dict)}

    selected = []
    for sid in selected_ids:
        s = shape_map.get(sid)
        if s:
            selected.append({
                "id": s.get("id"),
                "type": s.get("type"),
                "text": s.get("text", "")[:120],
                "color": s.get("color", ""),
                "x": s.get("x"), "y": s.get("y"),
                "w": s.get("w"), "h": s.get("h"),
                "semanticRole": s.get("meta", {}).get("semanticRole", "unknown"),
            })

    return {
        "selected": selected,
        "count": len(selected),
        "ids": selected_ids,
    }
