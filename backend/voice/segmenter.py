"""
Energy-based utterance segmentation for the microphone stream.

The browser streams 16 kHz mono PCM16 (with its own noise suppression and
echo cancellation). We cut that stream into utterances: speech starts when a
chunk is loud enough, and ends after END_SILENCE_MS of quiet. Each finished
utterance is transcribed once.
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass

SAMPLE_RATE = 16000


def rms(pcm16: bytes) -> float:
    if len(pcm16) < 2:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm16[: len(pcm16) - len(pcm16) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0


@dataclass
class SpeechStarted:
    pass


@dataclass
class Utterance:
    pcm: bytes

    @property
    def duration_ms(self) -> float:
        return len(self.pcm) / 2 / SAMPLE_RATE * 1000


class UtteranceSegmenter:
    def __init__(
        self,
        threshold: float = 0.015,
        end_silence_ms: int = 700,
        min_speech_ms: int = 350,
        max_utterance_ms: int = 30000,
        preroll_ms: int = 300,
    ):
        self.threshold = threshold
        self.end_silence_ms = end_silence_ms
        self.min_speech_ms = min_speech_ms
        self.max_utterance_ms = max_utterance_ms
        self.preroll_bytes = int(SAMPLE_RATE * 2 * preroll_ms / 1000)
        self.reset()

    def reset(self) -> None:
        self._in_speech = False
        self._buf = bytearray()
        self._preroll = bytearray()
        self._silence_ms = 0.0
        self._voiced_ms = 0.0

    def feed(self, pcm: bytes) -> list:
        """Feed one chunk; returns events (SpeechStarted / Utterance)."""
        events: list = []
        chunk_ms = len(pcm) / 2 / SAMPLE_RATE * 1000
        loud = rms(pcm) >= self.threshold

        if not self._in_speech:
            if loud:
                self._in_speech = True
                self._buf = bytearray(self._preroll) + pcm
                self._silence_ms = 0.0
                self._voiced_ms = chunk_ms
                events.append(SpeechStarted())
            else:
                self._preroll += pcm
                del self._preroll[: max(0, len(self._preroll) - self.preroll_bytes)]
            return events

        self._buf += pcm
        if loud:
            self._silence_ms = 0.0
            self._voiced_ms += chunk_ms
        else:
            self._silence_ms += chunk_ms

        too_long = len(self._buf) / 2 / SAMPLE_RATE * 1000 >= self.max_utterance_ms
        if self._silence_ms >= self.end_silence_ms or too_long:
            if self._voiced_ms >= self.min_speech_ms:
                events.append(Utterance(bytes(self._buf)))
            self._in_speech = False
            self._buf = bytearray()
            self._preroll = bytearray()
        return events


def pcm16_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    import io
    import wave

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return out.getvalue()
