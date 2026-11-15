"""
Ink recognizer — turns a rendered image of freehand strokes into structure.

The frontend groups nearby pen/finger strokes into a "cluster", renders that
cluster to a PNG covering a known page-space rectangle, and POSTs it to
/api/ink/recognize. Claude (vision + structured output) says what the
strokes are: handwritten text, math, shapes, arrows, or free doodles.

Boxes come back normalized to 0–1000 over the image
([ymin, xmin, ymax, xmax]); `to_page_elements` maps them back into tldraw page
coordinates so the frontend can replace the ink with clean shapes (Tidy) and
the live agent can annotate next to it.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from brain.claude import get_client, request_defaults
from model_config import CLAUDE_INK_EFFORT, CLAUDE_INK_MODEL, has_claude_credentials

ElementKind = Literal["text", "math", "shape", "arrow", "line", "doodle"]
GeoKind = Literal[
    "rectangle", "ellipse", "triangle", "diamond", "star", "cloud",
    "hexagon", "pentagon", "heart", "check-box", "x-box",
]
Intent = Literal["note", "question", "math", "list", "diagram", "drawing", "unknown"]


class InkElement(BaseModel):
    """One recognized element, in normalized image coordinates (0–1000)."""

    kind: ElementKind = Field(description="What this group of strokes is.")
    text: str = Field(
        default="",
        description=(
            "For text/math: exact transcription (keep line breaks as \\n; math as "
            "plain readable notation like 'x^2 + 3x = 10'). For shapes: any text "
            "written inside the shape. For arrows: a label written along it. "
            "For doodles: a 1-5 word description of the drawing."
        ),
    )
    shape: Optional[GeoKind] = Field(
        default=None, description="Only for kind=shape: the closest geometric shape."
    )
    box: list[int] = Field(
        description="Bounding box [ymin, xmin, ymax, xmax], each 0-1000, relative to the image."
    )
    start: Optional[list[int]] = Field(
        default=None, description="Only for arrow/line: tail point [y, x], 0-1000."
    )
    end: Optional[list[int]] = Field(
        default=None, description="Only for arrow/line: head point [y, x], 0-1000."
    )


class InkRecognition(BaseModel):
    elements: list[InkElement] = Field(default_factory=list)
    transcript: str = Field(
        default="",
        description="All handwritten text in reading order, joined with newlines.",
    )
    summary: str = Field(
        default="", description="One short sentence describing what the user drew or wrote."
    )
    intent: Intent = Field(default="unknown")
    asks_ai: bool = Field(
        default=False,
        description=(
            "True only if the writing is a question or unfinished problem that "
            "invites an answer (ends with '?', an equation ending in '=', 'solve', "
            "'what is', 'how do I', 'explain', '@ai', etc.)."
        ),
    )


class PageRect(BaseModel):
    """Page-space rectangle that the submitted image covers exactly."""

    x: float
    y: float
    w: float
    h: float


_SYSTEM = """\
You read handwriting and hand-drawn sketches from a digital whiteboard.
The image shows freehand pen or finger strokes on a white background.
Strokes can be messy: be generous when reading handwriting, use context to
disambiguate letters, and never invent content that is not there.

Split the strokes into elements:
- text: handwritten words or sentences. Group a whole line or paragraph into one element.
- math: equations, formulas, arithmetic. Transcribe in plain notation.
- shape: a closed outline that is clearly a rectangle, circle/ellipse, triangle,
  diamond, star, cloud, etc. If text is written inside, put it in `text` of the
  shape and do NOT emit a separate text element for it.
- arrow: a stroke with an arrowhead. Give tail (`start`) and head (`end`).
- line: a straight or slightly curved connector without an arrowhead.
- doodle: anything else (sketches, scribbles, icons, illustrations, underlines
  you cannot classify). Describe it in `text` in a few words.

Boxes must tightly enclose the strokes of each element. Coordinates are
[ymin, xmin, ymax, xmax] normalized to 0-1000 over the full image.
Return elements in reading order (top-to-bottom, left-to-right).
"""


def has_ink_credentials() -> bool:
    return has_claude_credentials()


class InkRecognitionRefused(Exception):
    pass


async def recognize_ink(
    image_bytes: bytes,
    mime: str = "image/png",
    context: str = "",
    client=None,
) -> InkRecognition:
    """Run Claude on a rendered ink cluster and return normalized elements."""
    import base64

    prompt = "Recognize the handwriting and sketches in this image."
    if context:
        prompt += f"\nNearby canvas context (may help disambiguate): {context[:600]}"

    response = await (client or get_client()).beta.messages.parse(
        **request_defaults(CLAUDE_INK_MODEL, CLAUDE_INK_EFFORT),
        max_tokens=8000,
        system=_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": mime,
                    "data": base64.standard_b64encode(image_bytes).decode(),
                }},
                {"type": "text", "text": prompt},
            ],
        }],
        output_format=InkRecognition,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise InkRecognitionRefused(str(response.stop_reason))
    return response.parsed_output


# ── Coordinate mapping ────────────────────────────────────────────────────────

def _clamp(v: float, lo: float = 0, hi: float = 1000) -> float:
    return max(lo, min(hi, float(v)))


def _norm_point(pt: list[int] | None, rect: PageRect) -> dict | None:
    if not pt or len(pt) < 2:
        return None
    y, x = _clamp(pt[0]), _clamp(pt[1])
    return {
        "x": round(rect.x + x / 1000 * rect.w, 1),
        "y": round(rect.y + y / 1000 * rect.h, 1),
    }


def to_page_elements(recognition: InkRecognition, rect: PageRect) -> list[dict]:
    """Convert normalized elements into page-space dicts the frontend consumes."""
    out: list[dict] = []
    for el in recognition.elements:
        if not el.box or len(el.box) < 4:
            continue
        ymin, xmin, ymax, xmax = (_clamp(v) for v in el.box[:4])
        if ymax < ymin:
            ymin, ymax = ymax, ymin
        if xmax < xmin:
            xmin, xmax = xmax, xmin
        item = {
            "kind": el.kind,
            "text": el.text.strip(),
            "x": round(rect.x + xmin / 1000 * rect.w, 1),
            "y": round(rect.y + ymin / 1000 * rect.h, 1),
            "w": round(max(1.0, (xmax - xmin) / 1000 * rect.w), 1),
            "h": round(max(1.0, (ymax - ymin) / 1000 * rect.h), 1),
        }
        if el.kind == "shape":
            item["shape"] = el.shape or "rectangle"
        if el.kind in ("arrow", "line"):
            start = _norm_point(el.start, rect)
            end = _norm_point(el.end, rect)
            if start is None or end is None:
                # Fall back to the box diagonal (left → right).
                start = {"x": item["x"], "y": item["y"] + item["h"] / 2}
                end = {"x": item["x"] + item["w"], "y": item["y"] + item["h"] / 2}
            item["start"] = start
            item["end"] = end
        out.append(item)
    return out
