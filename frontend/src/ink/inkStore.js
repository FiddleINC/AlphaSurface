// ── Ink UI store ──────────────────────────────────────────────────────────────
// Tiny observable store shared by the ink pipeline (non-React) and the ink
// toolbar (React). Preferences persist per device in localStorage.

import { useSyncExternalStore } from "react"

const PREFS_KEY = "alpha_surface_ink_prefs"

function loadPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

const prefs = loadPrefs()

let state = {
  // "idle" | "reading" | "tidying" | "unavailable" | "rate_limited"
  status: "idle",
  pending: 0,
  lastTranscript: "",
  lastError: "",
  // Spoken-reply / transcript caption shown above the toolbar
  caption: "",
  captionAt: 0,
  // Answer handwritten questions ("12 × 8 =", "why?") automatically
  autoRespond: prefs.autoRespond ?? true,
  // Recognize handwriting after each pause
  recognitionEnabled: prefs.recognitionEnabled ?? true,
}

const listeners = new Set()

export function getInkState() {
  return state
}

export function setInkState(patch) {
  state = { ...state, ...patch }
  if ("autoRespond" in patch || "recognitionEnabled" in patch) {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({
        autoRespond: state.autoRespond,
        recognitionEnabled: state.recognitionEnabled,
      }))
    } catch { /* storage unavailable (private mode) */ }
  }
  listeners.forEach(fn => fn())
}

function subscribe(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function useInkState() {
  return useSyncExternalStore(subscribe, getInkState, getInkState)
}
