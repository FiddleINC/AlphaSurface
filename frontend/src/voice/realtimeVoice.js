// ── Realtime voice (OpenAI) ───────────────────────────────────────────────────
// Speech-to-speech conversation over WebRTC: the SDK opens the microphone,
// plays the model's voice, and handles turn-taking and barge-in.
//
// The voice model is only the conversational front. It has one tool,
// `use_whiteboard`, that hands every board-related request to the backend,
// where Claude reads the board, acts on it, and returns a short answer that
// the voice model then says out loud.
//
//   you ⇄ OpenAI Realtime ──use_whiteboard(request)──► WS voice_request
//                        ◄──────────── answer ──────── WS voice_result (Claude)

import { OpenAIRealtimeWebRTC, RealtimeAgent, RealtimeSession, tool } from "@openai/agents/realtime"
import { z } from "zod"

const INSTRUCTIONS = `You are the voice of AlphaSurface, an AI partner on a shared whiteboard.
The user writes and sketches with a pencil or finger while talking to you.
You cannot see the board yourself. For ANYTHING involving the board — what they wrote or drew,
answering or checking their work, writing, drawing, marking, tidying, organizing, research,
or deep analysis — call use_whiteboard with their request in your own words, including any
detail they gave. Before calling it, say at most two or three words ("Let me look.", "On it.").
When it returns, say its answer naturally in one short sentence; don't add facts it did not give.
For small talk that has nothing to do with the board, just answer briefly.
Be warm and concise. Never read long text aloud.`

const TOOL_TIMEOUT_MS = 60_000

/**
 * Start a voice session.
 * @param {object} opts
 * @param {(msg: object) => void} opts.send   send a message to the backend WebSocket
 * @param {(state: string) => void} opts.onState  "listening" | "thinking" | "speaking" | "idle" | "off"
 * @param {(reason: string) => void} [opts.onDisconnect]  the call dropped after connecting
 * @returns {Promise<{resolve, speak, mute, setSpeakerMuted, close}>}
 */
export async function startRealtimeVoice({ send, onState, onDisconnect }) {
  const res = await fetch("/api/voice/session", { method: "POST" })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || `Voice session failed (${res.status})`)
  }
  const { key, model } = await res.json()

  const pending = new Map() // request id → resolve(answer)

  const useWhiteboard = tool({
    name: "use_whiteboard",
    description:
      "Hand a request to the whiteboard AI, which can see the board (including the user's " +
      "handwriting), write and draw on it, tidy it, and research. Returns a short answer to say.",
    parameters: z.object({
      request: z.string().describe("The user's request, self-contained, in your own words"),
    }),
    timeoutMs: TOOL_TIMEOUT_MS,
    execute: ({ request }) => new Promise((resolve) => {
      const id = crypto.randomUUID()
      pending.set(id, resolve)
      onState?.("thinking")
      send({ type: "voice_request", payload: { id, request } })
    }),
  })

  const agent = new RealtimeAgent({ name: "AlphaSurface", instructions: INSTRUCTIONS, tools: [useWhiteboard] })

  // Our own <audio> element so the speaker toggle can mute playback.
  const audioElement = document.createElement("audio")
  audioElement.autoplay = true
  const session = new RealtimeSession(agent, {
    transport: new OpenAIRealtimeWebRTC({ audioElement }),
    model,
  })

  session.on("audio_start", () => onState?.("speaking"))
  session.on("audio_stopped", () => onState?.("idle"))
  session.on("audio_interrupted", () => onState?.("listening"))
  session.on("transport_event", (event) => {
    if (event.type === "input_audio_buffer.speech_started") onState?.("listening")
    else if (event.type === "input_audio_buffer.speech_stopped") onState?.("idle")
  })
  session.on("error", (err) => console.warn("[Voice] Realtime error", err))
  if (import.meta.env.DEV) window.__alphaVoiceSession = session // debugging / e2e hook

  // The calls endpoint needs ?model= even with an ephemeral key (verified
  // against the live API: without it, 400 "You must provide a model parameter").
  let closedByUs = false
  const failPending = (text) => {
    for (const done of pending.values()) done(text)
    pending.clear()
  }

  await session.connect({
    apiKey: key,
    url: `https://api.openai.com/v1/realtime/calls?model=${encodeURIComponent(model)}`,
  })

  // If the call drops (network change, laptop sleep, blocked media), say so
  // instead of silently showing voice as on.
  session.transport.on("connection_change", (status) => {
    if (status !== "disconnected" || closedByUs) return
    failPending("The voice connection dropped.")
    onState?.("off")
    onDisconnect?.("Voice disconnected. Restart the app to reconnect.")
  })

  return {
    /** Deliver Claude's answer to the waiting use_whiteboard call. */
    resolve(id, text) {
      const done = pending.get(id)
      if (!done) return false
      pending.delete(id)
      done(text || "Done.")
      return true
    },
    /** Say a reply that did not come from a voice request (Ask AI, auto-answer). */
    speak(text) {
      if (!text) return
      session.transport.requestResponse?.({
        instructions: `Briefly tell the user this, in your own words, in one short sentence: ${text}`,
      })
    },
    mute(muted) { session.mute(muted) },
    setSpeakerMuted(muted) { audioElement.muted = muted },
    close() {
      closedByUs = true
      failPending("The voice session ended.")
      session.close()
    },
  }
}
