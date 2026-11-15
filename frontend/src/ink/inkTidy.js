// ── Tidy ink ──────────────────────────────────────────────────────────────────
// Converts recognized handwriting/sketches into clean tldraw shapes:
//   text / math → typed text (same size and position as the handwriting)
//   shape       → geo shape with the handwritten label inside
//   arrow/line  → straight arrow, bound to tidied shapes it touches
//   doodle      → left as ink
// One undo step restores the original strokes.

import { Box, createShapeId, toRichText } from "tldraw"
import { dominantColor, getBounds, getRecognizedClusters, getUserInk, isUserInk } from "./inkModel"
import { recognizeNow } from "./inkRecognition"
import { setInkState } from "./inkStore"

const TEXT_LINE_PX = 32   // rendered line height of size "m" text at scale 1
const BIND_SLOP = 36      // how close an arrow end must be to a shape to bind

function strokesInScope(editor, scope) {
  if (scope === "selection") {
    const selected = editor.getSelectedShapes()
    // Expand groups / frames to their ink children.
    const ids = new Set()
    for (const s of selected) {
      if (isUserInk(s)) ids.add(s.id)
      for (const childId of editor.getSortedChildIdsForParent(s.id)) {
        const child = editor.getShape(childId)
        if (isUserInk(child)) ids.add(child.id)
      }
    }
    return getUserInk(editor).filter(s => ids.has(s.id))
  }
  const viewport = editor.getViewportPageBounds()
  return getUserInk(editor).filter(s => {
    const b = editor.getShapePageBounds(s)
    return b && viewport.collides(b)
  })
}

/** Fraction of `stroke`'s area that lies inside `box`. */
function overlapRatio(stroke, box) {
  const x1 = Math.max(stroke.minX, box.minX), y1 = Math.max(stroke.minY, box.minY)
  const x2 = Math.min(stroke.maxX, box.maxX), y2 = Math.min(stroke.maxY, box.maxY)
  if (x2 <= x1 || y2 <= y1) return 0
  return ((x2 - x1) * (y2 - y1)) / Math.max(1, stroke.w * stroke.h)
}

function textScale(el) {
  const lines = Math.max(1, (el.text.match(/\n/g)?.length ?? 0) + 1)
  return Math.max(0.5, Math.min(4, el.h / lines / TEXT_LINE_PX))
}

function arrowEndBinding(editor, point, geoShapes) {
  for (const g of geoShapes) {
    const b = editor.getShapePageBounds(g.id)
    if (b && b.clone().expandBy(BIND_SLOP).containsPoint(point)) return g
  }
  return null
}

function tidyCluster(editor, cluster) {
  const lead = cluster.lead.meta.ink
  const elements = lead.elements ?? []
  if (elements.length === 0) return { created: [], removed: [] }

  // Strokes may have moved since recognition: shift elements by the delta.
  const now = getBounds(editor, cluster.shapes)
  const dx = now && lead.bounds ? now.x - lead.bounds.x : 0
  const dy = now && lead.bounds ? now.y - lead.bounds.y : 0
  const color = dominantColor(cluster.shapes)
  const meta = { addedBy: "user", semanticRole: "tidied_ink", source: "ink_tidy" }

  const created = []
  const geoShapes = []
  const coverBoxes = []

  // Shapes first so arrows can bind to them.
  const ordered = [...elements].sort((a, b) => (a.kind === "shape" ? -1 : 0) - (b.kind === "shape" ? -1 : 0))

  for (const el of ordered) {
    const x = el.x + dx, y = el.y + dy
    if (el.kind === "doodle") continue

    if (el.kind === "text" || el.kind === "math") {
      if (!el.text) continue
      const id = createShapeId()
      editor.createShape({
        id, type: "text", x, y,
        props: {
          richText: toRichText(el.text), color, size: "m", font: el.kind === "math" ? "mono" : "sans",
          scale: textScale(el), autoSize: true,
        },
        meta: { ...meta, semanticRole: `tidied_${el.kind}` },
      })
      created.push(id)
      coverBoxes.push(new Box(x, y, el.w, el.h))
    } else if (el.kind === "shape") {
      const id = createShapeId()
      editor.createShape({
        id, type: "geo", x, y,
        props: {
          geo: el.shape ?? "rectangle", w: Math.max(24, el.w), h: Math.max(24, el.h),
          richText: toRichText(el.text ?? ""), color, fill: "none", dash: "solid", size: "m",
        },
        meta: { ...meta, semanticRole: "tidied_shape" },
      })
      created.push(id)
      geoShapes.push(editor.getShape(id))
      coverBoxes.push(new Box(x, y, el.w, el.h))
    } else if (el.kind === "arrow" || el.kind === "line") {
      const start = { x: el.start.x + dx, y: el.start.y + dy }
      const end = { x: el.end.x + dx, y: el.end.y + dy }
      const id = createShapeId()
      editor.createShape({
        id, type: "arrow", x: start.x, y: start.y,
        props: {
          start: { x: 0, y: 0 }, end: { x: end.x - start.x, y: end.y - start.y },
          color, size: "m", dash: "solid",
          arrowheadStart: "none", arrowheadEnd: el.kind === "arrow" ? "arrow" : "none",
          richText: toRichText(el.text ?? ""),
        },
        meta: { ...meta, semanticRole: `tidied_${el.kind}` },
      })
      for (const [terminal, point] of [["start", start], ["end", end]]) {
        const target = arrowEndBinding(editor, point, geoShapes)
        if (!target) continue
        try {
          editor.createBinding({
            type: "arrow", fromId: id, toId: target.id,
            props: { terminal, normalizedAnchor: { x: 0.5, y: 0.5 }, isExact: false, isPrecise: false, snap: "none" },
          })
        } catch (err) { console.warn("[Ink] Arrow bind failed", err) }
      }
      created.push(id)
      coverBoxes.push(new Box(el.x + dx, el.y + dy, el.w, el.h))
    }
  }

  // Remove strokes covered by a tidied element; keep doodles.
  const hasDoodles = elements.some(e => e.kind === "doodle")
  const removed = cluster.shapes.filter(s => {
    if (!hasDoodles) return true
    const b = editor.getShapePageBounds(s)?.clone().expandBy(4)
    if (!b) return false
    return coverBoxes.some(box => overlapRatio(b, box.clone().expandBy(12)) >= 0.6)
  }).map(s => s.id)

  return { created, removed }
}

/**
 * Tidy ink in the current selection or viewport.
 * @param {"selection"|"viewport"} scope
 * @returns {Promise<number>} number of clean shapes created
 */
export async function tidyInk(editor, scope = "viewport") {
  const strokes = strokesInScope(editor, scope)
  if (strokes.length === 0) return 0

  setInkState({ status: "tidying" })
  try {
    // Make sure everything in scope has been read.
    await recognizeNow(editor, strokes.map(s => s.id))

    const ids = new Set(strokes.map(s => s.id))
    const clusters = [...getRecognizedClusters(editor).values()]
      .filter(c => c.shapes.some(s => ids.has(s.id)))
    if (clusters.length === 0) return 0

    editor.markHistoryStoppingPoint("tidy ink")
    const allCreated = []
    editor.run(() => {
      for (const cluster of clusters) {
        const { created, removed } = tidyCluster(editor, cluster)
        if (created.length === 0) continue
        editor.deleteShapes(removed)
        allCreated.push(...created)
      }
    })
    if (allCreated.length > 0) editor.select(...allCreated)
    return allCreated.length
  } finally {
    setInkState({ status: "idle" })
  }
}
