// ── InkToolbar ────────────────────────────────────────────────────────────────
// Floating dock on the right edge with big touch targets for whiteboard use:
//   ✎ Pencil only — palm rejection: stylus draws, finger pans
//   ✦ Tidy        — convert handwriting/sketches into clean shapes
//   ? Ask AI      — send the selection (or the screen) to the AI
//   Mode        — Tutor / Checker / Collaborator / Quiet (how proactive the AI is)
//   Explain     — written summary of the board (copy, Markdown, PDF)
// Plus a chip that shows what the AI read from the selected ink.

import { useEffect, useState } from "react"
import { useEditor, useValue } from "tldraw"
import { FileText, Hand, MessageCircleQuestion, PenLine, Sparkles } from "lucide-react"

import { explainBoard } from "../board/explainBoard"
import { askAboutShapes } from "../ink/askAi"
import { isUserInk } from "../ink/inkModel"
import { getInkState, setInkState, useInkState } from "../ink/inkStore"
import { tidyInk } from "../ink/inkTidy"
import { setPencilOnly } from "../ink/penInput"
import { MODE_INFO, MODE_ORDER } from "./modeInfo"

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
  const [modeMenu, setModeMenu] = useState(false)

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

  // Captions (what you said / what the AI answered) fade after a few seconds.
  useEffect(() => {
    if (!ink.caption) return
    const at = ink.captionAt
    const t = setTimeout(() => {
      if (getInkState().captionAt === at) setInkState({ caption: "" })
    }, 7000)
    return () => clearTimeout(t)
  }, [ink.caption, ink.captionAt])

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
      await askAboutShapes(editor, shapes, sendMessage)
      flash(selection.length ? "Asked AI about the selection" : "Asked AI about the screen")
    } catch (err) {
      console.warn("[Ink] Ask failed", err)
      flash("Could not send to AI")
    }
  }

  const chooseMode = (m) => {
    setModeMenu(false)
    setInkState({ mode: m })
    flash(`${MODE_INFO[m].label}: ${MODE_INFO[m].blurb}`)
  }

  const handleExplain = () => {
    if (!aiConnected) { flash("AI is offline"); return }
    if (editor.getCurrentPageShapeIds().size === 0) { flash("Write something first"); return }
    explainBoard(editor)
  }

  const current = MODE_INFO[ink.mode] ?? MODE_INFO.collab

  const statusText =
    ink.status === "reading" ? "Reading ink…"
    : ink.status === "tidying" ? "Tidying…"
    : ink.status === "unavailable" || ink.status === "rate_limited" ? ink.lastError
    : toast || ink.caption || (selectedRead ? `Reads: ${selectedRead}` : "")

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
        <DockButton label="Explain my board: written summary" busy={ink.explain?.status === "loading"} onClick={handleExplain}>
          <FileText size={22} />
        </DockButton>
        <div style={{ height: 1, margin: "2px 8px", background: "rgba(255,255,255,0.1)" }} />
        <DockButton
          label={`AI mode: ${current.label}. Tap to change`}
          active={ink.mode !== "quiet"}
          onClick={() => setModeMenu(v => !v)}
        >
          <current.Icon size={22} />
        </DockButton>
      </div>

      {modeMenu && (
        <>
          <div onPointerDown={() => setModeMenu(false)} style={{ position: "fixed", inset: 0, zIndex: 9998 }} />
          <div
            role="menu"
            aria-label="AI mode"
            style={{
              ...glass, position: "fixed", zIndex: 9999, borderRadius: 18, padding: 6,
              right: "calc(max(10px, env(safe-area-inset-right)) + 70px)", top: "50%",
              transform: "translateY(-10%)", width: "min(300px, calc(100vw - 100px))",
            }}
          >
            {MODE_ORDER.map(m => {
              const { label, Icon, blurb } = MODE_INFO[m]
              const on = m === ink.mode
              return (
                <button
                  key={m} type="button" role="menuitemradio" aria-checked={on}
                  onClick={() => chooseMode(m)}
                  style={{
                    display: "flex", gap: 12, alignItems: "flex-start", width: "100%", textAlign: "left",
                    padding: "10px 12px", minHeight: 56, borderRadius: 12, border: "none", cursor: "pointer",
                    background: on ? "rgba(139,92,246,0.28)" : "transparent",
                    color: on ? "#ddd6fe" : "rgba(255,255,255,0.88)", fontFamily: glass.fontFamily,
                    touchAction: "manipulation",
                  }}
                >
                  <Icon size={20} style={{ flexShrink: 0, marginTop: 1 }} />
                  <span>
                    <span style={{ display: "block", fontWeight: 600, fontSize: 14 }}>{label}</span>
                    <span style={{ display: "block", fontSize: 12, lineHeight: 1.4, opacity: 0.7, marginTop: 2 }}>{blurb}</span>
                  </span>
                </button>
              )
            })}
          </div>
        </>
      )}

      {statusText && (
        <div
          role="status"
          style={{
            ...glass,
            position: "fixed", left: "50%", transform: "translateX(-50%)",
            bottom: "calc(env(safe-area-inset-bottom) + 76px)", zIndex: 9998,
            maxWidth: "min(560px, calc(100vw - 32px))", padding: "8px 16px", borderRadius: 18,
            color: "rgba(255,255,255,0.88)", fontSize: 13, fontWeight: 500,
            overflow: "hidden", lineHeight: 1.4, textAlign: "center",
            display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical",
            pointerEvents: "none",
          }}
        >
          {statusText}
        </div>
      )}
    </>
  )
}
