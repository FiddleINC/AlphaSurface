// ── Ink model helpers ─────────────────────────────────────────────────────────
// "Ink" = freehand draw shapes made by the user with a pencil, finger or mouse.
// Strokes close to each other are grouped into clusters (a word, a line of
// handwriting, a sketch). A recognized cluster stores its result in the meta
// of its *lead* stroke:
//
//   lead.meta.ink   = { clusterId, lead: true, text, intent, summary,
//                       elements, bounds, fp, at }
//   other.meta.ink  = { clusterId, lead: false, fp }

import { Box } from "tldraw"

// Strokes closer than this (page units) belong to the same cluster.
export const CLUSTER_GAP = 48

export function isUserInk(shape) {
  if (!shape || shape.type !== "draw") return false
  const by = shape.meta?.addedBy
  return !by || by === "user"
}

/** Content fingerprint: changes when strokes are edited, not when moved. */
export function strokeFingerprint(shape) {
  const segs = shape.props?.segments ?? []
  let n = 0
  for (const s of segs) n += (s.path?.length ?? 0) + 1
  return `${segs.length}:${n}:${shape.props?.scale ?? 1}:${shape.props?.isComplete ? 1 : 0}`
}

export function getUserInk(editor) {
  return editor.getCurrentPageShapes().filter(isUserInk)
}

export function getBounds(editor, shapes) {
  const boxes = shapes.map(s => editor.getShapePageBounds(s)).filter(Boolean)
  return boxes.length ? Box.Common(boxes) : null
}

/** Group strokes into proximity clusters (union-find on padded bounds). */
export function clusterStrokes(editor, strokes, gap = CLUSTER_GAP) {
  const items = strokes
    .map(shape => ({ shape, box: editor.getShapePageBounds(shape) }))
    .filter(i => i.box)
  const parent = items.map((_, i) => i)
  const find = i => (parent[i] === i ? i : (parent[i] = find(parent[i])))

  for (let i = 0; i < items.length; i++) {
    const a = items[i].box.clone().expandBy(gap / 2)
    for (let j = i + 1; j < items.length; j++) {
      const b = items[j].box.clone().expandBy(gap / 2)
      if (a.collides(b)) parent[find(i)] = find(j)
    }
  }

  const groups = new Map()
  items.forEach((item, i) => {
    const root = find(i)
    if (!groups.has(root)) groups.set(root, [])
    groups.get(root).push(item.shape)
  })
  return [...groups.values()]
}

/** Recognized clusters on the current page, keyed by clusterId. */
export function getRecognizedClusters(editor) {
  const clusters = new Map()
  for (const shape of getUserInk(editor)) {
    const ink = shape.meta?.ink
    if (!ink?.clusterId) continue
    if (!clusters.has(ink.clusterId)) clusters.set(ink.clusterId, { lead: null, shapes: [] })
    const c = clusters.get(ink.clusterId)
    c.shapes.push(shape)
    if (ink.lead) c.lead = shape
  }
  for (const [id, c] of clusters) if (!c.lead) clusters.delete(id)
  return clusters
}

export function needsRecognition(shape) {
  if (!isUserInk(shape) || !shape.props?.isComplete) return false
  return shape.meta?.ink?.fp !== strokeFingerprint(shape)
}

const COLOR_ORDER = ["black", "blue", "red", "green", "violet", "orange", "grey"]

/** Most common stroke color in a set of shapes. */
export function dominantColor(shapes) {
  const counts = {}
  for (const s of shapes) {
    const c = s.props?.color ?? "black"
    counts[c] = (counts[c] ?? 0) + 1
  }
  return Object.entries(counts).sort((a, b) =>
    b[1] - a[1] || COLOR_ORDER.indexOf(a[0]) - COLOR_ORDER.indexOf(b[0])
  )[0]?.[0] ?? "black"
}
