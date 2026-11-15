"""
CanvasAgent — Claude drives the whiteboard.

Turns come from three places: something the user said (voice transcript),
"Ask AI" on a selection, or a handwritten question (auto-answer). Each turn
sends Claude the latest board screenshot plus a compact JSON summary of the
visible shapes, then runs a tool loop over the canvas tools. Tool calls
enqueue canvas actions that main.py broadcasts to the browser; the final
plain text of the turn is handed to `on_reply` (spoken by the voice layer).

Turns run one at a time, in order. History is append-only (never edited) so
prompt caching keeps working; it is reset after MAX_HISTORY_MESSAGES.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import anthropic

from model_config import CLAUDE_AGENT_EFFORT, CLAUDE_MODEL, has_claude_credentials
from prompts.loader import load_prompt
from tools import AGENT_TOOLS, canvas_state

from .claude import get_client, request_defaults, text_of
from .tool_schema import ToolBox

MAX_TOOL_ROUNDS = 8
MAX_HISTORY_MESSAGES = 40
MAX_SUMMARY_SHAPES = 80

BroadcastFn = Callable[[dict], Awaitable[None]]
ReplyFn = Callable[[str], Awaitable[None]]


@dataclass
class Turn:
    text: str
    source: str  # "voice" | "ask" | "auto_answer"
    image: Optional[bytes] = None
    mime: str = "image/png"


def board_summary(state: dict = canvas_state) -> str:
    """Compact JSON of what is on screen, for the start of each turn."""
    vp = state.get("viewport", {})
    shapes = []
    for s in state.get("shapes", [])[:MAX_SUMMARY_SHAPES]:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id", ""))
        item = {
            "id": sid[6:] if sid.startswith("shape:") else sid,
            "type": s.get("type", "?"),
            "x": round(s.get("x", 0)), "y": round(s.get("y", 0)),
            "w": round(s.get("w", 0)), "h": round(s.get("h", 0)),
        }
        if s.get("text"):
            item["text"] = str(s["text"])[:200]
        shapes.append(item)
    return json.dumps({
        "viewport": {k: round(vp.get(k, 0)) for k in ("x", "y", "w", "h")},
        "selected": state.get("selected_shape_ids", [])[:20],
        "shapes": shapes,
    }, separators=(",", ":"))


_SOURCE_PREFIX = {
    "voice": "The user said",
    "ask": "Ask AI",
    "auto_answer": "Handwritten question",
}


class CanvasAgent:
    def __init__(self, broadcast: BroadcastFn, on_reply: ReplyFn | None = None, client=None):
        self.broadcast = broadcast
        self.on_reply = on_reply
        self._client = client
        self.tools = ToolBox(AGENT_TOOLS)
        self.system = load_prompt("system.txt")
        self.messages: list = []
        self._latest_image: tuple[bytes, str] | None = None
        self._queue: asyncio.Queue[Turn] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self.busy = False

    # ── inputs ───────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._client is not None or has_claude_credentials()

    def set_canvas_image(self, image: bytes, mime: str = "image/jpeg") -> None:
        self._latest_image = (image, mime)

    def submit(self, text: str, source: str, image: bytes | None = None, mime: str = "image/png") -> bool:
        if not self.available:
            return False
        self._queue.put_nowait(Turn(text=text, source=source, image=image, mime=mime))
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())
        return True

    def reset(self) -> None:
        self.messages = []

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()

    # ── turn loop ────────────────────────────────────────────────────────────

    async def _status(self, status: str, detail: str = "") -> None:
        await self.broadcast({"type": "ai_status", "payload": {"status": status, "detail": detail}})

    async def _run(self) -> None:
        while not self._queue.empty():
            turn = await self._queue.get()
            self.busy = True
            try:
                await self._status("thinking")
                reply = await self.run_turn(turn)
                if reply and self.on_reply:
                    await self.on_reply(reply)
            except anthropic.RateLimitError:
                await self._status("idle", "Claude is rate limited, try again shortly")
            except anthropic.APIConnectionError:
                await self._status("idle", "Could not reach Claude")
            except anthropic.APIStatusError as e:
                print(f"[Agent] Claude error {e.status_code}: {e.message}")
                await self._status("idle", "Claude request failed")
            except Exception as e:
                print(f"[Agent] Turn failed: {e!r}")
                await self._status("idle", "AI turn failed")
            else:
                await self._status("idle")
            finally:
                self.busy = False

    def _user_content(self, turn: Turn) -> list:
        content: list = []
        image = (turn.image, turn.mime) if turn.image else self._latest_image
        if image:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image[1],
                    "data": base64.standard_b64encode(image[0]).decode(),
                },
            })
        label = _SOURCE_PREFIX.get(turn.source, "Request")
        content.append({
            "type": "text",
            "text": f"Board: {board_summary()}\n\n{label}: {turn.text}",
        })
        return content

    async def run_turn(self, turn: Turn) -> str:
        """Run one user turn through the tool loop; returns the spoken reply."""
        if len(self.messages) > MAX_HISTORY_MESSAGES:
            self.messages = []
        self.messages.append({"role": "user", "content": self._user_content(turn)})

        client = self._client or get_client()
        started = time.monotonic()
        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            response = await client.beta.messages.create(
                **request_defaults(CLAUDE_MODEL, CLAUDE_AGENT_EFFORT),
                max_tokens=16000,
                system=self.system,
                tools=self.tools.definitions,
                messages=self.messages,
                cache_control={"type": "ephemeral"},
            )
            # Append the full content unchanged (thinking + tool_use blocks).
            self.messages.append({"role": "assistant", "content": response.content})
            reply = text_of(response.content)

            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                break

            results = []
            for block in response.content:
                if getattr(block, "type", "") != "tool_use":
                    continue
                out, is_error = self.tools.run(block.name, block.input)
                print(f"[Agent] {block.name}({json.dumps(block.input)[:160]}) -> {out[:100]}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": out, "is_error": is_error})
            # If the round limit is hit here, history ends on these tool results;
            # the next turn's user message is merged into the same user turn.
            self.messages.append({"role": "user", "content": results})

        print(f"[Agent] {turn.source} turn done in {time.monotonic() - started:.1f}s reply={reply[:80]!r}")
        return reply
