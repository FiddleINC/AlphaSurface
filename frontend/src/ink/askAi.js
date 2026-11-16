// ── Ask AI about shapes ───────────────────────────────────────────────────────
// Shared by the dock's "?" button and the first-run examples: make sure the
// ink is read, render the shapes, and hand them to the canvas agent.

import { isUserInk } from "./inkModel"
import { recognizeNow, renderShapes } from "./inkRecognition"

function shapeText(editor, shape) {
  if (isUserInk(shape)) {
    const ink = shape.meta?.ink
    return ink?.lead ? ink.text || ink.summary || "" : ""
  }
  try { return editor.getShapeUtil(shape).getText(shape) ?? "" } catch { return "" }
}

/**
 * @param {object} editor tldraw editor
 * @param {object[]} shapes shapes to ask about
 * @param {(msg: object) => void} sendMessage WebSocket sender
 * @param {string} [question] optional explicit request
 */
export async function askAboutShapes(editor, shapes, sendMessage, question = "") {
  const inkIds = shapes.filter(isUserInk).map(s => s.id)
  if (inkIds.length) await recognizeNow(editor, inkIds)
  const fresh = shapes.map(s => editor.getShape(s.id)).filter(Boolean)
  const transcript = fresh.map(s => shapeText(editor, s)).filter(Boolean).join("\n")
  const rendered = await renderShapes(editor, fresh, { padding: 32, format: "png" })
  sendMessage({
    type: "ink_ask",
    payload: {
      shapeIds: fresh.map(s => s.id),
      transcript,
      question,
      image: rendered?.image,
      mime: rendered?.mime,
    },
  })
}
