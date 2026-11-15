"""
Voice I/O with OpenAI: speech-to-text in, text-to-speech out.

  mic PCM ─► UtteranceSegmenter ─► OpenAI transcription ─► CanvasAgent (Claude)
                                                               │
  browser ◄── audio_response (24 kHz PCM16) ◄── OpenAI TTS ◄────┘ spoken reply

Talking over the AI (barge-in) stops playback immediately.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Awaitable, Callable

from model_config import OPENAI_STT_MODEL, OPENAI_TTS_MODEL, OPENAI_TTS_VOICE, has_openai_credentials

from .segmenter import SpeechStarted, Utterance, UtteranceSegmenter, pcm16_to_wav

BroadcastFn = Callable[[dict], Awaitable[None]]
SubmitFn = Callable[[str], bool]

# Transcripts the STT model tends to produce for noise or silence.
_NOISE_TRANSCRIPTS = {"", "you", "thank you.", "thanks for watching!", "bye.", "."}

_TTS_INSTRUCTIONS = "Speak warmly, naturally and briskly, like a friendly colleague at a whiteboard."


class VoiceSession:
    def __init__(self, broadcast: BroadcastFn, submit: SubmitFn, client=None):
        self.broadcast = broadcast
        self.submit = submit
        self._client = client
        self.segmenter = UtteranceSegmenter()
        self.enabled = True        # mic input accepted
        self.speaker_enabled = True
        self._speaking: asyncio.Task | None = None
        self._pending: set[asyncio.Task] = set()

    @property
    def available(self) -> bool:
        return self._client is not None or has_openai_credentials()

    def _openai(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI()
        return self._client

    # ── input ────────────────────────────────────────────────────────────────

    def push_audio(self, pcm: bytes) -> None:
        if not (self.enabled and self.available):
            return
        for event in self.segmenter.feed(pcm):
            if isinstance(event, SpeechStarted):
                if self.is_speaking:
                    self._spawn(self.interrupt())
                self._spawn(self.broadcast({"type": "ai_status", "payload": {"status": "listening"}}))
            elif isinstance(event, Utterance):
                self._spawn(self._handle_utterance(event))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def transcribe(self, pcm: bytes) -> str:
        result = await self._openai().audio.transcriptions.create(
            model=OPENAI_STT_MODEL,
            file=("speech.wav", pcm16_to_wav(pcm), "audio/wav"),
        )
        return (getattr(result, "text", "") or "").strip()

    async def _handle_utterance(self, utt: Utterance) -> None:
        try:
            text = await self.transcribe(utt.pcm)
        except Exception as e:
            print(f"[Voice] Transcription failed: {e!r}")
            await self.broadcast({"type": "ai_status", "payload": {"status": "idle", "detail": "Could not transcribe"}})
            return
        if text.lower() in _NOISE_TRANSCRIPTS or len(text) < 2:
            await self.broadcast({"type": "ai_status", "payload": {"status": "idle"}})
            return
        print(f"[Voice] Heard ({utt.duration_ms:.0f} ms): {text!r}")
        await self.broadcast({"type": "user_transcript", "payload": {"text": text}})
        self.submit(text)

    # ── output ───────────────────────────────────────────────────────────────

    @property
    def is_speaking(self) -> bool:
        return self._speaking is not None and not self._speaking.done()

    async def speak(self, text: str) -> None:
        """Speak a reply (replaces anything currently being spoken)."""
        await self.broadcast({"type": "ai_reply", "payload": {"text": text}})
        if not (self.speaker_enabled and self.available and text.strip()):
            return
        if self.is_speaking:
            self._speaking.cancel()
        self._speaking = asyncio.create_task(self._stream_tts(text))

    async def _stream_tts(self, text: str) -> None:
        kwargs = dict(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE, input=text[:4000], response_format="pcm")
        if OPENAI_TTS_MODEL.startswith("gpt-"):
            kwargs["instructions"] = _TTS_INSTRUCTIONS
        carry = b""
        try:
            await self.broadcast({"type": "ai_status", "payload": {"status": "speaking"}})
            async with self._openai().audio.speech.with_streaming_response.create(**kwargs) as resp:
                async for chunk in resp.iter_bytes(9600):  # ~200 ms of 24 kHz PCM16
                    data = carry + chunk
                    cut = len(data) - len(data) % 2  # keep whole samples
                    carry = data[cut:]
                    if cut:
                        await self.broadcast({
                            "type": "audio_response",
                            "payload": {"data": base64.b64encode(data[:cut]).decode(), "sample_rate": 24000},
                        })
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[Voice] TTS failed: {e!r}")
        finally:
            await self.broadcast({"type": "ai_status", "payload": {"status": "idle"}})

    async def interrupt(self) -> None:
        if self.is_speaking:
            self._speaking.cancel()
        await self.broadcast({"type": "ai_interrupted", "payload": {}})
