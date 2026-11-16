// ── ExplainPanel ──────────────────────────────────────────────────────────────
// Shows the "Explain my board" summary: overview, key points, open questions
// and next steps, with Copy / Markdown / PDF. Opens from the dock, the main
// menu, or by voice ("explain my board").

import { useState } from "react"
import { useEditor } from "tldraw"
import { Copy, Download, FileText, Loader2, X } from "lucide-react"

import { closeExplain, explainBoard, saveMarkdown, savePdf } from "../board/explainBoard"
import { useInkState } from "../ink/inkStore"

const font = "'Inter','Segoe UI',system-ui,sans-serif"

const actionBtn = {
  display: "inline-flex", alignItems: "center", gap: 6, minHeight: 40, padding: "0 14px",
  borderRadius: 12, border: "none", cursor: "pointer", fontSize: 14, fontWeight: 600,
  background: "rgba(255,255,255,0.08)", color: "rgba(255,255,255,0.9)", touchAction: "manipulation",
}

function Section({ title, items, color }) {
  if (!items?.length) return null
  return (
    <section style={{ marginTop: 18 }}>
      <h3 style={{ margin: "0 0 6px", fontSize: 13, letterSpacing: 0.4, textTransform: "uppercase", color }}>{title}</h3>
      <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.55, fontSize: 15 }}>
        {items.map((it, i) => <li key={i} style={{ marginBottom: 4 }}>{it}</li>)}
      </ul>
    </section>
  )
}

export function ExplainPanel() {
  const editor = useEditor()
  const { explain } = useInkState()
  const [note, setNote] = useState("")

  if (!explain) return null
  const data = explain.data

  const flash = (msg) => { setNote(msg); setTimeout(() => setNote(n => (n === msg ? "" : n)), 2000) }
  const handleCopy = async () => {
    try { await navigator.clipboard.writeText(data.markdown); flash("Copied") }
    catch { flash("Copy is blocked here. Save as Markdown instead.") }
  }
  const handlePdf = async () => {
    try { await savePdf(editor, data) }
    catch (err) { console.warn("[Explain] PDF failed", err); flash("PDF export failed") }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Board summary"
      onPointerDown={(e) => { if (e.target === e.currentTarget) closeExplain() }}
      style={{
        position: "fixed", inset: 0, zIndex: 10000, background: "rgba(0,0,0,0.45)",
        display: "flex", alignItems: "center", justifyContent: "center", padding: 16, fontFamily: font,
      }}
    >
      <div style={{
        width: "min(560px, 100%)", maxHeight: "min(720px, calc(100dvh - 32px))", overflowY: "auto",
        background: "#121218", color: "#f4f4f5", borderRadius: 22, padding: "22px 22px 18px",
        border: "1px solid rgba(255,255,255,0.08)", boxShadow: "0 12px 40px rgba(0,0,0,0.5)",
      }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
          <FileText size={22} color="#c4b5fd" style={{ flexShrink: 0, marginTop: 3 }} />
          <h2 style={{ margin: 0, fontSize: 20, lineHeight: 1.3, flex: 1 }}>
            {explain.status === "done" ? data.title || "Board summary" : "Explain my board"}
          </h2>
          <button type="button" aria-label="Close" onClick={closeExplain}
            style={{ ...actionBtn, padding: 0, width: 40, justifyContent: "center", background: "transparent" }}>
            <X size={20} />
          </button>
        </div>

        {explain.status === "loading" && (
          <p style={{ display: "flex", alignItems: "center", gap: 10, color: "rgba(255,255,255,0.7)", margin: "22px 0 10px" }}>
            <Loader2 size={18} style={{ animation: "alpha-spin 1s linear infinite" }} />
            Reading your board and writing a summary…
            <style>{"@keyframes alpha-spin { to { transform: rotate(360deg) } }"}</style>
          </p>
        )}

        {explain.status === "error" && (
          <>
            <p style={{ color: "#fca5a5", margin: "18px 0 14px", lineHeight: 1.5 }}>{explain.error}</p>
            <button type="button" style={actionBtn} onClick={() => explainBoard(editor)}>Try again</button>
          </>
        )}

        {explain.status === "done" && (
          <>
            <p style={{ margin: "14px 0 0", lineHeight: 1.6, fontSize: 15, color: "rgba(255,255,255,0.88)" }}>{data.overview}</p>
            <Section title="Key points" items={data.key_points} color="#c4b5fd" />
            <Section title="Open questions" items={data.open_questions} color="#fcd34d" />
            <Section title="Next steps" items={data.next_steps} color="#67e8f9" />
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 22, alignItems: "center" }}>
              <button type="button" style={actionBtn} onClick={handleCopy}><Copy size={16} /> Copy</button>
              <button type="button" style={actionBtn} onClick={() => saveMarkdown(data)}><Download size={16} /> Markdown</button>
              <button type="button" style={actionBtn} onClick={handlePdf}><Download size={16} /> PDF</button>
              <button type="button" style={{ ...actionBtn, background: "transparent" }} onClick={() => explainBoard(editor)}>Refresh</button>
              {note && <span role="status" style={{ fontSize: 13, color: "rgba(255,255,255,0.65)" }}>{note}</span>}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
