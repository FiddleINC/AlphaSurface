from .state import canvas_action_queue, full_id


def _ids(shape_ids: list[str]) -> list[str]:
    return [full_id(i) for i in shape_ids if str(i).strip()]


def align_shapes(shape_ids: list[str], alignment: str) -> str:
    """
    Align shapes to each other.
    alignment: left | center-horizontal | right | top | center-vertical | bottom
    """
    if len(shape_ids) < 2:
        return "Need at least 2 shapes to align"
    canvas_action_queue.put_nowait({
        "type": "align_shapes",
        "payload": {"shapeIds": _ids(shape_ids), "alignment": alignment}
    })
    return f"Aligned {len(shape_ids)} shapes: {alignment}"


def distribute_shapes(shape_ids: list[str], direction: str) -> str:
    """
    Distribute shapes with equal spacing between them.
    direction: horizontal | vertical
    """
    if len(shape_ids) < 3:
        return "Need at least 3 shapes to distribute"
    canvas_action_queue.put_nowait({
        "type": "distribute_shapes",
        "payload": {"shapeIds": _ids(shape_ids), "direction": direction}
    })
    return f"Distributed {len(shape_ids)} shapes: {direction}"


def stack_shapes(shape_ids: list[str], direction: str, gap: int = 20) -> str:
    """
    Stack shapes in a row or column with a fixed gap between them.
    direction: horizontal | vertical
    gap: spacing between shapes in pixels (default 20)
    """
    if len(shape_ids) < 2:
        return "Need at least 2 shapes to stack"
    canvas_action_queue.put_nowait({
        "type": "stack_shapes",
        "payload": {"shapeIds": _ids(shape_ids), "direction": direction, "gap": int(gap)}
    })
    return f"Stacked {len(shape_ids)} shapes: {direction} gap={gap}"
