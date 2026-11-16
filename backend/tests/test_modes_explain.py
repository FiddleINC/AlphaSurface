import asyncio
import base64
from types import SimpleNamespace

import pytest

from brain.modes import (
    MODES, auto_respond_instruction, auto_respond_triggers, mode_line, normalize_mode,
)


# ── Modes ────────────────────────────────────────────────────────────────────

def test_normalize_mode_falls_back_to_collab():
    assert normalize_mode("TUTOR ") == "tutor"
    assert normalize_mode("nonsense") == "collab"
    assert normalize_mode(None) == "collab"


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_has_a_rule_line(mode):
    assert mode_line(mode).startswith("Mode: ")


def test_auto_respond_triggers_per_mode():
    # Explicit questions: everyone but quiet.
    assert all(auto_respond_triggers(m, True, "question") for m in ("tutor", "checker", "collab"))
    assert not auto_respond_triggers("quiet", True, "question")
    # Written math work without a question: only tutor and checker look at it.
    assert auto_respond_triggers("tutor", False, "math")
    assert auto_respond_triggers("checker", False, "math")
    assert not auto_respond_triggers("collab", False, "math")
    assert not auto_respond_triggers("checker", False, "note")


def test_tutor_and_checker_instructions_withhold_answers():
    assert "Do NOT give the answer" in auto_respond_instruction("tutor", "s1")
    assert "Do NOT solve" in auto_respond_instruction("checker", "s1")
    assert "short answer" in auto_respond_instruction("collab", "s1")


def test_agent_turn_states_the_mode():
    from brain.canvas_agent import CanvasAgent, Turn

    async def noop(_):
        pass

    agent = CanvasAgent(broadcast=noop, client=object())
    agent.set_mode("tutor")
    text = agent._user_content(Turn(text="what is 12 x 8", source="voice"))[-1]["text"]
    assert "Mode: TUTOR" in text
    agent.set_mode("bogus")
    assert agent.mode == "collab"


# ── Mode-aware auto-answer through the recognize endpoint ────────────────────

class _ModeAgent:
    def __init__(self):
        self.turns, self.mode = [], "collab"

    def set_mode(self, mode):
        self.mode = mode

    def submit(self, text, source, image=None, mime="image/png"):
        self.turns.append(text)
        return True


def _ink_client(monkeypatch, intent="math", asks_ai=True):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ink import api
    from ink.recognizer import InkElement, InkRecognition

    agent = _ModeAgent()
    app = FastAPI()
    app.include_router(api.create_ink_router(api.InkCoordinator(lambda: agent)))

    async def fake_recognize(image, mime, context):
        return InkRecognition(
            elements=[InkElement(kind="math", text="2x = 6, x = 3", box=[0, 0, 1000, 1000])],
            transcript="2x = 6, x = 3", intent=intent, asks_ai=asks_ai,
        )

    monkeypatch.setattr(api, "recognize_ink", fake_recognize)
    monkeypatch.setattr(api, "has_ink_credentials", lambda: True)
    return TestClient(app), agent


def _ink_body(**kw):
    return {
        "image": base64.b64encode(b"png").decode(),
        "rect": {"x": 0, "y": 0, "w": 100, "h": 50},
        "shapeIds": ["shape:s1"], **kw,
    }


def test_quiet_mode_never_auto_answers(monkeypatch):
    http, agent = _ink_client(monkeypatch)
    res = http.post("/api/ink/recognize", json=_ink_body(mode="quiet"))
    assert res.json()["autoResponded"] is False and agent.turns == []


def test_checker_reacts_to_math_work_without_a_question(monkeypatch):
    http, agent = _ink_client(monkeypatch, asks_ai=False)
    res = http.post("/api/ink/recognize", json=_ink_body(mode="checker"))
    assert res.json()["autoResponded"] is True
    assert "Do NOT solve" in agent.turns[0] and agent.mode == "checker"


def test_collab_ignores_math_work_without_a_question(monkeypatch):
    http, agent = _ink_client(monkeypatch, asks_ai=False)
    assert http.post("/api/ink/recognize", json=_ink_body(mode="collab")).json()["autoResponded"] is False


# ── Explain my board ─────────────────────────────────────────────────────────

def test_to_markdown_skips_empty_sections():
    from board.explain import BoardExplanation, to_markdown

    md = to_markdown(BoardExplanation(title="Fractions", overview="You added fractions.",
                                      key_points=["1/2 + 1/4 = 3/4"], next_steps=["Try 2/3 + 1/6"]))
    assert md.startswith("# Fractions\n")
    assert "## Key points\n- 1/2 + 1/4 = 3/4" in md
    assert "Open questions" not in md


def test_explain_board_sends_image_and_items():
    from board.explain import BoardExplanation, BoardItem, ExplainRequest, explain_board

    calls = {}

    class FakeMessages:
        async def parse(self, **kw):
            calls.update(kw)
            return SimpleNamespace(parsed_output=BoardExplanation(title="T", overview="O"))

    req = ExplainRequest(
        image=base64.b64encode(b"jpg").decode(), pageName="Page 1",
        items=[BoardItem(type="ink", text="12 x 8 ="), BoardItem(type="text", text="96", by="ai")],
    )
    out = asyncio.run(explain_board(req, client=SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))))
    assert out.title == "T"
    content = calls["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert "[ink, by user] 12 x 8 =" in content[1]["text"] and "[text, by AI] 96" in content[1]["text"]
    assert calls["output_format"] is BoardExplanation


def test_explain_endpoint(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from board import explain

    async def fake_explain(req, client=None):
        return explain.BoardExplanation(title="Plan", overview="You planned.", key_points=["A"])

    monkeypatch.setattr(explain, "explain_board", fake_explain)
    monkeypatch.setattr(explain, "has_claude_credentials", lambda: True)
    app = FastAPI()
    app.include_router(explain.create_board_router())
    http = TestClient(app)

    res = http.post("/api/board/explain", json={"items": [{"type": "ink", "text": "plan"}]})
    assert res.status_code == 200
    assert res.json()["title"] == "Plan" and res.json()["markdown"].startswith("# Plan")

    assert http.post("/api/board/explain", json={"items": []}).status_code == 400
    monkeypatch.setattr(explain, "has_claude_credentials", lambda: False)
    assert http.post("/api/board/explain", json={"items": [{"text": "x"}]}).status_code == 503
