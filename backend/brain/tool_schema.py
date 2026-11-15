"""
Turn plain Python tool functions into Claude tool definitions and run them.

The canvas tools are ordinary functions (signature + docstring). This keeps
them provider-neutral and testable without any SDK.
"""

from __future__ import annotations

import inspect
import json
import typing
from typing import Callable

# Bookkeeping params some tools accept but the model should never set.
HIDDEN_PARAMS = {"semantic_role", "source", "confidence", "linked_to"}

_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _json_type(annotation) -> dict:
    if annotation in _TYPES:
        return {"type": _TYPES[annotation]}
    origin = typing.get_origin(annotation)
    if origin in (list, typing.List):
        (item,) = typing.get_args(annotation) or (str,)
        return {"type": "array", "items": _json_type(item)}
    return {"type": "string"}


def tool_definition(fn: Callable) -> dict:
    sig = inspect.signature(fn)
    props: dict = {}
    required: list[str] = []
    for name, p in sig.parameters.items():
        has_default = p.default is not inspect.Parameter.empty
        if name in HIDDEN_PARAMS and has_default:
            continue
        schema = _json_type(p.annotation)
        if has_default:
            schema["default"] = p.default
        else:
            required.append(name)
        props[name] = schema
    return {
        "name": fn.__name__,
        "description": (inspect.getdoc(fn) or fn.__name__)[:4000],
        "input_schema": {"type": "object", "properties": props, "required": required},
    }


def _coerce(value, annotation):
    try:
        if annotation is int:
            return int(round(float(value)))
        if annotation is float:
            return float(value)
        if annotation is bool:
            return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
        if annotation is str and not isinstance(value, str):
            return json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        if typing.get_origin(annotation) is list and isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
    except (TypeError, ValueError):
        pass
    return value


class ToolBox:
    def __init__(self, functions: list[Callable]):
        self._fns = {f.__name__: f for f in functions}
        self.definitions = [tool_definition(f) for f in functions]

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Execute a tool. Returns (result_text, is_error)."""
        fn = self._fns.get(name)
        if fn is None:
            return f"Unknown tool '{name}'", True
        sig = inspect.signature(fn)
        kwargs = {
            k: _coerce(v, sig.parameters[k].annotation)
            for k, v in (args or {}).items() if k in sig.parameters
        }
        try:
            result = fn(**kwargs)
        except TypeError as e:
            return f"Bad arguments for {name}: {e}", True
        except Exception as e:  # tool bug: report to the model, keep the turn alive
            return f"{name} failed: {e}", True
        if not isinstance(result, str):
            result = json.dumps(result, default=str)
        return result[:8000], False
