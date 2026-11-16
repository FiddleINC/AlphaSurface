// ── Canvas snapshot builder ───────────────────────────────────────────────────
// Builds the snapshot sent to the Python backend via WebSocket
// (backend/tools/snapshot.py merges it into canvas_state):
//   blurryShapes   every shape in the viewport (id, type, bounds, text);
//                  recognized handwriting collapsed to one "ink" entry per cluster
//   focusedShapes  selected and AI-placed shapes, with more detail
// The backend feeds this into Claude's context with each turn.

import { convertToBlurryShape, convertToFocusedShape } from "./shapeConverters"
import { getRecognizedClusters, getBounds } from "../ink/inkModel"

/**
 * Replace each recognized handwriting cluster with one "ink" entry that
 * carries the transcription and the bounds of the whole cluster, so the
 * agent sees "ink: 'x^2 = 9'" instead of dozens of anonymous strokes.
 */
function collapseInk(editor, blurryShapes) {
  const clusters = getRecognizedClusters(editor)
  if (clusters.size === 0) return blurryShapes
  const memberToCluster = new Map()
  for (const [cid, c] of clusters) for (const s of c.shapes) memberToCluster.set(s.id, cid)

  const out = []
  const emitted = new Set()
  for (const b of blurryShapes) {
    const cid = memberToCluster.get(`shape:${b.shapeId}`)
    if (!cid) { out.push(b); continue }
    if (emitted.has(cid)) continue
    emitted.add(cid)
    const c = clusters.get(cid)
    const box = getBounds(editor, c.shapes)
    const ink = c.lead.meta.ink
    out.push({
      shapeId: c.lead.id.slice(6),
      type: "ink",
      x: Math.round(box.x), y: Math.round(box.y), w: Math.round(box.w), h: Math.round(box.h),
      text: ink.text || (ink.summary ? `[sketch] ${ink.summary}` : ""),
    })
  }
  return out
}

/**
 * Build and send the canvas snapshot over WebSocket.
 * Called periodically (every 3s) and immediately when shape count changes.
 *
 * @param {object} editor - tldraw editor instance
 * @param {WebSocket} ws - open WebSocket connection
 */
export function sendCanvasSnapshot(editor, ws) {
  if (!editor || !ws || ws.readyState !== WebSocket.OPEN) return

  const viewport = editor.getViewportPageBounds()
  const allShapes = editor.getCurrentPageShapes()
  const selectedIds = new Set(editor.getSelectedShapeIds())

  // ── Blurry shapes (viewport shapes, lightweight) ─────────────────────────
  const shapesInViewport = allShapes.filter(shape => {
    const bounds = editor.getShapeMaskedPageBounds(shape)
    if (!bounds) return false
    return !(
      bounds.x + bounds.w < viewport.x ||
      bounds.x > viewport.x + viewport.w ||
      bounds.y + bounds.h < viewport.y ||
      bounds.y > viewport.y + viewport.h
    )
  })

  const blurryShapes = collapseInk(
    editor,
    shapesInViewport.map(shape => convertToBlurryShape(editor, shape)).filter(Boolean),
  )

  // ── Focused shapes (selected shapes, full detail) ─────────────────────────
  const selectedShapes = allShapes.filter(s => selectedIds.has(s.id))
  const focusedShapes = selectedShapes.map(shape => convertToFocusedShape(editor, shape))

  // Also include shapes with semantic roles (agent-placed content) that are
  // in viewport but not selected — these get upgraded to focused for better context
  const agentShapesInViewport = shapesInViewport.filter(
    s => !selectedIds.has(s.id) && s.meta?.addedBy && s.meta.addedBy !== "user"
  )
  const agentFocused = agentShapesInViewport
    .slice(0, 10) // cap to avoid flooding context
    .map(shape => convertToFocusedShape(editor, shape))

  const allFocused = [...focusedShapes, ...agentFocused]

  // ── Build and send ────────────────────────────────────────────────────────
  ws.send(JSON.stringify({
    type: "canvas_snapshot",
    payload: {
      blurryShapes,
      focusedShapes: allFocused,

      // Selection
      selectedShapeIds: [...selectedIds].map(id =>
        id.startsWith("shape:") ? id.slice(6) : id
      ),

      shape_count: allShapes.length,

      // Viewport
      viewport: {
        x: Math.round(viewport.x),
        y: Math.round(viewport.y),
        w: Math.round(viewport.w),
        h: Math.round(viewport.h),
        zoom: editor.getZoomLevel(),
      },
    },
  }))
}
