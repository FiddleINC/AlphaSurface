"""Canvas tools the Claude canvas agent can call.

Each tool is a plain Python function: its signature becomes the JSON input
schema and its docstring the description (see brain/tool_schema.py).
"""

from .state import canvas_action_queue, canvas_state
from .spatial_read import get_viewport_context, find_shape_by_text, get_selected_shapes
from .smart_write import place_near, place_in_empty_space
from .organize import align_shapes, distribute_shapes, stack_shapes
from .basic_write import (
    add_geo_to_canvas, bind_arrow, move_shape, update_shape, delete_shapes,
    zoom_to_fit, undo_last_action,
)
from .pen_draw import draw_freehand
from .ink_annotate import ink_mark, ink_connect, ink_write, tidy_ink
from .dispatch import dispatch_research, dispatch_super_think

# Order is stable on purpose: the tool list is part of the cached prompt prefix.
AGENT_TOOLS = [
    # Read
    get_viewport_context, find_shape_by_text, get_selected_shapes,
    # Pen-style answers (preferred)
    ink_write, ink_mark, ink_connect, tidy_ink, draw_freehand,
    # Typed content
    place_near, place_in_empty_space, add_geo_to_canvas, bind_arrow,
    # Edit / organize
    move_shape, update_shape, delete_shapes,
    align_shapes, distribute_shapes, stack_shapes,
    zoom_to_fit, undo_last_action,
    # Background sub-agents
    dispatch_research, dispatch_super_think,
]

__all__ = ["AGENT_TOOLS", "canvas_action_queue", "canvas_state"]
