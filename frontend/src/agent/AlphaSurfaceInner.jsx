// ── AlphaSurfaceInner ─────────────────────────────────────────────────────────
// Mounts inside <Tldraw>. Owns:
//   - WebSocket connection + reconnect
//   - Microphone capture + VAD
//   - Three-tier canvas snapshot (every 3s + on shape change)
//   - Canvas image capture (every 12s + on shape change)
//   - AI status + indicator stripe
//   - Status pill UI

import { useEffect, useRef, useState } from "react"
import { useEditor } from "tldraw"
import {
  activatePlaybackContext,
  getPlaybackContext,
  flushAudioPlayback,
  setPlaybackEnabled,
  playAudioChunk,
} from "../audio/AudioPlayback"
import { handleCanvasMessage } from "../canvas/canvasActions"
import { sendCanvasSnapshot } from "../canvas/canvasSnapshot"
import { StatusPill } from "../components/StatusPill"
import { InkToolbar } from "../components/InkToolbar"
import { startInkRecognition } from "../ink/inkRecognition"
import { startPenInput } from "../ink/penInput"
import { setInkState } from "../ink/inkStore"


export function AlphaSurfaceInner({ config }) {
  const editor = useEditor()
  const [ws, setWs] = useState(null)
  const [indicator, setIndicator] = useState(false)
  const [aiStatus, setAiStatus] = useState("disconnected")
  const [muted, setMuted] = useState(false)
  const [speakerMuted, setSpeakerMuted] = useState(false)
  const [listening, setListening] = useState(false)

  const wsRef = useRef(null)
  const prevShapeCount = useRef(0)
  const mutedRef = useRef(false)
  const lastInterruptAtRef = useRef(0)
  const listeningRef = useRef(false)
  const listeningTimeoutRef = useRef(null)
  const configRef = useRef(config)

  useEffect(() => { configRef.current = config }, [config])
  useEffect(() => { listeningRef.current = listening }, [listening])

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
        setAiStatus("idle")
        socket.send(JSON.stringify({
          type: "set_config",
          payload: { voiceEnabled: configRef.current.voiceEnabled },
        }))
      }

      socket.onmessage = (event) => {
        if (disposed) return
        let message
        try { message = JSON.parse(event.data) }
        catch { console.warn("[AlphaSurface] Dropped malformed WS message"); return }

        if (message.type === "ai_status") {
          const { status = "idle", detail } = message.payload ?? {}
          setAiStatus(status === "listening" ? "idle" : status)
          if (status === "listening") { listeningRef.current = true; setListening(true) }
          if (detail) setInkState({ caption: detail, captionAt: Date.now() })
          return
        }

        // Captions: what the AI heard, and what it answered.
        if (message.type === "user_transcript") {
          setInkState({ caption: `You: ${message.payload?.text ?? ""}`, captionAt: Date.now() })
          return
        }
        if (message.type === "ai_reply") {
          setInkState({ caption: message.payload?.text ?? "", captionAt: Date.now() })
          return
        }

        if (message.type === "ai_interrupted") {
          const now = Date.now()
          if (now - lastInterruptAtRef.current > 250) {
            lastInterruptAtRef.current = now
            flushAudioPlayback()
            setAiStatus("idle")
          }
          return
        }

        // Show indicator stripe for any canvas action
        if (message.type !== "canvas_snapshot" && message.type !== "config_ack") {
          setIndicator(true)
          setTimeout(() => setIndicator(false), 1200)
        }

        handleCanvasMessage(editor, message, {
          onAudio: (data) => {
            playAudioChunk(data)
            setAiStatus("speaking")
          },
          onInterrupt: () => {
            flushAudioPlayback()
            setAiStatus("idle")
          },
        })
      }

      socket.onerror = () => {}
      socket.onclose = () => {
        if (disposed) return
        setListening(false)
        if (listeningTimeoutRef.current) {
          clearTimeout(listeningTimeoutRef.current)
          listeningTimeoutRef.current = null
        }
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

  // ── Pencil / finger input + handwriting recognition ───────────────────────
  useEffect(() => {
    if (!editor) return
    if (import.meta.env.DEV) window.__alphaEditor = editor // debugging / e2e hook
    const stopPen = startPenInput(editor)
    const stopInk = startInkRecognition(editor)
    return () => { stopPen(); stopInk() }
  }, [editor])

  const sendMessage = (msg) => {
    const socket = wsRef.current
    if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(msg))
  }

  // ── Three-tier canvas snapshot → backend ──────────────────────────────────
  // Replaces the old flat shape list with BlurryShapes / FocusedShapes / PeripheralClusters
  useEffect(() => {
    if (!ws || !editor) return

    const doSnapshot = () => sendCanvasSnapshot(editor, ws)

    // Periodic snapshot every 3s
    const interval = setInterval(doSnapshot, 3000)

    // Immediate snapshot when shape count changes
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

  // ── Canvas image → Claude vision ──────────────────────────────────────────
  useEffect(() => {
    if (!ws || !editor) return

    const captureAndSend = async () => {
      if (ws.readyState !== WebSocket.OPEN) return
      const shapeIds = [...editor.getCurrentPageShapeIds()]
      if (shapeIds.length === 0) return
      await new Promise(r => setTimeout(r, 600))
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

    const interval = setInterval(captureAndSend, 8000)  // 12s → 8s for baseline

    let debounce
    const unsub = editor.store.listen(() => {
      clearTimeout(debounce)
      debounce = setTimeout(captureAndSend, 800)           // 4s → 0.8s on shape change
    }, { scope: "document" })

    return () => { clearInterval(interval); clearTimeout(debounce); unsub() }
  }, [ws, editor])

  // ── Microphone → backend ──────────────────────────────────────────────────
  useEffect(() => {
    if (!ws || !config.voiceEnabled) return
    let audioContext, processor, source, stream

    async function startMic() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, sampleRate: 16000, channelCount: 1 },
          video: false,
        })
        audioContext = new AudioContext({ sampleRate: 16000 })
        source = audioContext.createMediaStreamSource(stream)
        processor = audioContext.createScriptProcessor(4096, 1, 1)

        processor.onaudioprocess = (e) => {
          const currentWs = wsRef.current
          if (!currentWs || currentWs.readyState !== WebSocket.OPEN) return
          if (mutedRef.current) return
          const input = e.inputBuffer.getChannelData(0)

          // Voice activity detection for status UI
          let sumSquares = 0
          for (let i = 0; i < input.length; i++) sumSquares += input[i] * input[i]
          const rms = Math.sqrt(sumSquares / input.length)
          if (rms > 0.015) {
            if (!listeningRef.current) { listeningRef.current = true; setListening(true) }
            if (listeningTimeoutRef.current) clearTimeout(listeningTimeoutRef.current)
            listeningTimeoutRef.current = setTimeout(() => {
              listeningRef.current = false; setListening(false)
            }, 700)
          }

          const pcm16 = new Int16Array(input.length)
          for (let i = 0; i < input.length; i++) {
            pcm16[i] = Math.max(-32768, Math.min(32767, input[i] * 32768))
          }
          const b64 = btoa(String.fromCharCode(...new Uint8Array(pcm16.buffer)))
          currentWs.send(JSON.stringify({ type: "audio_chunk", payload: { data: b64 } }))
        }

        source.connect(processor)
        const silentSink = audioContext.createGain()
        silentSink.gain.value = 0
        processor.connect(silentSink)
        silentSink.connect(audioContext.destination)
      } catch (err) {
        console.warn("[AlphaSurface] Mic error:", err.message)
      }
    }

    startMic()
    return () => {
      if (listeningTimeoutRef.current) { clearTimeout(listeningTimeoutRef.current); listeningTimeoutRef.current = null }
      listeningRef.current = false; setListening(false)
      processor?.disconnect(); source?.disconnect()
      stream?.getTracks().forEach(t => t.stop()); audioContext?.close()
    }
  }, [ws, config.voiceEnabled])

  // ── Playback enabled sync ─────────────────────────────────────────────────
  useEffect(() => { setPlaybackEnabled(config.voiceEnabled) }, [config.voiceEnabled])

  // ── Unlock audio context on first gesture ─────────────────────────────────
  useEffect(() => {
    if (!config.voiceEnabled || getPlaybackContext()) return
    const unlock = () => {
      activatePlaybackContext()
      window.removeEventListener("pointerdown", unlock)
      window.removeEventListener("keydown", unlock)
      window.removeEventListener("touchstart", unlock)
    }
    window.addEventListener("pointerdown", unlock, { passive: true })
    window.addEventListener("keydown", unlock)
    window.addEventListener("touchstart", unlock, { passive: true })
    return () => {
      window.removeEventListener("pointerdown", unlock)
      window.removeEventListener("keydown", unlock)
      window.removeEventListener("touchstart", unlock)
    }
  }, [config.voiceEnabled])


  // ── Mute toggle ───────────────────────────────────────────────────────────
  const handleToggleMute = () => {
    const next = !muted
    setMuted(next)
    mutedRef.current = next
    if (next) {
      listeningRef.current = false; setListening(false)
      if (listeningTimeoutRef.current) { clearTimeout(listeningTimeoutRef.current); listeningTimeoutRef.current = null }
    }
    sendMessage({ type: "set_audio", payload: { muted: next } })
    // Mic mute does not affect speaker
    if (!next) activatePlaybackContext()
    if (next) flushAudioPlayback()
  }

  // ── Speaker mute toggle ─────────────────────────────────────────────────--
  const handleToggleSpeaker = () => {
    const next = !speakerMuted
    setSpeakerMuted(next)
    setPlaybackEnabled(!next)
    sendMessage({ type: "set_speaker", payload: { muted: next } })
    if (!next) activatePlaybackContext()
    if (next) flushAudioPlayback()
  }

  return (
    <>
      {/* Edge indicator stripe — shows before AI acts on canvas */}
      {indicator && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, height: 3, zIndex: 9999,
          background: "linear-gradient(90deg, #8b5cf6, #06b6d4)",
        }} />
      )}

      <InkToolbar sendMessage={sendMessage} aiConnected={aiStatus !== "disconnected"} />

      <StatusPill
        aiStatus={aiStatus}
        listening={listening}
        muted={muted}
        speakerMuted={speakerMuted}
        config={config}
        onToggleMute={handleToggleMute}
        onToggleSpeaker={handleToggleSpeaker}
      />
    </>
  )
}
