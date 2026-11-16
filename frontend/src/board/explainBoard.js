// ── Explain my board ──────────────────────────────────────────────────────────
// Sends the current page (screenshot + the text of every shape, with the
// handwriting already transcribed) to POST /api/board/explain and keeps the
// result in the ink store, where ExplainPanel shows it. The summary can be
// copied, saved as Markdown, or saved as a PDF with the board image.

import { jsPDF } from "jspdf"
import { isUserInk } from "../ink/inkModel"
import { getInkState, setInkState } from "../ink/inkStore"

const MAX_IMAGE_SIDE = 1600

function shapeText(editor, shape) {
  try { return editor.getShapeUtil(shape).getText(shape) ?? "" } catch { return "" }
}

/** Text items for the current page, in reading order. */
export function collectBoardItems(editor) {
  const shapes = editor.getCurrentPageShapes()
    .map(s => ({ s, b: editor.getShapePageBounds(s) }))
    .filter(({ b }) => b)
    .sort((a, b) => (a.b.y - b.b.y) || (a.b.x - b.b.x))

  const items = []
  for (const { s } of shapes) {
    const by = s.meta?.addedBy && s.meta.addedBy !== "user" && s.meta.addedBy !== "demo" ? "ai" : "user"
    if (isUserInk(s)) {
      const ink = s.meta?.ink
      if (!ink?.lead) continue   // one entry per recognized cluster
      const text = ink.text || (ink.summary ? `[sketch] ${ink.summary}` : "")
      if (text) items.push({ type: "ink", text, by: "user" })
      continue
    }
    const text = shapeText(editor, s).trim()
    if (text) items.push({ type: s.type, text, by })
  }
  return items
}

async function blobToBase64(blob) {
  const dataUrl = await new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onloadend = () => resolve(r.result)
    r.onerror = reject
    r.readAsDataURL(blob)
  })
  return String(dataUrl).split(",")[1]
}

async function renderPage(editor, format = "jpeg") {
  const ids = [...editor.getCurrentPageShapeIds()]
  if (ids.length === 0) return null
  const bounds = editor.getCurrentPageBounds()
  const scale = bounds ? Math.min(2, MAX_IMAGE_SIDE / Math.max(bounds.w, bounds.h, 1)) : 1
  const { blob, width, height } = await editor.toImage(ids, {
    format, quality: 0.8, background: true, padding: 32, scale, pixelRatio: 1, darkMode: false,
  })
  return { blob, width, height }
}

/** Run the summary for the current page. Results land in inkStore.explain. */
export async function explainBoard(editor) {
  if (getInkState().explain?.status === "loading") return getInkState().explain
  setInkState({ explain: { status: "loading" } })
  try {
    const items = collectBoardItems(editor)
    const rendered = await renderPage(editor)
    if (!rendered && items.length === 0) throw new Error("The board is empty. Write something first.")

    const res = await fetch("/api/board/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image: rendered ? await blobToBase64(rendered.blob) : "",
        mime: "image/jpeg",
        items,
        pageName: editor.getCurrentPage().name,
      }),
    })
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}))
      throw new Error(detail.detail || `Summary failed (${res.status})`)
    }
    const explain = { status: "done", data: await res.json() }
    setInkState({ explain })
    return explain
  } catch (err) {
    const explain = { status: "error", error: err instanceof Error ? err.message : "Summary failed" }
    setInkState({ explain })
    return explain
  }
}

export function closeExplain() {
  setInkState({ explain: null })
}

function fileSlug(title) {
  return (title || "board-summary").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "board-summary"
}

function download(blob, name) {
  const url = URL.createObjectURL(blob)
  Object.assign(document.createElement("a"), { href: url, download: name }).click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function saveMarkdown(data) {
  download(new Blob([data.markdown], { type: "text/markdown" }), `${fileSlug(data.title)}.md`)
}

/** A4 PDF: the written summary first, then the board image. */
export async function savePdf(editor, data) {
  const pdf = new jsPDF({ unit: "pt", format: "a4" })
  const pageW = pdf.internal.pageSize.getWidth()
  const pageH = pdf.internal.pageSize.getHeight()
  const margin = 48
  const width = pageW - margin * 2
  let y = margin

  const ensure = (h) => {
    if (y + h > pageH - margin) { pdf.addPage(); y = margin }
  }
  const paragraph = (text, size, { bold = false, color = [30, 30, 30], gap = 6, indent = 0 } = {}) => {
    pdf.setFont("helvetica", bold ? "bold" : "normal")
    pdf.setFontSize(size)
    pdf.setTextColor(...color)
    const lines = pdf.splitTextToSize(text, width - indent)
    const lh = size * 1.35
    for (const line of lines) {
      ensure(lh)
      pdf.text(line, margin + indent, y + size)
      y += lh
    }
    y += gap
  }

  paragraph(data.title || "Board summary", 20, { bold: true, gap: 4 })
  paragraph(`${editor.getCurrentPage().name} · ${new Date().toLocaleDateString()}`, 10, { color: [120, 120, 120], gap: 14 })
  paragraph(data.overview || "", 12, { gap: 14 })
  for (const [heading, list] of [
    ["Key points", data.key_points], ["Open questions", data.open_questions], ["Next steps", data.next_steps],
  ]) {
    if (!list?.length) continue
    paragraph(heading, 14, { bold: true, gap: 4 })
    for (const item of list) paragraph(`•  ${item}`, 11, { indent: 8, gap: 3 })
    y += 10
  }

  const rendered = await renderPage(editor, "png")
  if (rendered) {
    const dataUrl = `data:image/png;base64,${await blobToBase64(rendered.blob)}`
    pdf.addPage()
    const usableH = pageH - margin * 2
    const scale = Math.min(width / rendered.width, usableH / rendered.height)
    pdf.addImage(dataUrl, "PNG", margin, margin, rendered.width * scale, rendered.height * scale, undefined, "FAST")
  }
  pdf.save(`${fileSlug(data.title)}.pdf`)
}
