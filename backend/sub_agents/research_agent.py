"""
AlphaSurface — ResearchAgent

Triggered by:
  A) Live Agent calls dispatch_research("query") → task lands in queue
  B) (Future) Event bus fires research_ready on long idle + canvas topic detected

Flow:
  1. Receives {query: str} payload from dispatcher
  2. Claude searches the web (web_search tool) and submits a structured result
  3. Returns structured JSON (Pydantic model): title + bullets + sources
  4. Places a clean cluster on canvas:
       [Title geo] ──→ [Bullet note] x3-5
                   ──→ [Source bookmark] (if URL available)
  5. Calls signal_agent_acted() via dispatcher wrapper (already done)

Canvas layout: newspaper-style single column with headline + sections.
All shapes placed relative to current viewport center.
"""

import asyncio
import random
import uuid
from typing import Optional

from pydantic import BaseModel, Field

from brain.claude import get_client, request_defaults
from model_config import CLAUDE_MODEL, CLAUDE_RESEARCH_EFFORT
from sub_agents import emit_failure_note
from tools.state import canvas_state

# ── Agent identity ───────────────────────────────────────────────────────────
# Each agent stamps its output with a small attribution label on canvas.

# ── Config ────────────────────────────────────────────────────────────────────

_MODEL = CLAUDE_MODEL

_SYSTEM_PROMPT = """\
You are a research assistant. Your job is to search the web for information on a query
and return a structured summary suitable for placing on a visual canvas.

Rules:
- 3 to 5 bullets maximum
- Each bullet must be a concrete fact or finding, not a vague statement
- Keep each bullet compact enough to fit on a canvas card; target 1 to 2 short sentences
- Prefer recent information
- ALWAYS use the web_search tool to find accurate information. DO NOT guess.
- When done, call submit_research exactly once with your findings.
- Keep each bullet under 220 characters.
"""

_MAX_BULLETS_SHORT = 4
_MAX_BULLETS_LONG = 3
_MAX_BULLET_CHARS = 220


def _compact_text(text: str, max_chars: int = _MAX_BULLET_CHARS) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."

class ResearchResult(BaseModel):
    title: str = Field(description="Short topic title (max 5 words)")
    format: str = Field(
        description=(
            "'long' for conceptual/explanatory questions (explain, history, how does, why). "
            "'short' for quick facts, comparisons, or lookups. Default: 'short'."
        )
    )
    bullets: list[str] = Field(
        description=(
            "Key findings. 'short': 3-5 concise one-sentence bullets. "
            "'long': 5-8 detailed points with full context and specifics."
        )
    )
    source_url: Optional[str] = Field(description="URL of best single source, or null")
    source_label: Optional[str] = Field(description="Short label for the source e.g. 'Reuters' or null")


# ── Canvas placement helpers ──────────────────────────────────────────────────

def _canvas_pos():
    """Return a base (x, y) position offset from canvas center with slight randomness."""
    base_x = random.randint(-600, 200)
    base_y = random.randint(-300, 300)
    return base_x, base_y


def _find_empty_column_origin(col_w: int, col_h: int) -> tuple[int, int]:
    vp = canvas_state.get("viewport", {"x": 0, "y": 0, "w": 1200, "h": 800})
    shapes = canvas_state.get("shapes", [])

    # Keep research cards outside the active focus area, but still nearby.
    # Place near the right edge rather than far off-canvas.
    cx = int(vp["x"] + vp["w"] * 0.85 + random.randint(24, 120))
    cy = int(vp["y"] + vp["h"] * 0.10 + random.randint(-40, 120))

    def overlaps(px: int, py: int) -> bool:
        pad = 48
        for s in shapes:
            if not isinstance(s, dict):
                continue
            sx = int(s.get("x", 0))
            sy = int(s.get("y", 0))
            sw = int(s.get("w", 220))
            sh = int(s.get("h", 120))
            if (
                px < sx + sw + pad
                and px + col_w > sx - pad
                and py < sy + sh + pad
                and py + col_h > sy - pad
            ):
                return True
        return False

    if not overlaps(cx, cy):
        return cx, cy

    for ring in range(1, 10):
        for dx, dy in [
            (ring * 520, 0),
            (0, ring * 280),
            (-ring * 520, 0),
            (0, -ring * 280),
            (ring * 520, ring * 280),
            (-ring * 520, ring * 280),
            (ring * 520, -ring * 280),
            (-ring * 520, -ring * 280),
        ]:
            tx, ty = cx + dx, cy + dy
            if not overlaps(tx, ty):
                return tx, ty

    return cx + 620, cy + 300


def _make_shape_id(prefix: str) -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _place_cluster(broadcast_fn, title: str, bullets: list[str],
                          source_url: str | None, source_label: str | None,
                          long_form: bool = False):
    """Broadcast a single semantic research card plus optional linked source bookmark."""
    col_w = 500 if long_form else 460
    card_h = 340 if long_form else 280
    card_id = f"shape:research_card_{uuid.uuid4().hex[:10]}"
    bx, by = _find_empty_column_origin(col_w, card_h + 220)

    await broadcast_fn({
        "type": "add_research_card",
        "payload": {
            "id": card_id,
            "x": bx,
            "y": by,
            "w": col_w,
            "h": card_h,
            "title": title,
            "bullets": bullets,
            "source": {
                "url": source_url,
                "label": source_label,
            },
            "meta": {
                "semanticRole": "research_card",
                "source": "ResearchAgent",
                "confidence": 0.88,
                "linked_to": [],
                "addedBy": "ResearchAgent",
            },
        },
    })
    await asyncio.sleep(0.05)

    linked_shapes = [card_id]
    if source_url:
        bookmark_id = f"shape:research_source_{uuid.uuid4().hex[:10]}"
        await broadcast_fn({
            "type": "add_bookmark",
            "payload": {
                "id": bookmark_id,
                "x": bx,
                "y": by + card_h + 18,
                "url": source_url,
                "meta": {
                    "semanticRole": "research_source",
                    "source": "ResearchAgent",
                    "confidence": 0.83,
                    "linked_to": [card_id],
                    "addedBy": "ResearchAgent",
                },
            },
        })
        await asyncio.sleep(0.05)
        linked_shapes.append(bookmark_id)

    await broadcast_fn({
        "type": "focus_artifact",
        "payload": {
            "shapeIds": linked_shapes,
            "primaryShapeId": card_id,
            "reason": "research_ready",
        },
    })
    print(
        f"[ResearchAgent] Research card placed — '{title}' with {len(bullets)} items "
        f"({'long' if long_form else 'short'} form)"
    )


# ── Core research logic ───────────────────────────────────────────────────────

_SUBMIT_TOOL = {
    "name": "submit_research",
    "description": "Submit the final research result for placement on the canvas. Call exactly once, after searching.",
    "input_schema": {
        **ResearchResult.model_json_schema(),
        "additionalProperties": False,
    },
}
_WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 4}


async def _research(query: str) -> dict | None:
    """Claude searches the web, then calls submit_research with the result."""
    messages: list = [{"role": "user", "content": f"Research this topic: {query}"}]
    client = get_client()
    for _ in range(6):
        response = await client.beta.messages.create(
            **request_defaults(_MODEL, CLAUDE_RESEARCH_EFFORT),
            max_tokens=16000,
            system=_SYSTEM_PROMPT,
            tools=[_WEB_SEARCH, _SUBMIT_TOOL],
            messages=messages,
        )
        for block in response.content:
            if getattr(block, "type", "") == "tool_use" and block.name == "submit_research":
                return dict(block.input)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            continue  # long server-side search: let it continue
        if response.stop_reason == "refusal":
            return None
        messages.append({"role": "user", "content": "Now call submit_research with your findings."})
    return None


async def run_research(payload: dict, broadcast_fn) -> None:
    """Dispatcher handler. payload = {"query": str}."""
    query = payload.get("query", "").strip()
    if not query:
        return
    print(f"[ResearchAgent] Researching: {query}")
    try:
        result = await _research(query)
        if not result:
            await emit_failure_note(broadcast_fn, "ResearchAgent", "no result")
            return
        title = result.get("title") or query[:40]
        long_form = result.get("format", "short") == "long"
        max_bullets = _MAX_BULLETS_LONG if long_form else _MAX_BULLETS_SHORT
        bullets = [_compact_text(b) for b in (result.get("bullets") or [])[:max_bullets] if isinstance(b, str)]
        if not bullets:
            return
        await _place_cluster(
            broadcast_fn, title, bullets, result.get("source_url"), result.get("source_label"), long_form=long_form
        )
    except Exception as e:
        print(f"[ResearchAgent] Error: {e!r}")
        await emit_failure_note(broadcast_fn, "ResearchAgent", e)
