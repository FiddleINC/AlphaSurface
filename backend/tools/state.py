import asyncio

# ── Shared state ──────────────────────────────────────────────────────────────
canvas_action_queue: asyncio.Queue = asyncio.Queue()

canvas_state: dict = {
    "shapes": [],
    "shape_count": 0,
    "viewport": {"x": 0, "y": 0, "w": 1200, "h": 800, "zoom": 1.0},
    "selected_shape_ids": [],
}


def full_id(shape_id) -> str:
    """tldraw id with the "shape:" prefix (the model sees ids without it)."""
    sid = str(shape_id).strip()
    return sid if sid.startswith("shape:") else f"shape:{sid}"


def update_canvas_state(
    shapes: list,
    shape_count: int,
    viewport: dict | None = None,
    selected_shape_ids: list | None = None,
) -> None:
    """Called by main.py when a canvas_snapshot arrives."""
    was_empty = canvas_state["shape_count"] == 0
    canvas_state["shapes"] = shapes
    canvas_state["shape_count"] = shape_count
    if viewport:
        canvas_state["viewport"] = viewport
    if selected_shape_ids is not None:
        canvas_state["selected_shape_ids"] = [full_id(i) for i in selected_shape_ids if i]

    # Board cleared: forget shapes placed locally but never confirmed by a snapshot.
    if shape_count == 0 and not was_empty:
        from .smart_write import _clear_local_registry
        _clear_local_registry()
