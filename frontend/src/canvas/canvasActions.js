// ── Canvas action handler ─────────────────────────────────────────────────────
// Applies the canvas actions the Python backend broadcasts (Claude's tool
// calls and the research / deep-analysis sub-agents) to the tldraw editor.
// Every action here has a matching emitter in backend/tools or sub_agents.

import { createShapeId, toRichText, b64Vecs } from "tldraw"
import { tidyInk } from "../ink/inkTidy"

// ── Valid action types ────────────────────────────────────────────────────────
// Every action except zoom_to_fit and undo carries a payload object.
const PAYLOAD_ACTIONS = new Set([
  // Create
  "add_text", "add_note", "add_geo", "bind_arrow", "add_bookmark", "add_research_card", "draw_freehand",
  // Edit / organize
  "move_shape", "update_shape", "delete_shapes", "align_shapes", "distribute_shapes", "stack_shapes",
  "ink_tidy",
  // Navigate
  "focus_artifact",
])
export const VALID_ACTIONS = new Set([...PAYLOAD_ACTIONS, "zoom_to_fit", "undo"])

// Actions that don't change the document, or manage their own undo history.
const NO_HISTORY_MARK = new Set(["zoom_to_fit", "focus_artifact", "undo", "ink_tidy"])

// ── Validation ────────────────────────────────────────────────────────────────
export function validateCanvasAction(message) {
  if (!message || typeof message !== "object") return { valid: false, reason: "invalid_message" }
  if (typeof message.type !== "string") return { valid: false, reason: "missing_type" }
  if (!VALID_ACTIONS.has(message.type)) return { valid: false, reason: "unknown_type" }
  if (PAYLOAD_ACTIONS.has(message.type) && (!message.payload || typeof message.payload !== "object")) {
    return { valid: false, reason: "missing_payload" }
  }
  return { valid: true }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const TL_COLORS = new Set([
  "black", "grey", "light-violet", "violet", "blue", "light-blue",
  "yellow", "orange", "green", "light-green", "light-red", "red", "white",
])

// Same aliases as backend/tools/colors.py
const COLOR_ALIASES = {
  gray: "grey", purple: "violet", "light-purple": "light-violet", "light-gray": "grey",
  cyan: "light-blue", teal: "blue", pink: "light-red",
}

function normalizeTlColor(value, fallback = "black") {
  const raw = String(value ?? "").trim().toLowerCase().replace(/[_\s]+/g, "-")
  const normalized = COLOR_ALIASES[raw] ?? raw
  return TL_COLORS.has(normalized) ? normalized : fallback
}

function resolveShapeId(rawId) {
  if (!rawId) return createShapeId()
  return String(rawId).startsWith("shape:") ? rawId : createShapeId(rawId)
}

// Convert simple IDs (without "shape:" prefix) to tldraw IDs
function toTldrawId(simpleId) {
  if (!simpleId) return null
  return String(simpleId).startsWith("shape:") ? simpleId : `shape:${simpleId}`
}

/** Normalized ids of the shapes in `ids` that exist on the board. */
function existingIds(editor, ids) {
  return (Array.isArray(ids) ? ids : []).map(toTldrawId).filter(id => id && editor.getShape(id))
}

function toShapeMeta(meta = {}, fallbackRole = "unknown") {
  return {
    semanticRole: meta.semanticRole ?? meta.semantic_role ?? fallbackRole,
    source: meta.source ?? "unknown",
    confidence: meta.confidence ?? 1,
    linked_to: Array.isArray(meta.linked_to) ? meta.linked_to : [],
    addedBy: meta.addedBy ?? meta.added_by ?? "live_agent",
  }
}

function createSemanticCard(editor, { id, x, y, w, h, title, body, color, semanticRole, meta }) {
  editor.createShape({
    id: resolveShapeId(id),
    type: "geo",
    x: x ?? 240, y: y ?? 220,
    props: {
      geo: "rectangle",
      w: w ?? 340, h: h ?? 220,
      richText: toRichText(`${title}\n\n${body}`),
      color: normalizeTlColor(color, "blue"),
      fill: "semi", dash: "solid", size: "m",
    },
    meta: toShapeMeta(meta, semanticRole),
  })
}

// ── AI ink animation helpers ─────────────────────────────────────────────────

function densifyPoints(points, closed) {
  const pts = points.map(pt => ({ x: Number(pt.x) || 0, y: Number(pt.y) || 0 }))
  const out = []
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1]
    out.push(a)
    const steps = Math.floor(Math.hypot(b.x - a.x, b.y - a.y) / 8)
    for (let j = 1; j < steps; j++) {
      const t = j / steps
      out.push({ x: Math.round(a.x + (b.x - a.x) * t), y: Math.round(a.y + (b.y - a.y) * t) })
    }
  }
  out.push(pts[pts.length - 1])
  if (closed) out.push(pts[0])
  return out
}

/** Calls step(fraction 0→1) each frame; stop early if step returns false. */
function animateFrames(durationMs, step) {
  const start = performance.now()
  const frame = (now) => {
    const f = Math.min(1, (now - start) / durationMs)
    const ease = 1 - Math.pow(1 - f, 2)
    if (step(f >= 1 ? 1 : ease) === false || f >= 1) return
    requestAnimationFrame(frame)
  }
  requestAnimationFrame(frame)
}

/** Reveal handwritten text character by character, like it is being written. */
function animateText(editor, id, full) {
  const duration = Math.min(1400, 180 + full.length * 35)
  let shown = 1
  animateFrames(duration, (f) => {
    const shape = editor.getShape(id)
    if (!shape) return false
    const n = Math.max(1, Math.ceil(full.length * f))
    if (n === shown) return true
    shown = n
    editor.run(() => {
      editor.updateShape({ id, type: "text", props: { richText: toRichText(full.slice(0, n)) } })
    }, { history: "ignore" })
    return true
  })
}

// ── Main handler ──────────────────────────────────────────────────────────────
export function handleCanvasMessage(editor, message) {
  if (!editor) return
  const validation = validateCanvasAction(message)
  if (!validation.valid) {
    console.warn("[AlphaSurface] Dropped invalid canvas action", validation.reason, message)
    return
  }

  const p = message.payload ?? {}

  // Each AI change is its own undo step: without a mark, one undo would roll
  // back every AI action since the user's last edit, and the user's edit too.
  if (!NO_HISTORY_MARK.has(message.type)) editor.markHistoryStoppingPoint(`ai:${message.type}`)

  switch (message.type) {

    // ── Create actions ──────────────────────────────────────────────────────

    case "add_text": {
      const id = resolveShapeId(p.id)
      const font = ["draw", "sans", "serif", "mono"].includes(p.font) ? p.font : "draw"
      const full = String(p.text ?? "")
      editor.createShape({
        id,
        type: "text", x: p.x ?? 200, y: p.y ?? 200,
        props: {
          richText: toRichText(p.animate ? full.slice(0, 1) : full),
          size: p.size ?? "m", font, color: normalizeTlColor(p.color, "black"),
        },
        meta: toShapeMeta(p.meta, "text"),
      })
      if (p.animate && full.length > 1) animateText(editor, id, full)
      break
    }

    case "add_note":
      editor.createShape({
        id: resolveShapeId(p.id),
        type: "note", x: p.x ?? 300, y: p.y ?? 300,
        props: { richText: toRichText(p.text), color: normalizeTlColor(p.color, "yellow"), size: p.size ?? "m" },
        meta: toShapeMeta(p.meta, "note"),
      })
      break

    case "add_geo":
      editor.createShape({
        id: resolveShapeId(p.id),
        type: "geo", x: p.x ?? 200, y: p.y ?? 200,
        props: {
          geo: p.geo ?? "rectangle",
          w: p.w ?? 200, h: p.h ?? 120,
          richText: toRichText(p.text ?? ""),
          color: normalizeTlColor(p.color, "blue"),
          fill: p.fill ?? "semi", dash: p.dash ?? "draw", size: p.size ?? "m",
        },
        meta: toShapeMeta(p.meta, "geo"),
      })
      break

    case "bind_arrow": {
      const fromId = toTldrawId(p.fromShapeId), toId = toTldrawId(p.toShapeId)
      const fromShape = fromId && editor.getShape(fromId)
      const toShape = toId && editor.getShape(toId)
      if (!fromShape || !toShape) break
      const arrowId = createShapeId()
      const cx = (fromShape.x + toShape.x) / 2
      const cy = (fromShape.y + toShape.y) / 2
      editor.createShape({
        id: arrowId, type: "arrow", x: cx, y: cy,
        props: {
          start: { x: 0, y: 0 },
          end: { x: toShape.x - fromShape.x, y: toShape.y - fromShape.y },
          richText: toRichText(p.label ?? ""),
          color: normalizeTlColor(p.color, "black"), size: p.size ?? "m",
          arrowheadEnd: "arrow", arrowheadStart: "none",
        },
      })
      editor.createBinding({ type: "arrow", fromId: arrowId, toId: fromId, props: { terminal: "start", normalizedAnchor: { x: 0.5, y: 0.5 }, isExact: false, isPrecise: false, snap: "none" } })
      editor.createBinding({ type: "arrow", fromId: arrowId, toId: toId, props: { terminal: "end", normalizedAnchor: { x: 0.5, y: 0.5 }, isExact: false, isPrecise: false, snap: "none" } })
      break
    }

    case "add_bookmark":
      editor.createShape({
        id: resolveShapeId(p.id),
        type: "bookmark", x: p.x ?? 200, y: p.y ?? 200,
        props: { url: p.url, w: 300, h: 160, assetId: null },
        meta: toShapeMeta(p.meta, "bookmark"),
      })
      break

    case "add_research_card": {
      const bullets = Array.isArray(p.bullets) && p.bullets.length > 0
        ? p.bullets.map(item => `- ${item}`).join("\n") : ""
      const src = p.source ?? {}
      const sourceLine = src.url ? `Source: ${src.label ? `${src.label} (${src.url})` : src.url}` : ""
      const body = [bullets, sourceLine].filter(Boolean).join("\n\n")
      createSemanticCard(editor, {
        id: p.id, x: p.x, y: p.y, w: p.w ?? 420, h: p.h ?? 280,
        title: p.title ?? "Research", body, color: "light-blue",
        semanticRole: "research_card",
        meta: { source: "ResearchAgent", addedBy: "ResearchAgent", ...(p.meta ?? {}) },
      })
      break
    }

    case "draw_freehand": {
      if (!Array.isArray(p.points) || p.points.length < 2) break
      const points = densifyPoints(p.points, p.closed)
      const minX = Math.min(...points.map(pt => pt.x))
      const minY = Math.min(...points.map(pt => pt.y))
      // Simulated pen pressure: taper in, press through the middle, lift out.
      const segPoints = points.map((pt, i) => {
        const t = points.length > 1 ? i / (points.length - 1) : 0
        const z = 0.35 + 0.4 * Math.sin(Math.PI * Math.min(1, t * 1.15))
        return { x: pt.x - minX, y: pt.y - minY, z: Math.round(z * 100) / 100 }
      })
      const id = resolveShapeId(p.id)
      const props = (pts, done) => ({
        color: normalizeTlColor(p.color, "black"),
        fill: "none",
        dash: "draw",
        size: ["s", "m", "l", "xl"].includes(p.size) ? p.size : "s",
        segments: [{ type: "free", path: b64Vecs.encodePoints(pts) }],
        isComplete: done,
        isClosed: !!p.closed && done,
        isPen: true,
      })
      const animate = !!p.animate && segPoints.length > 3
      editor.createShape({
        id, type: "draw", x: minX, y: minY,
        props: props(animate ? segPoints.slice(0, 2) : segPoints, !animate),
        meta: toShapeMeta(p.meta, "ink"),
      })
      if (animate) {
        const duration = Math.min(900, 220 + segPoints.length * 6)
        animateFrames(duration, (f) => {
          const shape = editor.getShape(id)
          if (!shape) return false
          const n = Math.max(2, Math.ceil(segPoints.length * f))
          editor.run(() => {
            editor.updateShape({ id, type: "draw", props: props(segPoints.slice(0, n), f >= 1) })
          }, { history: "ignore" })
          return true
        })
      }
      break
    }

    case "ink_tidy":
      tidyInk(editor, p.scope === "selection" ? "selection" : "viewport")
        .catch(err => console.warn("[AlphaSurface] Tidy failed", err))
      break

    // ── Move (anchor-aware) ─────────────────────────────────────────────────
    // Accounts for the offset between a shape's origin and its visible bounds,
    // and moves the given anchor point of the shape to (x, y).

    case "move_shape": {
      const shapeId = toTldrawId(p.shapeId)
      if (!shapeId) break
      const shape = editor.getShape(shapeId)
      if (!shape) break

      const shapeBounds = editor.getShapePageBounds(shapeId)
      if (!shapeBounds) break

      const targetX = p.x ?? shape.x
      const targetY = p.y ?? shape.y
      const anchor = p.anchor ?? "top-left"

      // Offset between shape record origin and its page bounds top-left
      const originDeltaX = shape.x - shapeBounds.minX
      const originDeltaY = shape.y - shapeBounds.minY

      // Anchor offsets
      const anchorOffsets = {
        "top-left":      [0,                   0],
        "top-center":    [shapeBounds.w / 2,    0],
        "top-right":     [shapeBounds.w,        0],
        "center-left":   [0,                   shapeBounds.h / 2],
        "center":        [shapeBounds.w / 2,    shapeBounds.h / 2],
        "center-right":  [shapeBounds.w,        shapeBounds.h / 2],
        "bottom-left":   [0,                   shapeBounds.h],
        "bottom-center": [shapeBounds.w / 2,    shapeBounds.h],
        "bottom-right":  [shapeBounds.w,        shapeBounds.h],
      }

      const [ax, ay] = anchorOffsets[anchor] ?? [0, 0]
      const newX = targetX - ax + originDeltaX
      const newY = targetY - ay + originDeltaY

      editor.updateShape({ id: shapeId, type: shape.type, x: newX, y: newY })
      break
    }

    // ── Update existing shape ────────────────────────────────────────────────

    case "update_shape": {
      const shapeId = toTldrawId(p.shapeId)
      if (!shapeId) break
      const shape = editor.getShape(shapeId)
      if (!shape) break
      const props = { ...shape.props }
      if (p.text !== undefined) props.richText = toRichText(p.text)
      if (p.color !== undefined) props.color = normalizeTlColor(p.color, shape.props?.color ?? "black")
      if (p.fill !== undefined) props.fill = p.fill
      if (p.w !== undefined) props.w = p.w
      if (p.h !== undefined) props.h = p.h
      editor.updateShape({ id: shapeId, type: shape.type, props })
      break
    }

    // ── Navigation ───────────────────────────────────────────────────────────

    case "zoom_to_fit":
      editor.zoomToFit()
      break

    case "focus_artifact": {
      const ids = existingIds(editor, p.shapeIds)
      const focus = ids.length > 0 ? ids : existingIds(editor, [p.primaryShapeId])
      if (focus.length > 0) { editor.select(...focus); editor.zoomToSelection({ animation: { duration: 300 } }) }
      break
    }

    // ── Edit / organize ──────────────────────────────────────────────────────

    case "delete_shapes": {
      const ids = existingIds(editor, p.shapeIds)
      if (ids.length > 0) editor.deleteShapes(ids)
      break
    }

    case "align_shapes": {
      const ids = existingIds(editor, p.shapeIds)
      if (ids.length > 1) editor.alignShapes(ids, p.alignment)
      break
    }

    case "distribute_shapes": {
      const ids = existingIds(editor, p.shapeIds)
      if (ids.length > 2) editor.distributeShapes(ids, p.direction)
      break
    }

    case "stack_shapes": {
      const ids = existingIds(editor, p.shapeIds)
      const direction = p.direction === "horizontal" ? "horizontal" : "vertical"
      if (ids.length > 1) editor.stackShapes(ids, direction, Number(p.gap) || 20)
      break
    }

    case "undo":
      editor.undo()
      break

    default:
      console.warn("[AlphaSurface] Unknown message type:", message.type)
  }
}
