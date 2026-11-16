"""Canvas tools, placement, shape ids and sub-agent layout — no API keys needed."""

import asyncio

import pytest

from tools import state


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setitem(state.canvas_state, "shapes", [
        {"id": "shape:a", "type": "geo", "x": 0, "y": 0, "w": 200, "h": 100, "text": "Alpha"},
        {"id": "shape:b", "type": "note", "x": 400, "y": 0, "w": 200, "h": 200, "text": "Beta"},
    ])
    monkeypatch.setitem(state.canvas_state, "viewport", {"x": 0, "y": 0, "w": 1600, "h": 1000, "zoom": 1})
    monkeypatch.setitem(state.canvas_state, "selected_shape_ids", [])
    _drain(state.canvas_action_queue)
    yield
    _drain(state.canvas_action_queue)


# ── Shape ids: the model sees ids without "shape:"; the browser needs them ───

def test_tools_send_full_shape_ids(board):
    from tools.basic_write import bind_arrow, delete_shapes, move_shape, update_shape
    from tools.organize import align_shapes, distribute_shapes, stack_shapes

    bind_arrow("a", "shape:b", "", "")
    delete_shapes(["a", "shape:b"])
    move_shape("a", 1, 2)
    update_shape("b", "hi", "")
    align_shapes(["a", "b"], "top")
    distribute_shapes(["a", "b", "c"], "horizontal")
    stack_shapes(["a", "b"], "vertical")
    actions = {a["type"]: a["payload"] for a in _drain(state.canvas_action_queue)}

    assert actions["bind_arrow"]["fromShapeId"] == "shape:a"
    assert actions["bind_arrow"]["toShapeId"] == "shape:b"
    assert actions["delete_shapes"]["shapeIds"] == ["shape:a", "shape:b"]
    assert actions["move_shape"]["shapeId"] == "shape:a"
    assert actions["update_shape"]["shapeId"] == "shape:b"
    for kind in ("align_shapes", "distribute_shapes", "stack_shapes"):
        assert all(i.startswith("shape:") for i in actions[kind]["shapeIds"]), kind


def test_selected_shapes_match_snapshot_ids_without_prefix(board):
    from brain.canvas_agent import board_summary
    from tools.snapshot import apply_snapshot
    from tools.spatial_read import get_selected_shapes

    apply_snapshot({
        "blurryShapes": [{"shapeId": "a", "type": "rectangle", "x": 0, "y": 0, "w": 200, "h": 100, "text": "Alpha"}],
        "selectedShapeIds": ["a"],
        "shape_count": 1,
    })
    sel = get_selected_shapes()
    assert sel["count"] == 1 and sel["selected"][0]["text"] == "Alpha"
    assert '"selected":["a"]' in board_summary()


# ── Colors and placement ─────────────────────────────────────────────────────

def test_normalize_color_aliases_and_fallback():
    from tools.colors import normalize_color
    assert normalize_color("Light Purple", "black") == "light-violet"
    assert normalize_color("gray", "black") == "grey"
    assert normalize_color("cyan", "black") == "light-blue"
    assert normalize_color("chartreuse", "violet") == "violet"
    assert normalize_color("", "yellow") == "yellow"


def test_find_free_spot_avoids_shapes():
    from tools.placement import find_free_spot, overlaps
    shapes = [{"x": 0, "y": 0, "w": 300, "h": 300}]
    assert find_free_spot(1000, 1000, 100, 100, shapes) == (1000, 1000)
    x, y = find_free_spot(50, 50, 100, 100, shapes, pad=10)
    assert (x, y) != (50, 50) and not overlaps(x, y, 100, 100, shapes, 10)


def test_place_near_keeps_requested_geo(board):
    from tools.smart_write import place_near
    place_near("a", "Gamma", "ellipse", "below", "blue")
    (action,) = _drain(state.canvas_action_queue)
    assert action["type"] == "add_geo" and action["payload"]["geo"] == "ellipse"
    assert action["payload"]["y"] >= 100  # below the anchor


def test_board_clear_resets_local_placements(board):
    from tools import smart_write
    from tools.snapshot import apply_snapshot
    smart_write.place_in_empty_space("x", "note", "yellow", 10, 10)
    assert smart_write._local_placed
    state.canvas_state["shape_count"] = 3
    apply_snapshot({"blurryShapes": [], "shape_count": 0})
    assert smart_write._local_placed == []


# ── Sub-agent layout ─────────────────────────────────────────────────────────

def test_research_keeps_up_to_eight_long_bullets(board, monkeypatch):
    from sub_agents import research_agent

    async def fake_research(query):
        return {"title": "T", "format": "long", "bullets": [f"fact {i}" for i in range(10)],
                "source_url": "https://example.com", "source_label": "Ex"}

    monkeypatch.setattr(research_agent, "_research", fake_research)
    sent = []

    async def broadcast(msg):
        sent.append(msg)

    asyncio.run(research_agent.run_research({"query": "q"}, broadcast))
    card = next(m["payload"] for m in sent if m["type"] == "add_research_card")
    bookmark = next(m["payload"] for m in sent if m["type"] == "add_bookmark")
    assert len(card["bullets"]) == 8
    assert card["source"] == {"url": "https://example.com", "label": "Ex"}
    assert bookmark["y"] >= card["y"] + card["h"]


def test_super_think_lays_out_in_viewport_without_overlap(board):
    from sub_agents.super_think_agent import _place_super_think
    from tools.placement import overlaps

    sent = []

    async def broadcast(msg):
        sent.append(msg)

    sections = {"synthesis": ["s1", "s2"], "tensions": ["t1"], "open_questions": ["q1", "q2", "q3"]}
    asyncio.run(_place_super_think(broadcast, sections))
    created = [m["payload"] for m in sent if m["type"] in ("add_geo", "add_note", "add_text")]
    assert len(created) == 3 + 6 + 1
    assert all(p["id"].startswith("shape:") for p in created)
    vp = state.canvas_state["viewport"]
    xs = [p["x"] for p in created]
    assert vp["x"] <= min(xs) <= vp["x"] + vp["w"]
    assert not any(
        overlaps(p["x"], p["y"], p.get("w", 200), p.get("h", 200), state.canvas_state["shapes"], 0) for p in created
    )
    assert sent[-1]["type"] == "focus_artifact"
