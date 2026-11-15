"""Claude canvas agent, tool schemas, snapshot merge and OpenAI voice — all with fake clients."""

import asyncio
import base64
import math
import struct
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
    assert '"text":"12 x 8 ="' in user[1]["text"] and "The user said: what is this?" in user[1]["text"]
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

    async def say(text):
        spoken.append(text)

    async def main():
        agent = CanvasAgent(broadcast=bc, on_reply=say, client=fake)
        agent.submit("a", "voice")
        agent.submit("b", "ask")
        await agent._worker

    asyncio.run(main())
    assert spoken == ["one", "two"]
    assert statuses == ["thinking", "idle", "thinking", "idle"]


# ── Voice (OpenAI) ───────────────────────────────────────────────────────────

def _tone(ms, amp=0.3, rate=16000):
    n = int(rate * ms / 1000)
    return b"".join(struct.pack("<h", int(amp * 32767 * math.sin(i / 8))) for i in range(n))


def _silence(ms, rate=16000):
    return b"\x00\x00" * int(rate * ms / 1000)


def test_segmenter_finds_one_utterance_with_preroll():
    from voice.segmenter import SpeechStarted, Utterance, UtteranceSegmenter

    seg = UtteranceSegmenter()
    events = []
    for chunk in [_silence(256), _tone(256), _tone(256), _silence(256), _silence(256), _silence(256)]:
        events += seg.feed(chunk)
    assert isinstance(events[0], SpeechStarted)
    utt = [e for e in events if isinstance(e, Utterance)]
    # 256 ms pre-roll + 512 ms speech + 768 ms trailing silence
    assert len(utt) == 1 and utt[0].duration_ms == 1536


def test_segmenter_ignores_clicks():
    from voice.segmenter import Utterance, UtteranceSegmenter

    seg = UtteranceSegmenter()
    events = []
    for chunk in [_tone(100), _silence(256), _silence(256), _silence(256)]:
        events += seg.feed(chunk)
    assert not [e for e in events if isinstance(e, Utterance)]


def test_wav_header():
    from voice.segmenter import pcm16_to_wav
    wav = pcm16_to_wav(_silence(100))
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE" and len(wav) == 44 + 3200


class FakeOpenAI:
    def __init__(self, transcript="what is twelve times eight", tts=b"\x01\x02\x03" * 5000):
        self.transcript = transcript
        self.tts = tts
        self.stt_calls = []
        self.tts_calls = []
        outer = self

        class Transcriptions:
            async def create(self, **kw):
                outer.stt_calls.append(kw)
                return SimpleNamespace(text=outer.transcript)

        class Resp:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def iter_bytes(self, size):
                for i in range(0, len(outer.tts), 7001):  # odd sizes on purpose
                    yield outer.tts[i:i + 7001]

        class Streaming:
            def create(self, **kw):
                outer.tts_calls.append(kw)
                return Resp()

        self.audio = SimpleNamespace(
            transcriptions=Transcriptions(),
            speech=SimpleNamespace(with_streaming_response=Streaming()),
        )


def test_voice_utterance_is_transcribed_and_submitted():
    from voice.session import VoiceSession

    submitted, sent = [], []

    async def bc(msg):
        sent.append(msg)

    async def main():
        v = VoiceSession(broadcast=bc, submit=lambda t: submitted.append(t) or True, client=FakeOpenAI())
        for chunk in [_tone(256), _tone(256), _silence(800)]:
            v.push_audio(chunk)
        await asyncio.gather(*list(v._pending))
        return v

    v = asyncio.run(main())
    assert submitted == ["what is twelve times eight"]
    stt = v._client.stt_calls[0]
    assert stt["model"] == "gpt-4o-transcribe" and stt["file"][2] == "audio/wav"
    assert {"type": "user_transcript", "payload": {"text": "what is twelve times eight"}} in sent


def test_voice_drops_noise_transcripts():
    from voice.session import VoiceSession
    submitted = []

    async def bc(msg):
        pass

    async def main():
        v = VoiceSession(broadcast=bc, submit=lambda t: submitted.append(t), client=FakeOpenAI(transcript="you"))
        for chunk in [_tone(256), _tone(256), _silence(800)]:
            v.push_audio(chunk)
        await asyncio.gather(*list(v._pending))

    asyncio.run(main())
    assert submitted == []


def test_voice_speak_streams_whole_pcm_samples():
    from voice.session import VoiceSession
    sent = []

    async def bc(msg):
        sent.append(msg)

    async def main():
        v = VoiceSession(broadcast=bc, submit=lambda t: True, client=FakeOpenAI())
        await v.speak("That's 96.")
        await v._speaking
        return v

    v = asyncio.run(main())
    audio = [base64.b64decode(m["payload"]["data"]) for m in sent if m["type"] == "audio_response"]
    assert audio and all(len(a) % 2 == 0 for a in audio)
    assert sum(len(a) for a in audio) == 15000
    assert sent[0] == {"type": "ai_reply", "payload": {"text": "That's 96."}}
    call = v._client.tts_calls[0]
    assert call["response_format"] == "pcm" and call["model"] == "gpt-4o-mini-tts" and "instructions" in call


def test_voice_barge_in_interrupts_speech():
    from voice.session import VoiceSession
    sent = []

    async def bc(msg):
        sent.append(msg["type"])

    async def main():
        v = VoiceSession(broadcast=bc, submit=lambda t: True, client=FakeOpenAI())
        v._speaking = asyncio.create_task(asyncio.sleep(10))
        v.push_audio(_tone(256))
        await asyncio.gather(*list(v._pending))
        await asyncio.sleep(0)
        return v

    v = asyncio.run(main())
    assert "ai_interrupted" in sent and v._speaking.cancelled()
