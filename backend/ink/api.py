"""
HTTP + WebSocket glue for the whiteboard ink features.

  POST /api/ink/recognize   rendered ink cluster → recognized elements
  WS   {"type": "ink_ask"}  "Ask AI" button → turn for the Claude canvas agent
"""

from __future__ import annotations

import base64
import time
from typing import Any, Callable, Optional

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from brain.modes import auto_respond_instruction, auto_respond_triggers, normalize_mode

from .recognizer import PageRect, has_ink_credentials, recognize_ink, to_page_elements

# Max decoded image size we accept from the browser.
_MAX_IMAGE_BYTES = 4 * 1024 * 1024
# Minimum gap between automatic "answer my handwritten question" nudges.
AUTO_RESPOND_COOLDOWN_S = 20.0


class RecognizeRequest(BaseModel):
    image: str = Field(description="Base64 PNG/JPEG of the ink cluster (no data: prefix).")
    mime: str = "image/png"
    rect: PageRect
    shapeIds: list[str] = Field(default_factory=list)
    context: str = ""
    autoRespond: bool = True  # legacy clients; `mode` wins when given
    mode: Optional[str] = None


def _short_ids(ids: list[str]) -> str:
    return ",".join(i[6:] if i.startswith("shape:") else i for i in ids[:12])


def build_auto_respond_prompt(
    transcript: str, intent: str, shape_ids: list[str], mode: str = "collab",
) -> str:
    target = _short_ids(shape_ids)
    return (
        f"The user just handwrote this on the whiteboard ({intent}): \"{transcript[:400]}\". "
        f"Its ink strokes are shapeIds [{target}]. Nobody asked you directly. "
        f"{auto_respond_instruction(mode, target)} "
        "Speak at most one short sentence, or stay silent."
    )


def build_ask_prompt(question: str, transcript: str, shape_ids: list[str]) -> str:
    target = _short_ids(shape_ids)
    parts = ["The user selected part of the whiteboard and tapped Ask AI."]
    if transcript:
        parts.append(f"Recognized handwriting in the selection: \"{transcript[:600]}\".")
    if target:
        parts.append(f"Selected shapeIds: [{target}].")
    if question:
        parts.append(f"Their request: \"{question[:400]}\".")
    else:
        parts.append(
            "No explicit request: respond to what is selected — answer a question, check "
            "or solve written work, or add one useful thought."
        )
    parts.append(
        "Respond on the canvas next to the selection. Prefer pen-style answers with "
        f"ink_write(near=\"{target}\") and ink_mark / ink_connect; use a sticky note only "
        "if the answer needs more than two lines. Keep voice to one short sentence."
    )
    return " ".join(parts)


class InkCoordinator:
    """Holds cross-request state (cooldowns) and talks to the live agent."""

    def __init__(self, get_agent: Callable[[], Any]):
        self._get_agent = get_agent
        self._last_auto_respond = 0.0

    def maybe_auto_respond(self, result: dict, req: RecognizeRequest, image: bytes) -> bool:
        mode = normalize_mode(req.mode) if req.mode else ("collab" if req.autoRespond else "quiet")
        if not result.get("transcript"):
            return False
        if not auto_respond_triggers(mode, bool(result.get("asks_ai")), result.get("intent", "")):
            return False
        now = time.monotonic()
        if now - self._last_auto_respond < AUTO_RESPOND_COOLDOWN_S:
            return False
        agent = self._get_agent()
        if agent is None:
            return False
        if req.mode and hasattr(agent, "set_mode"):
            agent.set_mode(mode)  # keep the agent in step with the browser's mode
        sent = agent.submit(
            build_auto_respond_prompt(
                result["transcript"], result.get("intent", "note"), req.shapeIds, mode,
            ),
            source="auto_answer", image=image, mime=req.mime,
        )
        if sent:
            self._last_auto_respond = now
        return sent

    def ask(self, payload: dict) -> bool:
        agent = self._get_agent()
        if agent is None:
            return False
        image: Optional[bytes] = None
        if payload.get("image"):
            try:
                image = base64.b64decode(payload["image"])
            except Exception:
                image = None
        prompt = build_ask_prompt(
            str(payload.get("question", "")).strip(),
            str(payload.get("transcript", "")).strip(),
            [str(i) for i in payload.get("shapeIds", []) if i],
        )
        return agent.submit(prompt, source="ask", image=image, mime=payload.get("mime", "image/png"))


def _note_cluster(req: RecognizeRequest, result: dict) -> None:
    """Make the recognized cluster visible to Claude before the next snapshot."""
    from tools.snapshot import note_recognized_cluster

    els = result["elements"]
    if els:
        x1 = min(e["x"] for e in els)
        y1 = min(e["y"] for e in els)
        x2 = max(e["x"] + e["w"] for e in els)
        y2 = max(e["y"] + e["h"] for e in els)
        bounds = {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}
    else:
        r = req.rect
        bounds = {"x": r.x, "y": r.y, "w": r.w, "h": r.h}
    text = result["transcript"] or (f"[sketch] {result['summary']}" if result["summary"] else "")
    note_recognized_cluster(req.shapeIds, bounds, text)


def create_ink_router(coordinator: InkCoordinator) -> APIRouter:
    router = APIRouter(prefix="/api/ink", tags=["ink"])

    @router.post("/recognize")
    async def recognize(req: RecognizeRequest):
        if not has_ink_credentials():
            raise HTTPException(status_code=503, detail="Ink recognition needs ANTHROPIC_API_KEY")
        try:
            image = base64.b64decode(req.image, validate=False)
        except Exception:
            raise HTTPException(status_code=400, detail="image must be base64")
        if not image or len(image) > _MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="image missing or too large")
        if req.rect.w <= 0 or req.rect.h <= 0:
            raise HTTPException(status_code=400, detail="rect must have positive size")

        try:
            recognition = await recognize_ink(image, req.mime, req.context)
        except anthropic.RateLimitError:
            raise HTTPException(status_code=429, detail="Claude is rate limited")
        except anthropic.APIStatusError as exc:
            print(f"[Ink] Claude error {exc.status_code}: {exc.message[:300]}")
            raise HTTPException(status_code=502, detail="Ink recognition failed")
        except Exception as exc:  # network errors, refusals, malformed output
            print(f"[Ink] Recognition failed: {exc!r}")
            raise HTTPException(status_code=502, detail="Ink recognition failed")

        result = {
            "elements": to_page_elements(recognition, req.rect),
            "transcript": recognition.transcript.strip(),
            "summary": recognition.summary.strip(),
            "intent": recognition.intent,
            "asks_ai": bool(recognition.asks_ai),
        }
        _note_cluster(req, result)
        result["autoResponded"] = coordinator.maybe_auto_respond(result, req, image)
        print(
            f"[Ink] {len(result['elements'])} elements, intent={result['intent']} "
            f"asks_ai={result['asks_ai']} transcript={result['transcript'][:80]!r}"
        )
        return result

    return router
