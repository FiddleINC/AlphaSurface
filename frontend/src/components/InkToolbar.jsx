// ── InkToolbar ────────────────────────────────────────────────────────────────
// Floating dock on the right edge with big touch targets for whiteboard use:
//   ✎ Pencil only — palm rejection: stylus draws, finger pans
//   ✦ Tidy        — convert handwriting/sketches into clean shapes
//   ? Ask AI      — send the selection (or the screen) to the AI
//   💡 Auto-answer — let the AI answer handwritten questions by itself
// Plus a chip that shows what the AI read from the selected ink.

import { useState } from "react"
import { useEditor, useValue } from "tldraw"
import { Hand, Lightbulb, LightbulbOff, MessageCircleQuestion, PenLine, Sparkles } from "lucide-react"

import { isUserInk } from "../ink/inkModel"
import { recognizeNow, renderShapes } from "../ink/inkRecognition"
import { setInkState, useInkState } from "../ink/inkStore"
import { tidyInk } from "../ink/inkTidy"
import { setPencilOnly } from "../ink/penInput"

const glass = {
  background: "rgba(6,6,8,0.78)",
  backdropFilter: "blur(16px)", WebkitBackdropFilter: "blur(16px)",
  border: "1px solid rgba(255,255,255,0.08)",
  boxShadow: "0 2px 14px rgba(0,0,0,0.4)",
  fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
}

function DockButton({ label, active, busy, onClick, children }) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active}
      title={label}
      onClick={onClick}
      disabled={busy}
      style={{
        width: 48, height: 48, borderRadius: 14, border: "none",
        display: "flex", alignItems: "center", justifyContent: "center",
        background: active ? "rgba(139,92,246,0.28)" : "transparent",
        color: active ? "#c4b5fd" : "rgba(255,255,255,0.82)",
        cursor: busy ? "progress" : "pointer", opacity: busy ? 0.55 : 1,
        touchAction: "manipulation", WebkitTapHighlightColor: "transparent",
        transition: "background 0.15s, color 0.15s",
      }}
    >
      {children}
    </button>
  )
}

function inkText(shape) {
  return shape?.meta?.ink?.lead ? shape.meta.ink.text || shape.meta.ink.summary : ""
}

export function InkToolbar({ sendMessage, aiConnected }) {
  const editor = useEditor()
  const ink = useInkState()
  const [toast, setToast] = useState("")

  const pencilOnly = useValue("pen mode", () => editor.getInstanceState().isPenMode, [editor])
  const selection = useValue("selection", () => editor.getSelectedShapes(), [editor])

  // What the AI read from the selected ink (lead strokes carry the text).
  const selectedRead = useValue("selected ink text", () => {
    const sel = editor.getSelectedShapes()
    const clusterIds = new Set(sel.filter(isUserInk).map(s => s.meta?.ink?.clusterId).filter(Boolean))
    if (clusterIds.size === 0) return ""
    return editor.getCurrentPageShapes()
      .filter(s => clusterIds.has(s.meta?.ink?.clusterId))
      .map(inkText)
      .filter(Boolean)
      .join(" · ")
  }, [editor])

  const flash = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(t => (t === msg ? "" : t)), 2400)
  }

  const handleTidy = async () => {
    const scope = selection.some(isUserInk) ? "selection" : "viewport"
    try {
      const n = await tidyInk(editor, scope)
      flash(n > 0 ? `Tidied into ${n} shape${n === 1 ? "" : "s"} · two-finger tap or ⌘Z to undo` : "No handwriting to tidy")
    } catch (err) {
      console.warn("[Ink] Tidy failed", err)
      flash("Tidy failed")
    }
  }

  const handleAsk = async () => {
    if (!aiConnected) { flash("AI is offline"); return }
    const shapes = selection.length > 0
      ? selection
      : editor.getCurrentPageShapes().filter(s => {
          const b = editor.getShapePageBounds(s)
          return b && editor.getViewportPageBounds().collides(b)
        })
    if (shapes.length === 0) { flash("Write or select something first"); return }

    try {
      const inkIds = shapes.filter(isUserInk).map(s => s.id)
      if (inkIds.length) await recognizeNow(editor, inkIds)
      const fresh = shapes.map(s => editor.getShape(s.id)).filter(Boolean)
      const transcript = fresh.map(inkText).filter(Boolean).join("\n")
      const rendered = await renderShapes(editor, fresh, { padding: 32, format: "png" })
      sendMessage({
        type: "ink_ask",
        payload: {
          shapeIds: fresh.map(s => s.id),
          transcript,
          question: "",
          image: rendered?.image,
          mime: rendered?.mime,
        },
      })
      flash(selection.length ? "Asked AI about the selection" : "Asked AI about the screen")
    } catch (err) {
      console.warn("[Ink] Ask failed", err)
      flash("Could not send to AI")
    }
  }

  const statusText =
    ink.status === "reading" ? "Reading ink…"
    : ink.status === "tidying" ? "Tidying…"
    : ink.status === "unavailable" || ink.status === "rate_limited" ? ink.lastError
    : toast || (selectedRead ? `Reads: ${selectedRead}` : "")

  return (
    <>
      <div
        role="toolbar"
        aria-label="Ink tools"
        style={{
          ...glass,
          position: "fixed", right: "max(10px, env(safe-area-inset-right))", top: "50%",
          transform: "translateY(-50%)", zIndex: 9998,
          display: "flex", flexDirection: "column", gap: 4, padding: 6, borderRadius: 18,
        }}
      >
        <DockButton
          label={pencilOnly ? "Pencil only: on (finger pans)" : "Pencil only: off (finger draws)"}
          active={pencilOnly}
          onClick={() => setPencilOnly(editor, !pencilOnly)}
        >
          {pencilOnly ? <PenLine size={22} /> : <Hand size={22} />}
        </DockButton>
        <DockButton label="Tidy handwriting into clean shapes" busy={ink.status === "tidying"} onClick={handleTidy}>
          <Sparkles size={22} />
        </DockButton>
        <DockButton label="Ask AI about the selection" onClick={handleAsk}>
          <MessageCircleQuestion size={22} />
        </DockButton>
        <DockButton
          label={ink.autoRespond ? "Auto-answer handwritten questions: on" : "Auto-answer handwritten questions: off"}
          active={ink.autoRespond}
          onClick={() => setInkState({ autoRespond: !ink.autoRespond })}
        >
          {ink.autoRespond ? <Lightbulb size={22} /> : <LightbulbOff size={22} />}
        </DockButton>
      </div>

      {statusText && (
        <div
          role="status"
          style={{
            ...glass,
            position: "fixed", left: "50%", transform: "translateX(-50%)",
            bottom: "calc(env(safe-area-inset-bottom) + 76px)", zIndex: 9998,
            maxWidth: "min(560px, calc(100vw - 32px))", padding: "7px 14px", borderRadius: 999,
            color: "rgba(255,255,255,0.88)", fontSize: 13, fontWeight: 500,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            pointerEvents: "none",
          }}
        >
          {statusText}
        </div>
      )}
    </>
  )
}
