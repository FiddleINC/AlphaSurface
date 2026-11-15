// ── Pencil + finger input ─────────────────────────────────────────────────────
// tldraw already does palm rejection: once a stylus is seen it switches to
// "pen mode" and ignores touch pointers for drawing. On top of that we add the
// gestures people expect from note-taking apps:
//   - pen mode: one finger pans the canvas (two fingers still pinch-zoom)
//   - pen mode: two-finger tap = undo, three-finger tap = redo
//     (only in pen mode, where fingers never leave stray marks)
//   - start in the draw tool, so the board is ready to write on

const TAP_MAX_MS = 260
const TAP_MAX_MOVE = 14

export function setPencilOnly(editor, on) {
  editor.updateInstanceState({ isPenMode: !!on })
}

export function startPenInput(editor) {
  const container = editor.getContainer()
  if (editor.getCurrentToolId() === "select" && !editor.getSelectedShapeIds().length) {
    editor.setCurrentTool("draw")
  }

  const touches = new Map() // pointerId → { x, y, startX, startY }
  let gesture = null        // { startedAt, count, moved }
  let panId = null

  const isPenMode = () => editor.getInstanceState().isPenMode

  const onDown = (e) => {
    if (e.pointerType !== "touch") return
    touches.set(e.pointerId, { x: e.clientX, y: e.clientY, startX: e.clientX, startY: e.clientY })

    if (!gesture || touches.size === 1) gesture = { startedAt: performance.now(), count: 0, moved: false }
    gesture.count = Math.max(gesture.count, touches.size)

    // In pen mode, a single finger pans.
    panId = isPenMode() && touches.size === 1 ? e.pointerId : null
  }

  const onMove = (e) => {
    const t = touches.get(e.pointerId)
    if (!t) return
    const dx = e.clientX - t.x, dy = e.clientY - t.y
    t.x = e.clientX; t.y = e.clientY
    if (gesture && Math.hypot(t.x - t.startX, t.y - t.startY) > TAP_MAX_MOVE) gesture.moved = true

    if (panId === e.pointerId && touches.size === 1 && isPenMode()) {
      const cam = editor.getCamera()
      editor.setCamera({ x: cam.x + dx / cam.z, y: cam.y + dy / cam.z, z: cam.z }, { immediate: true })
    }
  }

  const onUp = (e) => {
    if (!touches.has(e.pointerId)) return
    touches.delete(e.pointerId)
    if (panId === e.pointerId) panId = null
    if (touches.size > 0 || !gesture) return

    const quick = performance.now() - gesture.startedAt < TAP_MAX_MS
    if (quick && !gesture.moved && isPenMode()) {
      if (gesture.count === 2) editor.undo()
      else if (gesture.count === 3) editor.redo()
    }
    gesture = null
  }

  const opts = { capture: true, passive: true }
  container.addEventListener("pointerdown", onDown, opts)
  window.addEventListener("pointermove", onMove, opts)
  window.addEventListener("pointerup", onUp, opts)
  window.addEventListener("pointercancel", onUp, opts)

  return () => {
    container.removeEventListener("pointerdown", onDown, opts)
    window.removeEventListener("pointermove", onMove, opts)
    window.removeEventListener("pointerup", onUp, opts)
    window.removeEventListener("pointercancel", onUp, opts)
  }
}
