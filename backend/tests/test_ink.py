import asyncio
import base64

import pytest

from ink.geometry import VALID_MARKS, connector_points, mark_points, resolve_targets, union_bounds
from ink.recognizer import InkElement, InkRecognition, PageRect, to_page_elements


SHAPES = [
    {"id": "shape:a", "type": "draw", "x": 100, "y": 100, "w": 200, "h": 50, "text": "x^2 = 9"},
    {"id": "shape:b", "type": "draw", "x": 600, "y": 400, "w": 100, "h": 80, "text": "answer"},
    {"id": "shape:c", "type": "note", "x": 0, "y": 600, "w": 200, "h": 200, "text": "a much longer note about x^2 = 9"},
]


def _drain(queue):
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


# ── Coordinate mapping ───────────────────────────────────────────────────────

def test_to_page_elements_maps_normalized_boxes():
    rec = InkRecognition(elements=[
        InkElement(kind="text", text=" hello ", box=[0, 0, 500, 1000]),
        InkElement(kind="shape", shape="ellipse", box=[500, 250, 1000, 750]),
        InkElement(kind="arrow", box=[0, 0, 1000, 1000], start=[1000, 0], end=[0, 1000]),
    ])
    rect = PageRect(x=100, y=200, w=400, h=200)
    els = to_page_elements(rec, rect)

    assert els[0] == {"kind": "text", "text": "hello", "x": 100, "y": 200, "w": 400, "h": 100}
    assert els[1]["shape"] == "ellipse"
    assert (els[1]["x"], els[1]["y"], els[1]["w"], els[1]["h"]) == (200, 300, 200, 100)
    assert els[2]["start"] == {"x": 100, "y": 400}
    assert els[2]["end"] == {"x": 500, "y": 200}


def test_to_page_elements_clamps_and_fixes_inverted_boxes():
    rec = InkRecognition(elements=[
        InkElement(kind="text", text="t", box=[800, 900, 200, -50]),
        InkElement(kind="line", text="", box=[0, 0, 10, 1000]),  # no start/end → fallback
        InkElement(kind="doodle", text="sun", box=[1, 2]),  # malformed → skipped
    ])
    els = to_page_elements(rec, PageRect(x=0, y=0, w=1000, h=1000))
    assert len(els) == 2
    assert els[0]["x"] == 0 and els[0]["w"] == 900 and els[0]["y"] == 200 and els[0]["h"] == 600
    assert els[1]["start"]["x"] == 0 and els[1]["end"]["x"] == 1000


def test_response_schema_is_accepted_by_genai():
    from google.genai import types
    cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=InkRecognition)
    assert cfg.response_schema is InkRecognition


# ── Target resolution + geometry ─────────────────────────────────────────────

def test_resolve_targets_by_id_ids_region_and_text():
    matched, b = resolve_targets("a", SHAPES)
    assert [s["id"] for s in matched] == ["shape:a"] and b["w"] == 200

    matched, b = resolve_targets("shape:a, b", SHAPES)
    assert len(matched) == 2 and b == {"x": 100.0, "y": 100.0, "w": 600.0, "h": 380.0}

    matched, b = resolve_targets("10,20,30,40", SHAPES)
    assert matched == [] and b == {"x": 10, "y": 20, "w": 30, "h": 40}

    # Text match prefers the tightest (shortest) hit.
    matched, _ = resolve_targets("X^2", SHAPES)
    assert matched[0]["id"] == "shape:a"

    assert resolve_targets("nothing here", SHAPES) == ([], None)
    assert resolve_targets("", SHAPES) == ([], None)


def test_union_bounds_empty():
    assert union_bounds([]) is None


@pytest.mark.parametrize("mark", VALID_MARKS)
def test_every_mark_produces_strokes(mark):
    strokes = mark_points(mark, {"x": 100, "y": 100, "w": 200, "h": 50}, seed=1)
    assert strokes and all(len(s) >= 2 for s in strokes)
    for s in strokes:
        for p in s:
            assert isinstance(p["x"], int) and isinstance(p["y"], int)


def test_circle_encloses_target():
    (stroke,) = mark_points("circle", {"x": 100, "y": 100, "w": 200, "h": 50}, seed=3)
    xs, ys = [p["x"] for p in stroke], [p["y"] for p in stroke]
    assert min(xs) < 100 and max(xs) > 300 and min(ys) < 100 and max(ys) > 150


def test_unknown_mark_raises():
    with pytest.raises(ValueError):
        mark_points("spiral", {"x": 0, "y": 0, "w": 1, "h": 1})


def test_connector_runs_between_boxes_and_ends_at_tip():
    a = {"x": 0, "y": 0, "w": 100, "h": 100}
    b = {"x": 500, "y": 0, "w": 100, "h": 100}
    pts = connector_points(a, b, seed=2)
    assert pts[0]["x"] >= 100  # starts outside box a's right edge
    assert pts[-1]["x"] <= 500  # tip stops before box b
    assert pts[-1] == pts[-3]   # arrowhead returns to the tip


# ── Live agent ink tools ─────────────────────────────────────────────────────

@pytest.fixture
def canvas(monkeypatch):
    from tools import state
    monkeypatch.setitem(state.canvas_state, "shapes", list(SHAPES))
    _drain(state.canvas_action_queue)
    yield state
    _drain(state.canvas_action_queue)


def test_ink_mark_emits_animated_ai_stroke(canvas):
    from tools.ink_annotate import ink_mark
    result = ink_mark("x^2", "tick", color="green")
    assert result.startswith("Drew check")
    (action,) = _drain(canvas.canvas_action_queue)
    assert action["type"] == "draw_freehand"
    p = action["payload"]
    assert p["color"] == "green" and p["animate"] is True
    assert p["meta"]["addedBy"] == "ai_ink" and p["meta"]["linked_to"] == ["shape:a"]


def test_ink_mark_rejects_unknown(canvas):
    from tools.ink_annotate import ink_mark
    assert "Unknown mark" in ink_mark("a", "spiral")
    assert "Could not find" in ink_mark("zzz", "circle")
    assert _drain(canvas.canvas_action_queue) == []


def test_ink_write_places_handwritten_text_beside_target(canvas):
    from tools.ink_annotate import ink_write
    ink_write("x = ±3", near="a")
    (action,) = _drain(canvas.canvas_action_queue)
    p = action["payload"]
    assert action["type"] == "add_text" and p["font"] == "draw" and p["color"] == "violet"
    assert p["x"] >= 300  # to the right of shape a (x 100 + w 200)


def test_ink_connect_with_label(canvas):
    from tools.ink_annotate import ink_connect
    ink_connect("a", "b", label="because")
    actions = _drain(canvas.canvas_action_queue)
    assert [a["type"] for a in actions] == ["draw_freehand", "add_text"]


def test_tidy_ink_emits_frontend_action(canvas):
    from tools.ink_annotate import tidy_ink
    tidy_ink("selected")
    (action,) = _drain(canvas.canvas_action_queue)
    assert action == {"type": "ink_tidy", "payload": {"scope": "selection"}}


# ── HTTP endpoint ────────────────────────────────────────────────────────────

class _FakeAgent:
    def __init__(self):
        self.turns = []

    def send_user_turn(self, text, image=None, mime="image/png"):
        self.turns.append(text)
        return True


@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ink import api

    fake_agent = _FakeAgent()
    coordinator = api.InkCoordinator(lambda: fake_agent)
    app = FastAPI()
    app.include_router(api.create_ink_router(coordinator))

    async def fake_recognize(image, mime, context):
        return InkRecognition(
            elements=[InkElement(kind="math", text="12 x 8 =", box=[0, 0, 1000, 1000])],
            transcript="12 x 8 =", summary="A multiplication", intent="math", asks_ai=True,
        )

    monkeypatch.setattr(api, "recognize_ink", fake_recognize)
    monkeypatch.setattr(api, "has_ink_credentials", lambda: True)
    return TestClient(app), fake_agent


def _body(**kw):
    body = {
        "image": base64.b64encode(b"\x89PNG fake").decode(),
        "rect": {"x": 10, "y": 20, "w": 300, "h": 100},
        "shapeIds": ["shape:s1", "shape:s2"],
    }
    body.update(kw)
    return body


def test_recognize_endpoint_returns_page_elements_and_auto_responds(client):
    http, agent = client
    res = http.post("/api/ink/recognize", json=_body())
    assert res.status_code == 200
    data = res.json()
    assert data["elements"][0] == {"kind": "math", "text": "12 x 8 =", "x": 10, "y": 20, "w": 300, "h": 100}
    assert data["asks_ai"] is True and data["autoResponded"] is True
    assert 'near="s1,s2"' in agent.turns[0]

    # Cooldown: a second question right away does not nudge the agent again.
    res = http.post("/api/ink/recognize", json=_body())
    assert res.json()["autoResponded"] is False and len(agent.turns) == 1


def test_recognize_endpoint_respects_auto_respond_off(client):
    http, agent = client
    res = http.post("/api/ink/recognize", json=_body(autoRespond=False))
    assert res.json()["autoResponded"] is False and agent.turns == []


def test_recognize_endpoint_validates_input(client, monkeypatch):
    http, _ = client
    assert http.post("/api/ink/recognize", json=_body(rect={"x": 0, "y": 0, "w": 0, "h": 10})).status_code == 400
    assert http.post("/api/ink/recognize", json=_body(image="")).status_code == 413

    from ink import api
    monkeypatch.setattr(api, "has_ink_credentials", lambda: False)
    assert http.post("/api/ink/recognize", json=_body()).status_code == 503


def test_ask_prompt_mentions_selection():
    from ink.api import InkCoordinator
    agent = _FakeAgent()
    InkCoordinator(lambda: agent).ask({"shapeIds": ["shape:q"], "transcript": "why?", "question": ""})
    assert "[q]" in agent.turns[0] and "why?" in agent.turns[0]
