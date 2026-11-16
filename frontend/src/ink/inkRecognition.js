// ── Handwriting + sketch recognition ──────────────────────────────────────────
// Watches the user's pen/finger strokes. When they pause, nearby strokes are
// clustered, each changed cluster is rendered to a PNG and sent to
// POST /api/ink/recognize. The result (transcript, elements, intent) is
// stored in the lead stroke's meta so that:
//   - canvas snapshots tell the live agent what the handwriting says
//   - Tidy can convert the ink into clean shapes later (even after reload)

import { createShapeId } from "tldraw"
import {
  clusterStrokes, getBounds, getUserInk, isUserInk, needsRecognition, strokeFingerprint,
} from "./inkModel"
import { getInkState, setInkState } from "./inkStore"

const IDLE_MS = 1400          // pause after the last stroke before reading
const PADDING = 24            // page units around a cluster in the image
const MAX_IMAGE_SIDE = 1024   // px
const MAX_STROKES = 400       // skip absurdly large clusters
const RATE_LIMIT_BACKOFF_MS = 20000

let activeEditor = null
let inFlight = null           // Promise of the running pass
let rerunRequested = false
let backoffUntil = 0

async function blobToBase64(blob) {
  const buf = new Uint8Array(await blob.arrayBuffer())
  let bin = ""
  for (let i = 0; i < buf.length; i += 0x8000) {
    bin += String.fromCharCode(...buf.subarray(i, i + 0x8000))
  }
  return btoa(bin)
}

/** Render shapes to a base64 PNG covering exactly `rect` (page space). */
export async function renderShapes(editor, shapes, { padding = PADDING, format = "png" } = {}) {
  const bounds = getBounds(editor, shapes)
  if (!bounds) return null
  const rect = bounds.clone().expandBy(padding)
  const scale = Math.max(0.25, Math.min(2, MAX_IMAGE_SIDE / Math.max(rect.w, rect.h)))
  const { blob } = await editor.toImage(shapes.map(s => s.id), {
    format,
    bounds,
    padding,
    scale,
    pixelRatio: 1,
    background: true,
    darkMode: false,
  })
  return {
    image: await blobToBase64(blob),
    mime: format === "png" ? "image/png" : `image/${format}`,
    rect: { x: rect.x, y: rect.y, w: rect.w, h: rect.h },
  }
}

/** Text of typed shapes near a cluster — helps disambiguate handwriting. */
function nearbyContext(editor, bounds) {
  const area = bounds.clone().expandBy(300)
  return editor.getCurrentPageShapes()
    .filter(s => !isUserInk(s) && s.type !== "draw")
    .filter(s => {
      const b = editor.getShapePageBounds(s)
      return b && area.collides(b)
    })
    .map(s => {
      try { return editor.getShapeUtil(s).getText(s) ?? "" } catch { return "" }
    })
    .filter(Boolean)
    .join(" | ")
    .slice(0, 600)
}

/**
 * The stroke that stores the cluster's result: the previous lead if there is
 * one (so references stay valid across re-recognition), else the top-left one.
 */
function pickLead(editor, strokes) {
  return strokes.find(s => s.meta?.ink?.lead) ?? [...strokes].sort((a, b) => {
    const ba = editor.getShapePageBounds(a), bb = editor.getShapePageBounds(b)
    return (ba.y - bb.y) || (ba.x - bb.x)
  })[0]
}

async function recognizeCluster(editor, strokes) {
  const rendered = await renderShapes(editor, strokes)
  if (!rendered) return null
  const bounds = getBounds(editor, strokes)
  const lead = pickLead(editor, strokes)

  const res = await fetch("/api/ink/recognize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...rendered,
      // Lead first: the backend names the cluster after the first id.
      shapeIds: [lead.id, ...strokes.filter(s => s !== lead).map(s => s.id)],
      context: nearbyContext(editor, bounds),
      autoRespond: getInkState().autoRespond,
    }),
  })
  if (!res.ok) {
    const err = new Error(`recognize failed: ${res.status}`)
    err.status = res.status
    throw err
  }
  return { result: await res.json(), bounds }
}

function writeResult(editor, strokes, result, bounds) {
  const lead = pickLead(editor, strokes)
  const clusterId = (lead.meta?.ink?.lead && lead.meta.ink.clusterId) || createShapeId().slice(6)
  const at = Date.now()

  editor.run(() => {
    for (const s of strokes) {
      // Skip strokes that were deleted while we were waiting.
      const current = editor.getShape(s.id)
      if (!current) continue
      const fp = strokeFingerprint(current)
      const ink = current.id === lead.id
        ? {
            clusterId, lead: true, fp, at,
            text: result.transcript ?? "",
            intent: result.intent ?? "unknown",
            summary: result.summary ?? "",
            elements: result.elements ?? [],
            bounds: { x: bounds.x, y: bounds.y, w: bounds.w, h: bounds.h },
          }
        : { clusterId, lead: false, fp }
      editor.updateShape({ id: current.id, type: current.type, meta: { ...current.meta, ink } })
    }
  }, { history: "ignore" })
}

/** Clusters on the page that contain at least one changed stroke. */
function pendingClusters(editor, onlyIds = null) {
  const ink = getUserInk(editor).filter(s => s.props?.isComplete)
  const clusters = clusterStrokes(editor, ink)
  return clusters.filter(c =>
    c.length <= MAX_STROKES &&
    (onlyIds ? c.some(s => onlyIds.has(s.id)) && c.some(needsRecognition) : c.some(needsRecognition))
  )
}

async function runPass(editor, onlyIds = null) {
  const clusters = pendingClusters(editor, onlyIds)
  if (clusters.length === 0) return
  setInkState({ status: "reading", pending: clusters.length })

  for (const strokes of clusters) {
    try {
      const out = await recognizeCluster(editor, strokes)
      if (!out) continue
      writeResult(editor, strokes, out.result, out.bounds)
      setInkState({
        pending: Math.max(0, getInkState().pending - 1),
        lastTranscript: out.result.transcript || out.result.summary || "",
        lastError: "",
      })
    } catch (err) {
      if (err.status === 503) {
        setInkState({ status: "unavailable", pending: 0, lastError: "Add ANTHROPIC_API_KEY to enable ink AI" })
        return
      }
      if (err.status === 429) {
        backoffUntil = Date.now() + RATE_LIMIT_BACKOFF_MS
        setInkState({ status: "rate_limited", pending: 0, lastError: "Ink AI is busy, retrying soon" })
        return
      }
      console.warn("[Ink] Recognition failed", err)
      setInkState({ lastError: "Could not read that ink" })
    }
  }
  setInkState({ status: "idle", pending: 0 })
}

function schedulePass(editor) {
  if (inFlight) { rerunRequested = true; return inFlight }
  inFlight = (async () => {
    try {
      do {
        rerunRequested = false
        await runPass(editor)
      } while (rerunRequested)
    } finally {
      inFlight = null
    }
  })()
  return inFlight
}

/**
 * Recognize the clusters containing `shapeIds` right now (used by Tidy and
 * Ask AI). Resolves once results are written to the shapes.
 */
export async function recognizeNow(editor, shapeIds) {
  if (getInkState().status === "unavailable") return
  if (inFlight) await inFlight
  await runPass(editor, new Set(shapeIds))
}

function invalidateClusters(editor, clusterIds) {
  const affected = getUserInk(editor).filter(s => clusterIds.has(s.meta?.ink?.clusterId))
  if (affected.length === 0) return
  editor.run(() => {
    for (const s of affected) {
      editor.updateShape({ id: s.id, type: s.type, meta: { ...s.meta, ink: { ...s.meta.ink, fp: null } } })
    }
  }, { history: "ignore" })
}

/** Start watching strokes. Returns a dispose function. */
export function startInkRecognition(editor) {
  activeEditor = editor
  let timer = null

  const tick = () => {
    timer = null
    const st = getInkState()
    if (!st.recognitionEnabled || st.status === "unavailable") return
    if (Date.now() < backoffUntil) { timer = setTimeout(tick, backoffUntil - Date.now()); return }
    // Still drawing? Wait for the pen to lift.
    if (editor.inputs.getIsPointing?.() || editor.isIn("draw.drawing")) {
      timer = setTimeout(tick, 400)
      return
    }
    if (st.status === "rate_limited") setInkState({ status: "idle", lastError: "" })
    schedulePass(editor)
  }

  const unsub = editor.store.listen(({ changes }) => {
    // Erased strokes invalidate the rest of their cluster so it is re-read.
    const removedClusters = new Set(
      Object.values(changes.removed)
        .filter(r => r.typeName === "shape" && r.meta?.ink?.clusterId)
        .map(r => r.meta.ink.clusterId)
    )
    if (removedClusters.size > 0) {
      queueMicrotask(() => invalidateClusters(editor, removedClusters))
    }

    const touched = [...Object.values(changes.added), ...Object.values(changes.updated).map(([, to]) => to)]
    if (removedClusters.size === 0 && !touched.some(r => r.typeName === "shape" && isUserInk(r))) return
    clearTimeout(timer)
    timer = setTimeout(tick, IDLE_MS)
  }, { scope: "document", source: "user" })

  // Read anything left unrecognized from a previous session.
  timer = setTimeout(tick, 2500)

  return () => {
    clearTimeout(timer)
    unsub()
    if (activeEditor === editor) activeEditor = null
  }
}
