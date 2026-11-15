"""
AlphaSurface — FastAPI server for the AI whiteboard.

  Browser ──WS──► main.py
     canvas_snapshot  → shared canvas_state (what Claude sees as the board)
     canvas_image     → latest screenshot attached to Claude's next turn
     audio_chunk      → VoiceSession (OpenAI speech-to-text) → CanvasAgent
     ink_ask          → CanvasAgent ("Ask AI" on a selection)
  POST /api/ink/recognize → Claude handwriting recognition (+ auto-answer)

  CanvasAgent (Claude) tool calls → canvas_action_queue → broadcast → browser
  CanvasAgent reply text → VoiceSession (OpenAI text-to-speech) → browser

Run:  uv run uvicorn main:app --reload --port 8000
"""

import asyncio
import base64
import contextlib
import json
import os
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv()

import tools as canvas_tools  # noqa: E402
from brain.canvas_agent import CanvasAgent  # noqa: E402
from dispatcher import register_handler, run_dispatcher  # noqa: E402
from ink.api import InkCoordinator, create_ink_router  # noqa: E402
from sub_agents import find_empty_note_position  # noqa: E402
from tools.snapshot import apply_snapshot  # noqa: E402
from voice.session import VoiceSession  # noqa: E402

connected_clients: list[WebSocket] = []

# Actions any client may relay to all clients (also what the agent emits).
CANVAS_PASSTHROUGH_TYPES = {
    "add_text", "add_note", "add_geo", "add_arrow", "bind_arrow", "add_bookmark",
    "delete_shapes", "update_shape", "move_shape", "clear_canvas", "zoom_to_fit",
    "focus_shape", "select_shapes", "align_shapes", "distribute_shapes", "resize_shape",
    "create_frame", "group_shapes", "label_shape", "stack_shapes", "rotate_shapes",
    "bring_to_front", "send_to_back", "set_viewport", "draw_freehand", "ink_tidy",
    "add_research_card", "focus_artifact", "undo", "redo",
}


async def broadcast(message: dict):
    text = json.dumps(message)
    for ws in list(connected_clients):
        try:
            await ws.send_text(text)
        except Exception:
            if ws in connected_clients:
                connected_clients.remove(ws)


async def drain_canvas_actions():
    queue = canvas_tools.canvas_action_queue
    while True:
        action = await queue.get()
        try:
            await broadcast(action)
        except Exception as e:
            print(f"[App] Broadcast failed: {e}")


# ── Claude brain + OpenAI voice ──────────────────────────────────────────────

voice: VoiceSession | None = None


async def _speak_reply(text: str) -> None:
    if voice is not None:
        await voice.speak(text)


agent = CanvasAgent(broadcast=broadcast, on_reply=_speak_reply)
voice = VoiceSession(broadcast=broadcast, submit=lambda text: agent.submit(text, source="voice"))
ink_coordinator = InkCoordinator(lambda: agent)


async def _run_subagent(name: str, run_fn, payload: dict, *extra) -> None:
    status_id = f"shape:task_status_{uuid.uuid4().hex[:10]}"
    x, y = find_empty_note_position()
    await broadcast({"type": "add_note", "payload": {
        "id": status_id, "x": x, "y": y, "text": f"{name} running…", "color": "light-violet", "size": "m",
    }})
    try:
        await run_fn(payload, broadcast, *extra)
    finally:
        await broadcast({"type": "delete_shapes", "payload": {"shapeIds": [status_id]}})


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sub_agents.research_agent import run_research
    from sub_agents.super_think_agent import run_super_think

    register_handler("research", lambda p: _run_subagent("Research", run_research, p))
    register_handler(
        "super_think",
        lambda p: _run_subagent("Deep analysis", run_super_think, p, canvas_tools.canvas_state),
    )
    tasks = [asyncio.create_task(run_dispatcher()), asyncio.create_task(drain_canvas_actions())]
    print(f"[App] Claude: {'ready' if agent.available else 'missing ANTHROPIC_API_KEY'} · "
          f"Voice: {'ready' if voice.available else 'off (no OPENAI_API_KEY)'}")
    yield
    await agent.stop()
    for t in tasks:
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t


app = FastAPI(lifespan=lifespan)
app.include_router(create_ink_router(ink_coordinator))
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "claude": agent.available,
        "voice": voice.available,
        "clients": len(connected_clients),
        "canvas_shapes": canvas_tools.canvas_state["shape_count"],
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    await websocket.send_text(json.dumps({"type": "ai_status", "payload": {
        "status": "idle" if agent.available else "disconnected",
        "voice": voice.available,
    }}))

    try:
        while True:
            message: dict = json.loads(await websocket.receive_text())
            msg_type: str = message.get("type", "")
            payload: dict = message.get("payload") or {}

            if msg_type == "canvas_snapshot":
                apply_snapshot(payload)

            elif msg_type == "canvas_image":
                if payload.get("data"):
                    agent.set_canvas_image(base64.b64decode(payload["data"]), payload.get("mime", "image/jpeg"))

            elif msg_type == "audio_chunk":
                if payload.get("data"):
                    voice.push_audio(base64.b64decode(payload["data"]))

            elif msg_type == "set_config":
                # "Start without voice" turns off both the mic and spoken replies.
                voice.enabled = voice.speaker_enabled = bool(payload.get("voiceEnabled", True))
                await websocket.send_text(json.dumps({"type": "config_ack", "payload": {"voice": voice.available}}))

            elif msg_type == "set_audio":
                voice.enabled = not bool(payload.get("muted", False))

            elif msg_type == "set_speaker":
                voice.speaker_enabled = not bool(payload.get("muted", False))
                if not voice.speaker_enabled:
                    await voice.interrupt()

            elif msg_type == "ink_ask":
                if not ink_coordinator.ask(payload):
                    await websocket.send_text(json.dumps({"type": "ai_status", "payload": {
                        "status": "disconnected", "detail": "Claude is not configured (ANTHROPIC_API_KEY)",
                    }}))

            elif msg_type in CANVAS_PASSTHROUGH_TYPES:
                await broadcast(message)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] Error: {e!r}")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
