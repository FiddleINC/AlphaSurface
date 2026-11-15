"""Claude canvas agent, tool schemas, snapshot merge and Realtime voice glue — fake clients only."""

import asyncio
from types import SimpleNamespace

import pytest

from brain.tool_schema import ToolBox, tool_definition
from tools import AGENT_TOOLS
from tools import state as canvas


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


# ── Tool schemas ─────────────────────────────────────────────────────────────

def test_every_agent_tool_has_a_description_and_valid_schema():
    for fn in AGENT_TOOLS:
        d = tool_definition(fn)
        assert len(d["description"]) > 20, fn.__name__
        assert d["input_schema"]["type"] == "object"
        assert set(d["input_schema"]["required"]) <= set(d["input_schema"]["properties"])


def test_tool_definition_types_defaults_and_hidden_params():
    from tools.basic_write import add_geo_to_canvas, delete_shapes
    d = tool_definition(add_geo_to_canvas)
    props = d["input_schema"]["properties"]
    assert props["x"] == {"type": "integer"} and "semantic_role" not in props
    assert tool_definition(delete_shapes)["input_schema"]["properties"]["shape_ids"] == {
        "type": "array", "items": {"type": "string"}}
    from tools.ink_annotate import ink_mark
    assert tool_definition(ink_mark)["input_schema"]["properties"]["mark"]["default"] == "circle"


def test_toolbox_coerces_args_and_reports_errors():
    def f(n: int, ids: list[str], flag: bool = False) -> str:
        """Test tool with enough description text."""
        return f"{n}|{ids}|{flag}"

    box = ToolBox([f])
    assert box.run("f", {"n": "4.6", "ids": "a, b", "flag": "true"}) == ("5|['a', 'b']|True", False)
    assert box.run("nope", {})[1] is True
    assert box.run("f", {})[1] is True  # missing required arg


# ── Snapshot merge ───────────────────────────────────────────────────────────

def test_snapshot_keeps_ink_cluster_bounds_and_text():
    from tools.snapshot import shapes_from_snapshot
    shapes = shapes_from_snapshot({
        "blurryShapes": [{"shapeId": "lead", "type": "ink", "x": 0, "y": 0, "w": 300, "h": 80, "text": "x^2 = 9"}],
        "focusedShapes": [{"shapeId": "lead", "_type": "draw", "x": 5, "y": 5, "text": "x^2 = 9"}],
    })
    (s,) = shapes
    assert s["id"] == "shape:lead" and s["type"] == "ink" and s["w"] == 300 and s["text"] == "x^2 = 9"


# ── Canvas agent (Claude) ────────────────────────────────────────────────────

def _block(**kw):
    return SimpleNamespace(**kw)


class FakeClaude:
    """Scripted beta.messages.create responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=self)

    async def create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        return self.responses.pop(0)


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setitem(canvas.canvas_state, "shapes", [
        {"id": "shape:q1", "type": "ink", "x": 100, "y": 100, "w": 200, "h": 50, "text": "12 x 8 ="},
    ])
    _drain(canvas.canvas_action_queue)
    yield
    _drain(canvas.canvas_action_queue)


def test_agent_turn_runs_tools_then_returns_spoken_reply(board):
    from brain.canvas_agent import CanvasAgent, Turn

    fake = FakeClaude([
        SimpleNamespace(stop_reason="tool_use", content=[
            _block(type="text", text=""),
            _block(type="tool_use", id="t1", name="ink_write", input={"text": "96", "near": "q1"}),
        ]),
        SimpleNamespace(stop_reason="end_turn", content=[_block(type="text", text="That's 96.")]),
    ])

    async def bc(msg):
        pass

    agent = CanvasAgent(broadcast=bc, client=fake)
    agent.set_canvas_image(b"jpegbytes", "image/jpeg")
    reply = asyncio.run(agent.run_turn(Turn(text="what is this?", source="voice")))

    assert reply == "That's 96."
    actions = _drain(canvas.canvas_action_queue)
    assert actions[0]["type"] == "add_text" and actions[0]["payload"]["text"] == "96"

    first = fake.calls[0]
    user = first["messages"][0]["content"]
    assert user[0]["type"] == "image" and user[0]["source"]["media_type"] == "image/jpeg"
    assert '"text":"12 x 8 ="' in user[1]["text"] and "The user asked by voice: what is this?" in user[1]["text"]
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert first["output_config"] == {"effort": "low"} and first["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in first["tools"]][:4] == [f.__name__ for f in AGENT_TOOLS][:4]

    # Second call carries the assistant tool_use and our tool_result.
    second = fake.calls[1]["messages"]
    assert second[1]["role"] == "assistant" and second[2]["content"][0]["tool_use_id"] == "t1"
    assert second[2]["content"][0]["is_error"] is False


def test_agent_submit_runs_turns_in_order_and_speaks(board):
    from brain.canvas_agent import CanvasAgent

    fake = FakeClaude([
        SimpleNamespace(stop_reason="end_turn", content=[_block(type="text", text="one")]),
        SimpleNamespace(stop_reason="end_turn", content=[_block(type="text", text="two")]),
    ])
    spoken, statuses = [], []

    async def bc(msg):
        statuses.append(msg["payload"]["status"])

    async def say(text, turn):
        spoken.append((text, turn.source, turn.reply_id))

    async def main():
        agent = CanvasAgent(broadcast=bc, on_reply=say, client=fake)
        agent.submit("a", "voice", reply_id="r1")
        agent.submit("b", "ask")
        await agent._worker

    asyncio.run(main())
    assert spoken == [("one", "voice", "r1"), ("two", "ask", None)]
    assert statuses == ["thinking", "idle", "thinking", "idle"]




def test_failed_voice_turn_still_answers_the_waiting_tool_call(board):
    from brain.canvas_agent import CanvasAgent

    class Broken:
        def __init__(self):
            self.beta = SimpleNamespace(messages=self)

        async def create(self, **kw):
            raise RuntimeError("boom")

    replies = []

    async def bc(msg):
        pass

    async def on_reply(text, turn):
        replies.append((text, turn.reply_id))

    async def main():
        agent = CanvasAgent(broadcast=bc, on_reply=on_reply, client=Broken())
        agent.submit("draw a cat", "voice", reply_id="v9")
        await agent._worker

    asyncio.run(main())
    assert replies == [("Sorry, that didn't work: AI turn failed.", "v9")]


# ── Realtime voice ───────────────────────────────────────────────────────────

def test_voice_session_mints_ephemeral_key_with_model_and_voice():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from voice.realtime import create_voice_router

    calls = []

    class Secrets:
        async def create(self, **kw):
            calls.append(kw)
            return SimpleNamespace(value="ek_test", expires_at=123)

    fake = SimpleNamespace(realtime=SimpleNamespace(client_secrets=Secrets()))
    app = FastAPI()
    app.include_router(create_voice_router(client=fake))
    res = TestClient(app).post("/api/voice/session")

    assert res.status_code == 200
    assert res.json() == {"key": "ek_test", "model": "gpt-realtime-2.1", "expiresAt": 123}
    session = calls[0]["session"]
    assert session["type"] == "realtime" and session["model"] == "gpt-realtime-2.1"
    assert session["audio"]["output"]["voice"] == "marin"
    assert calls[0]["expires_after"]["seconds"] <= 600


def test_voice_session_needs_openai_key(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from voice.realtime import create_voice_router

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = FastAPI()
    app.include_router(create_voice_router())
    assert TestClient(app).post("/api/voice/session").status_code == 503


def test_voice_request_reply_is_routed_back_by_id(monkeypatch):
    import main

    sent = []

    async def fake_broadcast(msg):
        sent.append(msg)

    monkeypatch.setattr(main, "broadcast", fake_broadcast)
    from brain.canvas_agent import Turn
    asyncio.run(main._send_reply("It's 96.", Turn(text="x", source="voice", reply_id="abc")))
    assert sent == [
        {"type": "ai_reply", "payload": {"text": "It's 96.", "source": "voice"}},
        {"type": "voice_result", "payload": {"id": "abc", "text": "It's 96."}},
    ]
