"""
ink_annotate.py — the AI writes back in ink.

High-level, hand-drawn annotation tools for the live agent. Instead of
asking the model to invent raw coordinates, these tools look up the target
on the canvas (typed text, shapes or recognized handwriting) and generate a
natural-looking pen mark around it.

Ink the AI draws is tagged meta.addedBy="ai_ink" so the frontend renders it
with a progressive "being drawn" animation and never sends it back for
handwriting recognition.
"""

import uuid

from ink.geometry import VALID_MARKS, connector_points, mark_points, resolve_targets
from .state import canvas_action_queue, canvas_state

AI_INK_COLOR = "violet"

_VALID_COLORS = {
    "black", "grey", "light-violet", "violet", "blue", "light-blue",
    "yellow", "orange", "green", "light-green", "light-red", "red",
}
_COLOR_ALIASES = {"gray": "grey", "purple": "violet"}


def _color(color: str) -> str:
    c = (color or AI_INK_COLOR).strip().lower().replace("_", "-")
    c = _COLOR_ALIASES.get(c, c)
    return c if c in _VALID_COLORS else AI_INK_COLOR


def _ink_meta(role: str, linked: list[str]) -> dict:
    return {
        "semanticRole": role,
        "source": "AlphaSurface",
        "confidence": 1.0,
        "linked_to": linked,
        "addedBy": "ai_ink",
    }


def _emit_stroke(points: list[dict], color: str, role: str, linked: list[str]) -> str:
    shape_id = f"shape:ink_{uuid.uuid4().hex[:10]}"
    canvas_action_queue.put_nowait({
        "type": "draw_freehand",
        "payload": {
            "id": shape_id,
            "points": points,
            "color": color,
            "closed": False,
            "size": "m",
            "animate": True,
            "meta": _ink_meta(role, linked),
        },
    })
    return shape_id


def _not_found(target: str) -> str:
    return (
        f"Could not find '{target}' on the canvas. Use a shapeId from "
        "list_canvas_shapes / get_viewport_context, a few words of the text, "
        "or an explicit region 'x,y,w,h'."
    )


def ink_mark(target: str, mark: str = "circle", color: str = "violet") -> str:
    """
    Draw a hand-drawn pen mark on or around something on the canvas.

    Use this to react to the user's writing the way a person would with a pen:
    circle a key idea, underline a word, tick a correct answer, cross out a
    mistake, star something important, bracket a group, or add a "?" next to
    something unclear.

    target: what to mark — a shapeId (e.g. "abc123" or "shape:abc123"),
            several comma-separated shapeIds, a few words of the text to find
            (typed or handwritten), or an explicit region "x,y,w,h".
    mark:   circle | underline | double_underline | box | check | cross |
            star | bracket | question
    color:  violet (default AI ink) | red | green | blue | orange | black

    Returns the id(s) of the strokes drawn.
    """
    mark = (mark or "circle").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {"tick": "check", "checkmark": "check", "x": "cross", "strike": "cross",
               "ring": "circle", "rectangle": "box", "highlight": "underline", "?": "question"}
    mark = aliases.get(mark, mark)
    if mark not in VALID_MARKS:
        return f"Unknown mark '{mark}'. Use one of: {', '.join(VALID_MARKS)}"

    matched, bounds = resolve_targets(target, canvas_state.get("shapes", []))
    if bounds is None:
        return _not_found(target)

    linked = [str(s.get("id")) for s in matched]
    ids = [
        _emit_stroke(stroke, _color(color), f"ink_{mark}", linked)
        for stroke in mark_points(mark, bounds)
    ]
    return f"Drew {mark} around {target!r} — ids={','.join(ids)}"


def ink_connect(from_target: str, to_target: str, label: str = "", color: str = "violet") -> str:
    """
    Draw a curved, hand-drawn arrow from one thing on the canvas to another.

    Use it to show a relationship between two ideas the user wrote or drew,
    e.g. cause → effect, or to point a margin answer at the question it answers.

    from_target / to_target: shapeId(s), a few words of text, or "x,y,w,h".
    label: optional short handwritten label placed at the arrow's midpoint.
    color: violet (default AI ink) | red | green | blue | orange | black
    """
    shapes = canvas_state.get("shapes", [])
    a_shapes, a = resolve_targets(from_target, shapes)
    if a is None:
        return _not_found(from_target)
    b_shapes, b = resolve_targets(to_target, shapes)
    if b is None:
        return _not_found(to_target)

    linked = [str(s.get("id")) for s in a_shapes + b_shapes]
    points = connector_points(a, b)
    arrow_id = _emit_stroke(points, _color(color), "ink_connector", linked)

    if label.strip():
        mid = points[len(points) // 2 - 2] if len(points) > 4 else points[0]
        canvas_action_queue.put_nowait({
            "type": "add_text",
            "payload": {
                "id": f"shape:inklabel_{uuid.uuid4().hex[:10]}",
                "x": mid["x"] + 8,
                "y": mid["y"] - 28,
                "text": label.strip()[:60],
                "color": _color(color),
                "size": "s",
                "font": "draw",
                "meta": _ink_meta("ink_label", [arrow_id]),
            },
        })
    return f"Connected {from_target!r} → {to_target!r} — id={arrow_id}"


def ink_write(text: str, near: str = "", side: str = "right", color: str = "violet") -> str:
    """
    Write a short handwritten reply on the canvas, like a margin note.

    Use for answering a handwritten question or problem right next to it
    (e.g. the result of "12 x 8 =", a one-line hint, a correction).
    Keep it short — a few words or one line of math. For longer content use
    add_note_to_canvas or a research card instead.

    text:  what to write (max ~80 characters, use \\n for a second line)
    near:  what to write next to — shapeId(s), a few words of text, or
           "x,y,w,h". Leave empty to write in empty space in the viewport.
    side:  right | below | left | above
    color: violet (default AI ink) | red | green | blue | orange | black
    """
    text = (text or "").strip()
    if not text:
        return "Nothing to write."
    text = text[:160]

    matched, bounds = resolve_targets(near, canvas_state.get("shapes", [])) if near else ([], None)
    if near and bounds is None:
        return _not_found(near)

    est_w = min(520, 14 * max(len(line) for line in text.split("\n")) + 20)
    est_h = 44 * (text.count("\n") + 1)

    if bounds is None:
        from .smart_write import _find_free_position
        vp = canvas_state.get("viewport", {"x": 0, "y": 0, "w": 1200, "h": 800})
        x, y = _find_free_position(int(vp["x"] + vp["w"] * 0.3), int(vp["y"] + vp["h"] * 0.3), est_w, est_h)
    else:
        gap = 24
        side = (side or "right").lower()
        if side == "below":
            x, y = bounds["x"], bounds["y"] + bounds["h"] + gap
        elif side == "left":
            x, y = bounds["x"] - est_w - gap, bounds["y"]
        elif side == "above":
            x, y = bounds["x"], bounds["y"] - est_h - gap
        else:
            x, y = bounds["x"] + bounds["w"] + gap, bounds["y"] + max(0, bounds["h"] / 2 - est_h / 2)

    shape_id = f"shape:inkwrite_{uuid.uuid4().hex[:10]}"
    from .smart_write import _register_local
    _register_local(int(x), int(y), est_w, est_h, shape_id)
    canvas_action_queue.put_nowait({
        "type": "add_text",
        "payload": {
            "id": shape_id,
            "x": int(x),
            "y": int(y),
            "text": text,
            "color": _color(color),
            "size": "m",
            "font": "draw",
            "animate": True,
            "meta": _ink_meta("ink_reply", [str(s.get("id")) for s in matched]),
        },
    })
    return f"Wrote {text!r} — id={shape_id}"


def tidy_ink(scope: str = "viewport") -> str:
    """
    Convert the user's rough handwriting and sketches into clean typed text,
    neat shapes and straight arrows.

    Call when the user asks to "clean up", "tidy", "neaten", "make this neat",
    "convert my handwriting" or "turn this into a diagram".

    scope: "selection" — only the ink the user has selected
           "viewport"  — all handwriting visible on screen (default)
    """
    scope = "selection" if str(scope).lower().startswith("sel") else "viewport"
    canvas_action_queue.put_nowait({"type": "ink_tidy", "payload": {"scope": scope}})
    return f"Tidying ink in {scope}. The user can undo with one tap."
