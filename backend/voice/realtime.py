"""
OpenAI Realtime voice: the browser talks to a speech-to-speech model over
WebRTC; this server only mints a short-lived client secret for it, so the
real OPENAI_API_KEY never reaches the browser.

  browser mic/speaker ◄──WebRTC──► OpenAI Realtime (gpt-realtime-*)
        │  tool call use_whiteboard(request)
        ▼
  WS voice_request ──► CanvasAgent (Claude) ──► WS voice_result ──► spoken

The voice model's instructions and its one tool live in the browser agent
(frontend/src/voice/realtimeVoice.js).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from model_config import OPENAI_REALTIME_MODEL, OPENAI_REALTIME_VOICE, has_openai_credentials

SESSION_TTL_SECONDS = 600  # the key only needs to live long enough to connect

_client = None


def _openai():
    global _client
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI()
    return _client


def create_voice_router(client=None) -> APIRouter:
    router = APIRouter(prefix="/api/voice", tags=["voice"])

    @router.post("/session")
    async def create_session():
        if client is None and not has_openai_credentials():
            raise HTTPException(status_code=503, detail="Voice needs OPENAI_API_KEY")
        try:
            secret = await (client or _openai()).realtime.client_secrets.create(
                expires_after={"anchor": "created_at", "seconds": SESSION_TTL_SECONDS},
                session={
                    "type": "realtime",
                    "model": OPENAI_REALTIME_MODEL,
                    "audio": {"output": {"voice": OPENAI_REALTIME_VOICE}},
                },
            )
        except Exception as e:
            print(f"[Voice] Could not create Realtime session: {e!r}")
            raise HTTPException(status_code=502, detail="Could not start voice session")
        return {"key": secret.value, "model": OPENAI_REALTIME_MODEL, "expiresAt": secret.expires_at}

    return router
