// ── WelcomeCard ───────────────────────────────────────────────────────────────
// First-run examples on an empty board. Tapping an example writes it on the
// board and lets the AI respond in the current mode, so the first minute shows
// what the product does instead of a blank canvas. Reopen it from the main
// menu ("Show examples").

import { createShapeId, toRichText, useEditor } from "tldraw"
import { Calculator, CircleHelp, ClipboardCheck, PenLine } from "lucide-react"

import { askAboutShapes } from "../ink/askAi"
import { setInkState, useInkState } from "../ink/inkStore"
import { MODE_INFO, MODE_ORDER } from "./modeInfo"

const font = "'Inter','Segoe UI',system-ui,sans-serif"

const EXAMPLES = [
  {
    id: "solve", Icon: Calculator, title: "Solve a problem", text: "12 × 8 =",
    hint: "The AI answers next to it, or hints in Tutor mode.",
    question: "",
  },
  {
    id: "check", Icon: ClipboardCheck, title: "Check my work", text: "3x + 5 = 20\nx = 4",
    hint: "There's a mistake. Watch the AI mark it.",
    question: "Check this work.",
  },
  {
    id: "ask", Icon: CircleHelp, title: "Ask a question", text: "Why is the sky blue?",
    hint: "Get a short handwritten answer.",
    question: "",
  },
]

function placeExample(editor, example) {
  const vp = editor.getViewportPageBounds()
  // Left of centre, leaving room for the AI's reply on the right.
  const id = createShapeId()
  editor.createShape({
    id, type: "text",
    x: vp.x + vp.w * 0.22, y: vp.y + vp.h * 0.32,
    props: { richText: toRichText(example.text), font: "draw", size: "xl", color: "black" },
    meta: { addedBy: "demo", semanticRole: "example" },
  })
  return editor.getShape(id)
}

function close(caption = "") {
  setInkState({
    welcomeOpen: false, welcomed: true,
    ...(caption ? { caption, captionAt: Date.now() } : {}),
  })
}

export function WelcomeCard({ sendMessage, syncBoard, aiConnected }) {
  const editor = useEditor()
  const { welcomeOpen, mode } = useInkState()
  if (!welcomeOpen) return null

  const runExample = async (example) => {
    const shape = placeExample(editor, example)
    close(aiConnected
      ? `${example.hint} Then write your own with your pencil and pause.`
      : "The AI is offline, so it can't answer yet. Check that the backend is running.")
    if (!aiConnected || !shape) return
    syncBoard()  // make sure the agent's board summary includes the example
    await new Promise(r => setTimeout(r, 300))
    try { await askAboutShapes(editor, [shape], sendMessage, example.question) }
    catch (err) { console.warn("[Welcome] Example failed", err) }
  }

  const info = MODE_INFO[mode]

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 10000, display: "flex", alignItems: "center",
      justifyContent: "center", padding: 16, background: "rgba(0,0,0,0.35)", fontFamily: font,
    }}>
      <div role="dialog" aria-label="Try an example" style={{
        width: "min(460px, 100%)", maxHeight: "calc(100dvh - 32px)", overflowY: "auto",
        background: "#121218", color: "#f4f4f5", borderRadius: 22, padding: "22px 20px 16px",
        border: "1px solid rgba(255,255,255,0.08)", boxShadow: "0 12px 40px rgba(0,0,0,0.5)",
      }}>
        <h2 style={{ margin: 0, fontSize: 20 }}>Try one</h2>
        <p style={{ margin: "6px 0 14px", color: "rgba(255,255,255,0.62)", fontSize: 14, lineHeight: 1.5 }}>
          Tap an example to see the AI respond on the board. Or just start writing.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {EXAMPLES.map(ex => (
            <button key={ex.id} type="button" onClick={() => runExample(ex)} style={{
              display: "flex", alignItems: "center", gap: 14, textAlign: "left", padding: "12px 14px",
              minHeight: 64, borderRadius: 16, border: "1px solid rgba(255,255,255,0.08)",
              background: "rgba(255,255,255,0.04)", color: "inherit", cursor: "pointer",
              fontFamily: font, touchAction: "manipulation",
            }}>
              <ex.Icon size={24} color="#c4b5fd" style={{ flexShrink: 0 }} />
              <span style={{ flex: 1 }}>
                <span style={{ display: "block", fontWeight: 600, fontSize: 15 }}>{ex.title}</span>
                <span style={{ display: "block", fontSize: 13, color: "rgba(255,255,255,0.6)", marginTop: 2 }}>
                  “{ex.text.replace("\n", ", ")}”
                </span>
              </span>
            </button>
          ))}
        </div>

        <div style={{ marginTop: 16, fontSize: 13, color: "rgba(255,255,255,0.62)" }}>
          <div style={{ marginBottom: 8 }}>
            How should the AI help? You can change this anytime from the dock.
          </div>
          <div role="radiogroup" aria-label="AI mode" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {MODE_ORDER.map(m => {
              const { label, Icon } = MODE_INFO[m]
              const on = m === mode
              return (
                <button key={m} type="button" role="radio" aria-checked={on}
                  onClick={() => setInkState({ mode: m })}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 6, minHeight: 36, padding: "0 12px",
                    borderRadius: 999, border: "none", cursor: "pointer", fontSize: 13, fontWeight: 600,
                    background: on ? "rgba(139,92,246,0.3)" : "rgba(255,255,255,0.06)",
                    color: on ? "#ddd6fe" : "rgba(255,255,255,0.8)", touchAction: "manipulation",
                  }}>
                  <Icon size={15} /> {label}
                </button>
              )
            })}
          </div>
          <div style={{ marginTop: 8 }}>{info.blurb}</div>
        </div>

        <button type="button" onClick={() => close()} style={{
          display: "flex", alignItems: "center", justifyContent: "center", gap: 8, width: "100%",
          minHeight: 48, marginTop: 16, borderRadius: 14, border: "none", cursor: "pointer",
          fontSize: 15, fontWeight: 600, background: "rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.9)",
          touchAction: "manipulation",
        }}>
          <PenLine size={18} /> Start with a blank board
        </button>
      </div>
    </div>
  )
}
