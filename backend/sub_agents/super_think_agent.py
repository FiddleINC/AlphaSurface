"""
AlphaSurface — SuperThinkAgent

A deep canvas analysis sub-agent. Triggered when the canvas agent calls
dispatch_super_think() ("super think", "deep dive", "analyse everything").

Flow:
  1. Reads all text from the canvas (via the canvas_state snapshot)
  2. Sends it to Claude at high effort
  3. Places three columns of notes in empty space in the viewport:
       - Synthesis (violet)
       - Tensions / contradictions (red)
       - Open questions (yellow)
  4. Focuses the viewport on the result

Model: Claude (CLAUDE_MODEL, effort ALPHASURFACE_SUPER_THINK_EFFORT)
"""

import asyncio
import traceback
import uuid
from typing import Optional

from brain.claude import get_client, request_defaults, text_of
from model_config import CLAUDE_MODEL, CLAUDE_SUPER_THINK_EFFORT
from sub_agents import emit_failure_note, find_empty_area

_MODEL = CLAUDE_MODEL


def _make_shape_id(prefix: str) -> str:
    return f"shape:{prefix}_{uuid.uuid4().hex[:8]}"


# ── Deep analysis prompt ──────────────────────────────────────────────────────

_SYSTEM = """\
You are a deep analytical thinker reviewing a shared thinking canvas.
The canvas contains the user's ideas, notes, sketches, and concepts.

Your task is to produce THREE layers of analysis:

1. SYNTHESIS (2-3 bullet points):
   What is the core insight or claim the user is building?
   What do all these ideas have in common?

2. TENSIONS (2-3 bullet points):
   What contradictions, trade-offs, or unresolved conflicts exist in these ideas?
   What assumptions are being made that could be challenged?

3. OPEN QUESTIONS (2-3 bullet points):
   What important question has NOT been asked yet?
   What would make this thinking more complete?

Format your response as:
SYNTHESIS:
• [point]
• [point]

TENSIONS:
• [point]
• [point]

OPEN QUESTIONS:
• [point]
• [point]

Be specific. Reference the actual content on the canvas, not generic advice.
If the canvas is empty or has only shapes with no text, say so in SYNTHESIS.
"""

# ── Parser ────────────────────────────────────────────────────────────────────

def _parse_sections(text: str) -> dict[str, list[str]]:
    """Parse the three-section response into lists of bullet points."""
    sections: dict[str, list[str]] = {
        "synthesis": [],
        "tensions": [],
        "open_questions": [],
    }
    current: Optional[str] = None
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("SYNTHESIS"):
            current = "synthesis"
        elif line.upper().startswith("TENSION"):
            current = "tensions"
        elif line.upper().startswith("OPEN QUESTION"):
            current = "open_questions"
        elif line.startswith("•") or line.startswith("-") or line.startswith("*"):
            if current:
                bullet = line.lstrip("•-* ").strip()
                if bullet:
                    sections[current].append(bullet)
    return sections


# ── Canvas placement ──────────────────────────────────────────────────────────

_SECTION_COLORS = {
    "synthesis": "violet",
    "tensions": "red",
    "open_questions": "yellow",
}

_SECTION_LABELS = {
    "synthesis": "💡 Synthesis",
    "tensions": "⚡ Tensions",
    "open_questions": "❓ Open Questions",
}


async def _place_super_think(broadcast_fn, sections: dict[str, list[str]]):
    """Place up to three columns (header + notes) in empty space in the viewport."""
    col_gap = 420
    note_w = 380
    note_spacing = 240  # tldraw notes are 200 tall at size "m"
    columns = [(key, bullets[:3]) for key, bullets in sections.items() if bullets]
    if not columns:
        return
    total_w = col_gap * (len(columns) - 1) + note_w
    total_h = 32 + 70 + note_spacing * max(len(b) for _, b in columns)
    bx, top = find_empty_area(total_w, total_h, step=(total_w + 80, total_h + 80), pad=48)
    by = top + 32  # room for the attribution line
    placed: list[str] = []

    for col, (key, bullets) in enumerate(columns):
        cx = bx + col * col_gap
        cy = by

        # Section header (geo shape)
        header_id = _make_shape_id(f"st_{key}_header")
        await broadcast_fn({
            "type": "add_geo",
            "payload": {
                "id": header_id,
                "x": cx,
                "y": cy,
                "w": note_w,
                "h": 54,
                "text": _SECTION_LABELS[key],
                "color": _SECTION_COLORS[key],
                "fill": "solid",
                "geo": "rectangle",
            }
        })
        placed.append(header_id)
        await asyncio.sleep(0.1)

        # Bullet notes below header
        for i, bullet in enumerate(bullets):
            note_id = _make_shape_id(f"st_{key}_{i}")
            await broadcast_fn({
                "type": "add_note",
                "payload": {
                    "id": note_id,
                    "x": cx,
                    "y": cy + 70 + i * note_spacing,
                    "text": bullet,
                    "color": _SECTION_COLORS[key],
                }
            })
            placed.append(note_id)
            await asyncio.sleep(0.08)

    # Attribution
    stamp_id = _make_shape_id("st_stamp")
    await broadcast_fn({
        "type": "add_text",
        "payload": {
            "id": stamp_id,
            "x": bx,
            "y": by - 32,
            "text": f"🧠 SuperThink · {_MODEL}",
            "size": "s",
            "color": "violet",
        }
    })
    placed.append(stamp_id)
    await asyncio.sleep(0.05)
    await broadcast_fn({
        "type": "focus_artifact",
        "payload": {"shapeIds": placed, "primaryShapeId": placed[0], "reason": "super_think_ready"},
    })


# ── Canvas text extractor ─────────────────────────────────────────────────────

def _extract_canvas_text(canvas_state: dict) -> str:
    """Pull all text from the canvas shapes into a flat summary."""
    shapes = canvas_state.get("shapes", [])
    lines = []
    non_text_counts: dict[str, int] = {}
    for shape in shapes:
        if not isinstance(shape, dict):
            continue
        text = (shape.get("text") or shape.get("label") or "").strip()
        if text:
            shape_type = shape.get("type", "shape")
            lines.append(f"[{shape_type}] {text}")
        else:
            shape_type = shape.get("type", "shape")
            non_text_counts[shape_type] = non_text_counts.get(shape_type, 0) + 1

    if lines:
        return "\n".join(lines)

    if shapes:
        summary = ", ".join(f"{k}:{v}" for k, v in sorted(non_text_counts.items()))
        return f"(canvas has {len(shapes)} shapes with no readable text labels; types: {summary})"

    return "(canvas is empty)"


# ── Main handler ──────────────────────────────────────────────────────────────

async def run_super_think(payload: dict, broadcast_fn, canvas_state: dict) -> None:
    """
    Main handler. Called by the dispatcher with an empty payload.
    canvas_state: the live canvas state dict from tools.canvas_state.
    """
    print("[SuperThink] Starting deep analysis...")

    canvas_text = _extract_canvas_text(canvas_state)
    print(f"[SuperThink] Canvas content ({len(canvas_state.get('shapes', []))} shapes):\n{canvas_text[:400]}")

    try:
        user_message = f"Here is what's on the canvas:\n\n{canvas_text}"
        async with get_client().beta.messages.stream(
            **request_defaults(_MODEL, CLAUDE_SUPER_THINK_EFFORT),
            max_tokens=32000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            response = await stream.get_final_message()

        raw_text = text_of(response.content)
        print(f"[SuperThink] Response received ({len(raw_text)} chars)")

        sections = _parse_sections(raw_text)
        total_bullets = sum(len(v) for v in sections.values())

        if total_bullets == 0:
            print("[SuperThink] No structured output parsed — skipping canvas placement.")
            await emit_failure_note(broadcast_fn, "SuperThinkAgent", "no analysis parsed")
            return

        await _place_super_think(broadcast_fn, sections)
        print(f"[SuperThink] Complete — {total_bullets} insights placed on canvas.")

    except Exception as e:
        print(f"[SuperThink] Error: {e!r}")
        if "429" not in str(e):
            traceback.print_exc()
        await emit_failure_note(broadcast_fn, "SuperThinkAgent", e)
