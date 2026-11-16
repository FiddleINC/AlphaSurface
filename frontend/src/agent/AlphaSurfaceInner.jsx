// ── AlphaSurfaceInner ─────────────────────────────────────────────────────────
// Mounts inside <Tldraw>. Owns:
//   - WebSocket to the backend (+ reconnect): canvas actions in, board state out
//   - Pencil/finger input and handwriting recognition
//   - Board snapshot (every 3s + on shape change) and screenshot for Claude
//   - Realtime voice session (OpenAI) that hands board requests to Claude
//   - Status pill, ink toolbar, captions
//   - Assistant mode sync, first-run examples, "Explain my board" panel

import { useEffect, useRef, useState } from "react"
import { useEditor } from "tldraw"
import { explainBoard } from "../board/explainBoard"
import { handleCanvasMessage } from "../canvas/canvasActions"
import { sendCanvasSnapshot } from "../canvas/canvasSnapshot"
import { ExplainPanel } from "../components/ExplainPanel"
import { InkToolbar } from "../components/InkToolbar"
import { StatusPill } from "../components/StatusPill"
import { WelcomeCard } from "../components/WelcomeCard"
import { startInkRecognition } from "../ink/inkRecognition"
import { getInkState, setInkState, useInkState } from "../ink/inkStore"
import { startPenInput } from "../ink/penInput"
import { startRealtimeVoice } from "../voice/realtimeVoice"

const caption = (text) => text && setInkState({ caption: text, captionAt: Date.now() })

export function AlphaSurfaceInner({ config }) {
  const editor = useEditor()
  const [ws, setWs] = useState(null)
  const [indicator, setIndicator] = useState(false)
  const [aiStatus, setAiStatus] = useState("disconnected")   // from the backend (Claude)
  const [voiceState, setVoiceState] = useState(config.voiceEnabled ? "connecting" : "off") // Realtime session
  const [muted, setMuted] = useState(false)
  const [speakerMuted, setSpeakerMuted] = useState(false)

  const wsRef = useRef(null)
  const voiceRef = useRef(null)
  const prevShapeCount = useRef(0)
  const { mode } = useInkState()

  const sendMessage = (msg) => {
    const socket = wsRef.current
    if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(msg))
  }

  // ── WebSocket connection ──────────────────────────────────────────────────
  useEffect(() => {
    if (!editor) return
    let socket, retryDelay = 1000, retryTimeout, disposed = false

    function connect() {
      if (disposed) return
      socket = new WebSocket("/ws")
      wsRef.current = socket

      socket.onopen = () => {
        retryDelay = 1000
        setWs(socket)
        socket.send(JSON.stringify({ type: "set_mode", payload: { mode: getInkState().mode } }))
      }

      socket.onmessage = (event) => {
        if (disposed) return
        let message
        try { message = JSON.parse(event.data) }
        catch { return }
        const p = message.payload ?? {}

        switch (message.type) {
          case "ai_status":
            setAiStatus(p.status ?? "idle")
            caption(p.detail)
            return
          case "voice_result":
            voiceRef.current?.resolve(p.id, p.text)
            return
          case "ai_reply":
            caption(p.text)
            // Replies to voice requests are spoken by the voice tool call itself;
            // speak the others (Ask AI, auto-answer) if voice is on.
            if (p.source !== "voice") voiceRef.current?.speak(p.text)
            return
          case "config_ack":
          case "canvas_snapshot":
            return
          default:
            setIndicator(true)
            setTimeout(() => setIndicator(false), 1200)
            handleCanvasMessage(editor, message)
        }
      }

      socket.onclose = () => {
        if (disposed) return
        setWs(null); wsRef.current = null; setAiStatus("disconnected")
        retryTimeout = setTimeout(() => {
          retryDelay = Math.min(retryDelay * 2, 30000)
          connect()
        }, retryDelay)
      }
    }

    connect()
    return () => { disposed = true; clearTimeout(retryTimeout); socket?.close() }
  }, [editor])

  // ── Assistant mode → backend ────────────────────────────────────────────
  useEffect(() => {
    sendMessage({ type: "set_mode", payload: { mode } })
  }, [mode])

  // ── First run: offer examples on an empty board ──────────────────────────
  useEffect(() => {
    if (!editor || getInkState().welcomed) return
    // tldraw has loaded the persisted board by the time the editor mounts.
    if (editor.getCurrentPageShapeIds().size === 0) setInkState({ welcomeOpen: true })
    else setInkState({ welcomed: true })
  }, [editor])

  // ── Pencil / finger input + handwriting recognition ───────────────────────
  useEffect(() => {
    if (!editor) return
    if (import.meta.env.DEV) window.__alphaEditor = editor // debugging / e2e hook
    const stopPen = startPenInput(editor)
    const stopInk = startInkRecognition(editor)
    return () => { stopPen(); stopInk() }
  }, [editor])

  // ── Realtime voice ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!config.voiceEnabled) return
    let disposed = false
    startRealtimeVoice({
      send: sendMessage,
      explain: async () => {
        const res = await explainBoard(editor)
        return res.status === "done"
          ? `${res.data.overview} The full summary is on screen.`
          : res.error || "I couldn't summarize the board."
      },
      onState: setVoiceState,
      onDisconnect: (reason) => { voiceRef.current = null; caption(reason) },
    })
      .then((voice) => {
        if (disposed) { voice.close(); return }
        voiceRef.current = voice
        setVoiceState("idle")
      })
      .catch((err) => {
        console.warn("[Voice]", err)
        setVoiceState("off")
        caption(`Voice unavailable: ${err.message}`)
      })
    return () => {
      disposed = true
      voiceRef.current?.close()
      voiceRef.current = null
    }
  }, [config.voiceEnabled, editor])

  // ── Board snapshot → backend ──────────────────────────────────────────────
  useEffect(() => {
    if (!ws || !editor) return
    const doSnapshot = () => sendCanvasSnapshot(editor, ws)
    const interval = setInterval(doSnapshot, 3000)
    let debounce
    const unsub = editor.store.listen(() => {
      const count = editor.getCurrentPageShapeIds().size
      if (count !== prevShapeCount.current) {
        prevShapeCount.current = count
        clearTimeout(debounce)
        debounce = setTimeout(doSnapshot, 400)
      }
    }, { scope: "document" })
    return () => { clearInterval(interval); clearTimeout(debounce); unsub() }
  }, [ws, editor])

  // ── Board screenshot → Claude vision ──────────────────────────────────────
  useEffect(() => {
    if (!ws || !editor) return

    const captureAndSend = async () => {
      if (ws.readyState !== WebSocket.OPEN) return
      const shapeIds = [...editor.getCurrentPageShapeIds()]
      if (shapeIds.length === 0) return
      try {
        const { blob } = await editor.toImage(shapeIds, { format: "jpeg", quality: 0.65, background: true, padding: 32 })
        const reader = new FileReader()
        reader.onloadend = () => {
          if (ws.readyState !== WebSocket.OPEN) return
          ws.send(JSON.stringify({
            type: "canvas_image",
            payload: { data: reader.result.split(",")[1], mime: "image/jpeg" },
          }))
        }
        reader.readAsDataURL(blob)
      } catch (err) {
        console.warn("[AlphaSurface] Canvas capture failed", err)
      }
    }

    const interval = setInterval(captureAndSend, 8000)
    let debounce
    const unsub = editor.store.listen(() => {
      clearTimeout(debounce)
      debounce = setTimeout(captureAndSend, 1000)
    }, { scope: "document" })
    return () => { clearInterval(interval); clearTimeout(debounce); unsub() }
  }, [ws, editor])

  // ── Mic / speaker toggles ─────────────────────────────────────────────────
  const handleToggleMute = () => {
    const next = !muted
    setMuted(next)
    voiceRef.current?.mute(next)
  }
  const handleToggleSpeaker = () => {
    const next = !speakerMuted
    setSpeakerMuted(next)
    voiceRef.current?.setSpeakerMuted(next)
  }

  // Claude working beats voice state; otherwise show what the voice is doing.
  const status = aiStatus === "disconnected" || aiStatus === "thinking"
    ? aiStatus
    : (voiceState === "speaking" || voiceState === "thinking" ? voiceState : aiStatus)

  return (
    <>
      {indicator && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, height: 3, zIndex: 9999,
          background: "linear-gradient(90deg, #8b5cf6, #06b6d4)",
        }} />
      )}

      <InkToolbar sendMessage={sendMessage} aiConnected={aiStatus !== "disconnected"} />
      <WelcomeCard
        sendMessage={sendMessage}
        syncBoard={() => sendCanvasSnapshot(editor, wsRef.current)}
        aiConnected={aiStatus !== "disconnected"}
      />
      <ExplainPanel />

      <StatusPill
        aiStatus={status}
        listening={voiceState === "listening"}
        voiceOn={voiceState !== "off" && voiceState !== "connecting"}
        muted={muted}
        speakerMuted={speakerMuted}
        onToggleMute={handleToggleMute}
        onToggleSpeaker={handleToggleSpeaker}
      />
    </>
  )
}
