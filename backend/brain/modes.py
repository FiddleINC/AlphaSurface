"""
Assistant modes: how proactive and how revealing the AI is.

  tutor   Hints and guiding questions; never hands over the final answer.
  checker Only marks work right / wrong / unclear; writes no solutions.
  collab  Full collaborator: answers, explains, adds ideas (the original behaviour).
  quiet   Never acts on its own; responds only when asked directly.

The mode is chosen in the browser and sent over the WebSocket (`set_mode`).
Each agent turn states the mode in its user message (not the system prompt,
so prompt caching is unaffected by switching modes).
"""

from __future__ import annotations

MODES = ("tutor", "checker", "collab", "quiet")
DEFAULT_MODE = "collab"

MODE_RULES = {
    "tutor": (
        "TUTOR. Help the user learn; do not do the work for them. Never write or say the final "
        "answer or a full solution, even when the writing ends in '=' or asks 'what is'. Instead "
        "give ONE hint, the next step, or a guiding question (ink_write, a few words). If their "
        "work has a mistake, ink_mark it with '?' and hint at what to re-check. Correct work gets "
        "a green check plus a short encouragement. Only reveal an answer if the user explicitly "
        "insists (\"just tell me the answer\")."
    ),
    "checker": (
        "CHECKER. Only check the user's work; never solve, explain at length or add new content. "
        "Mark correct steps with a green check, mistakes with a red cross or '?'. You may "
        "ink_write at most four words naming the kind of error (\"sign error\", \"check units\"). "
        "No research, no sticky notes, no diagrams unless the user explicitly asks."
    ),
    "collab": (
        "COLLABORATOR. Answer, solve, explain and add ideas freely, following the default rules."
    ),
    "quiet": (
        "QUIET. The user wants to think without interruption. Respond only to what they asked "
        "directly, as briefly as possible; do not add marks, ideas or extras they did not ask for."
    ),
}


def normalize_mode(mode: object) -> str:
    m = str(mode or "").strip().lower()
    return m if m in MODES else DEFAULT_MODE


def mode_line(mode: str) -> str:
    """One line prepended to each agent turn."""
    return f"Mode: {MODE_RULES[normalize_mode(mode)]}"


def auto_responds(mode: str) -> bool:
    """Whether the AI may act on handwriting without being asked."""
    return normalize_mode(mode) != "quiet"


def auto_respond_triggers(mode: str, asks_ai: bool, intent: str) -> bool:
    """
    Should freshly recognized ink trigger an unprompted turn?

    Every proactive mode answers explicit questions. Tutor and Checker also
    react to written math work (no question needed), since checking work in
    progress is their whole job.
    """
    m = normalize_mode(mode)
    if not auto_responds(m):
        return False
    if asks_ai:
        return True
    return m in ("tutor", "checker") and intent == "math"


def auto_respond_instruction(mode: str, target: str) -> str:
    """What to do with an unprompted handwritten question/work, per mode."""
    m = normalize_mode(mode)
    if m == "tutor":
        return (
            f"Do NOT give the answer. Reply IN INK next to it with ink_write(text=<hint, next step "
            f"or guiding question>, near=\"{target}\"), one short line. If you see a mistake, "
            f"ink_mark it with '?'. If the work is correct and complete, ink_mark a check."
        )
    if m == "checker":
        return (
            f"Do NOT solve it. If it is finished work, ink_mark each checkable part with a check "
            f"or cross (target \"{target}\"); optionally ink_write up to four words naming an "
            f"error. If it is an unanswered question or still in progress, do nothing and say nothing."
        )
    return (
        f"Reply IN INK right next to it: call ink_write(text=<short answer>, near=\"{target}\"). "
        "Keep the written answer to one short line (for math: just the result or the next step). "
        "Optionally ink_mark the key part."
    )
