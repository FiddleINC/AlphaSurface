"""Model + provider settings. Every value can be overridden with an env var."""

import os


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


# ── Claude (reasoning, canvas actions, handwriting) ──────────────────────────
# The canvas agent that answers voice, Ask AI and handwritten questions.
CLAUDE_MODEL = _env("ALPHASURFACE_CLAUDE_MODEL", "claude-opus-5-5")
# Effort trades depth for latency. "low" keeps spoken replies snappy.
CLAUDE_AGENT_EFFORT = _env("ALPHASURFACE_AGENT_EFFORT", "low")

# Handwriting / sketch recognition (one structured call per ink cluster).
CLAUDE_INK_MODEL = _env("ALPHASURFACE_INK_MODEL", CLAUDE_MODEL)
CLAUDE_INK_EFFORT = _env("ALPHASURFACE_INK_EFFORT", "low")

# Background sub-agents.
CLAUDE_RESEARCH_EFFORT = _env("ALPHASURFACE_RESEARCH_EFFORT", "medium")
CLAUDE_SUPER_THINK_EFFORT = _env("ALPHASURFACE_SUPER_THINK_EFFORT", "high")

# ── OpenAI (voice only) ──────────────────────────────────────────────────────
OPENAI_STT_MODEL = _env("ALPHASURFACE_STT_MODEL", "gpt-4o-transcribe")
OPENAI_TTS_MODEL = _env("ALPHASURFACE_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = _env("ALPHASURFACE_TTS_VOICE", "alloy")


def has_claude_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def has_openai_credentials() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))
