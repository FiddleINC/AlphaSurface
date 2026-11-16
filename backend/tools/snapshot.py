"""Apply a browser canvas snapshot to the shared canvas_state."""

from .state import canvas_state, full_id, update_canvas_state

_DEFAULT_META = {"semanticRole": "unknown", "source": "unknown", "addedBy": "unknown", "confidence": 1.0, "linked_to": []}


def shapes_from_snapshot(payload: dict) -> list[dict]:
    """
    Merge the snapshot tiers into one shape list.

    blurryShapes:  every visible shape (id, type, bounds, text). Recognized
                   handwriting arrives here as one "ink" shape per cluster.
    focusedShapes: selected / AI-placed shapes with fuller props.
    """
    shape_map: dict = {}
    for s in payload.get("blurryShapes", []):
        sid = s.get("shapeId", "")
        if not sid:
            continue
        fid = full_id(sid)
        shape_map[fid] = {
            "id": fid,
            "type": s.get("type", "unknown"),
            "x": s.get("x", 0), "y": s.get("y", 0),
            "w": s.get("w", 200), "h": s.get("h", 120),
            "text": s.get("text", ""),
            "color": "black",
            "inViewport": True,
            "meta": dict(_DEFAULT_META),
        }
    for s in payload.get("focusedShapes", []):
        sid = s.get("shapeId", "")
        if not sid:
            continue
        fid = full_id(sid)
        existing = shape_map.get(fid, {})
        shape_map[fid] = {
            **existing,
            "id": fid,
            "type": existing.get("type") if existing.get("type") == "ink" else s.get("_type", existing.get("type", "unknown")),
            "x": existing.get("x", s.get("x", 0)), "y": existing.get("y", s.get("y", 0)),
            "w": s.get("w", existing.get("w", 200)) if existing.get("type") != "ink" else existing.get("w", 200),
            "h": s.get("h", existing.get("h", 120)) if existing.get("type") != "ink" else existing.get("h", 120),
            "text": s.get("text") or existing.get("text", ""),
            "color": s.get("color", existing.get("color", "black")),
            "fill": s.get("fill", "none"),
            "inViewport": True,
            "meta": existing.get("meta", dict(_DEFAULT_META)),
        }
    return list(shape_map.values())


def apply_snapshot(payload: dict) -> None:
    """Update canvas_state from a browser snapshot."""
    shapes = shapes_from_snapshot(payload)
    update_canvas_state(
        shapes,
        payload.get("shape_count", len(shapes)),
        viewport=payload.get("viewport"),
        selected_shape_ids=payload.get("selectedShapeIds"),
    )


def note_recognized_cluster(shape_ids: list[str], bounds: dict, text: str) -> str | None:
    """
    Record a freshly recognized ink cluster in canvas_state right away.

    Auto-answer starts Claude's turn inside the recognition request, before
    the browser's next snapshot arrives; without this, Claude would see the
    strokes as anonymous "draw" shapes (or not at all) and could not answer
    next to them. The next snapshot replaces this entry with the real one.
    The browser sends the cluster's lead stroke first, so the id used here is
    the same one later snapshots use.
    Returns the id used for the cluster.
    """
    ids = [full_id(i) for i in shape_ids if i]
    if not ids:
        return None
    members = set(ids)
    shapes = [s for s in canvas_state.get("shapes", []) if s.get("id") not in members]
    shapes.append({
        "id": ids[0], "type": "ink", "text": text,
        "x": bounds["x"], "y": bounds["y"], "w": bounds["w"], "h": bounds["h"],
        "color": "black", "inViewport": True, "meta": dict(_DEFAULT_META),
    })
    canvas_state["shapes"] = shapes
    return ids[0]
