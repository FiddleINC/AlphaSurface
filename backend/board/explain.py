"""
"Explain my board": a written summary of the current page.

  POST /api/board/explain  {image, mime, items[], pageName}  →  BoardExplanation

The browser sends a screenshot of the page plus the text of every shape
(handwriting already transcribed by the ink recognizer). Claude returns a
structured summary that the browser shows in a panel and can copy, save as
Markdown or export as a PDF together with the board image.

Stateless on purpose: everything needed comes in the request, so it does not
depend on the shared canvas_state.
"""

from __future__ import annotations

import base64
from typing import Literal

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from brain.claude import get_client, request_defaults
from model_config import CLAUDE_EXPLAIN_EFFORT, CLAUDE_MODEL, has_claude_credentials

_MAX_IMAGE_BYTES = 6 * 1024 * 1024
_MAX_ITEMS = 300


class BoardItem(BaseModel):
    type: str = "shape"
    text: str = ""
    by: Literal["user", "ai"] = "user"


class ExplainRequest(BaseModel):
    image: str = ""
    mime: str = "image/jpeg"
    items: list[BoardItem] = Field(default_factory=list)
    pageName: str = ""


class BoardExplanation(BaseModel):
    title: str = Field(description="A short title for what this board is about (max 8 words).")
    overview: str = Field(description="2-4 sentences: what the user worked on and where they got to.")
    key_points: list[str] = Field(
        default_factory=list,
        description="The main ideas, results or decisions on the board, 3-7 items, each one sentence.",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="Unresolved questions, mistakes or gaps still on the board, 0-4 items.",
    )
    next_steps: list[str] = Field(
        default_factory=list, description="Concrete suggested next steps, 1-3 items.",
    )


_SYSTEM = """\
You write a clear summary of a user's whiteboard session so they can keep it, review it
later or share it. The board mixes the user's handwriting (already transcribed for you,
though transcriptions can have small errors) and content an AI assistant added.

Write about the user's work, in plain language, addressed to the user ("You worked out...").
Reference the actual content; never invent anything that is not on the board. Correct
obvious transcription slips using the screenshot. Keep math in plain readable notation.
If the board has almost no content, say so briefly in the overview and keep lists short.
"""


def format_items(items: list[BoardItem]) -> str:
    lines = []
    for it in items[:_MAX_ITEMS]:
        text = " ".join(it.text.split())[:400]
        if text:
            who = "AI" if it.by == "ai" else "user"
            lines.append(f"- [{it.type}, by {who}] {text}")
    return "\n".join(lines) or "(no readable text on the board)"


def to_markdown(ex: BoardExplanation, page_name: str = "") -> str:
    out = [f"# {ex.title or page_name or 'Board summary'}", "", ex.overview.strip(), ""]
    for heading, items in (
        ("Key points", ex.key_points),
        ("Open questions", ex.open_questions),
        ("Next steps", ex.next_steps),
    ):
        if items:
            out += [f"## {heading}", *[f"- {i}" for i in items], ""]
    return "\n".join(out).strip() + "\n"


async def explain_board(req: ExplainRequest, client=None) -> BoardExplanation:
    content: list = []
    if req.image:
        try:
            image = base64.b64decode(req.image, validate=False)
        except Exception:
            raise HTTPException(status_code=400, detail="image must be base64")
        if len(image) > _MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="image too large")
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": req.mime,
            "data": base64.standard_b64encode(image).decode(),
        }})
    page = f" (page \"{req.pageName[:80]}\")" if req.pageName else ""
    content.append({"type": "text", "text": (
        f"Summarize this whiteboard{page}. Text on the board:\n{format_items(req.items)}"
    )})

    response = await (client or get_client()).beta.messages.parse(
        **request_defaults(CLAUDE_MODEL, CLAUDE_EXPLAIN_EFFORT),
        max_tokens=16000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_format=BoardExplanation,
    )
    if response.parsed_output is None:
        raise HTTPException(status_code=502, detail="Could not summarize the board")
    return response.parsed_output


def create_board_router() -> APIRouter:
    router = APIRouter(prefix="/api/board", tags=["board"])

    @router.post("/explain")
    async def explain(req: ExplainRequest):
        if not has_claude_credentials():
            raise HTTPException(status_code=503, detail="Explain needs ANTHROPIC_API_KEY")
        if not req.image and not any(i.text.strip() for i in req.items):
            raise HTTPException(status_code=400, detail="The board is empty")
        try:
            ex = await explain_board(req)
        except HTTPException:
            raise
        except anthropic.RateLimitError:
            raise HTTPException(status_code=429, detail="Claude is rate limited, try again shortly")
        except anthropic.APIStatusError as exc:
            print(f"[Explain] Claude error {exc.status_code}: {exc.message[:300]}")
            raise HTTPException(status_code=502, detail="Could not summarize the board")
        except Exception as exc:
            print(f"[Explain] Failed: {exc!r}")
            raise HTTPException(status_code=502, detail="Could not summarize the board")
        return {**ex.model_dump(), "markdown": to_markdown(ex, req.pageName)}

    return router
