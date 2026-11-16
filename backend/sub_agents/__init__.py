"""Background sub-agents (research, deep analysis) and their shared helpers."""

import asyncio

from tools.placement import find_free_spot
from tools.state import canvas_state

_DEFAULT_VIEWPORT = {"x": 0, "y": 0, "w": 1200, "h": 800}


def find_empty_area(
    w: int, h: int, fx: float = 0.08, fy: float = 0.08,
    step: tuple[int, int] = (360, 220), pad: int = 36,
) -> tuple[int, int]:
    """
    A free (w × h) spot on the board, searched outward from the point at
    fractions (fx, fy) of the current viewport.
    """
    vp = canvas_state.get("viewport") or _DEFAULT_VIEWPORT
    x = int(vp["x"] + vp["w"] * fx)
    y = int(vp["y"] + vp["h"] * fy)
    return find_free_spot(x, y, w, h, canvas_state.get("shapes", []), step=step, pad=pad, rings=9)


def find_empty_note_position(note_w: int = 320, note_h: int = 140) -> tuple[int, int]:
    """Pick a note position in the viewport that avoids existing shapes when possible."""
    return find_empty_area(note_w, note_h)


async def emit_failure_note(broadcast_fn, agent_name: str, error: Exception | str) -> None:
    """Broadcast a visible canvas note when a sub-agent fails."""
    message = str(error).strip() if error is not None else "unknown error"
    lower = message.lower()
    if "429" in lower or "rate" in lower or "overloaded" in lower:
        user_text = "Temporary capacity limit. Please try again in a moment."
    elif "timed out" in lower or "timeout" in lower:
        user_text = "That took too long. Try a shorter prompt or retry now."
    elif "401" in lower or "403" in lower or "auth" in lower or "key" in lower:
        user_text = "Authorization issue detected. Please verify provider credentials."
    else:
        user_text = "Could not complete that request. Please retry with a clearer prompt."
    x, y = find_empty_note_position()

    await broadcast_fn({
        "type": "add_note",
        "payload": {
            "x": x,
            "y": y,
            "text": f"{agent_name}: {user_text}",
            "color": "light-red",
            "size": "m",
            "meta": {
                "semanticRole": "error_notice",
                "source": agent_name,
                "confidence": 1.0,
                "linked_to": [],
                "addedBy": agent_name,
            },
        },
    })

    # Small yield to keep note ordering predictable relative to status updates.
    await asyncio.sleep(0.01)
