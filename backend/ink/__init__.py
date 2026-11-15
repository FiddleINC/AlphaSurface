"""Ink (pen / finger) understanding for the whiteboard."""

from .recognizer import (
    InkRecognition,
    InkElement,
    PageRect,
    recognize_ink,
    to_page_elements,
)
from .geometry import (
    resolve_targets,
    union_bounds,
    mark_points,
    connector_points,
)

__all__ = [
    "InkRecognition",
    "InkElement",
    "PageRect",
    "recognize_ink",
    "to_page_elements",
    "resolve_targets",
    "union_bounds",
    "mark_points",
    "connector_points",
]
