"""Shared Claude client + request defaults."""

from __future__ import annotations

import anthropic

# Models that accept the server-side refusal fallback: if Claude declines a
# request on policy grounds, the API re-runs it on a suitable fallback model
# inside the same call instead of returning an empty refusal.
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


def request_defaults(model: str, effort: str) -> dict:
    """Common kwargs for client.beta.messages.create / .parse."""
    kwargs: dict = {"model": model, "output_config": {"effort": effort}}
    if model in _FALLBACK_MODELS:
        kwargs["betas"] = [FALLBACK_BETA]
        kwargs["fallbacks"] = "default"
    return kwargs


def text_of(content) -> str:
    """Concatenate the text blocks of a response."""
    return "".join(getattr(b, "text", "") for b in content if getattr(b, "type", "") == "text").strip()
