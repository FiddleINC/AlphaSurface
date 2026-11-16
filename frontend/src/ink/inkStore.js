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

// Assistant modes (see backend/brain/modes.py). Older installs stored a
// plain on/off auto-answer flag: off maps to Quiet, on to Collaborator.
export const MODES = ["tutor", "checker", "collab", "quiet"]
const initialMode = MODES.includes(prefs.mode) ? prefs.mode
  : prefs.autoRespond === false ? "quiet" : "collab"

let state = {
  // "idle" | "reading" | "tidying" | "unavailable" | "rate_limited"
  status: "idle",
  pending: 0,
  lastTranscript: "",
  lastError: "",
  // Spoken-reply / transcript caption shown above the toolbar
  caption: "",
  captionAt: 0,
  // How proactive / revealing the AI is: "tutor" | "checker" | "collab" | "quiet"
  mode: initialMode,
  // Recognize handwriting after each pause
  recognitionEnabled: prefs.recognitionEnabled ?? true,
  // First-run examples card; `welcomed` persists once dismissed
  welcomed: prefs.welcomed ?? false,
  welcomeOpen: false,
  // "Explain my board" panel: { status: "loading" | "done" | "error", data, error }
  explain: null,
}

const PERSISTED = ["mode", "recognitionEnabled", "welcomed"]

const listeners = new Set()

export function getInkState() {
  return state
}

export function setInkState(patch) {
  state = { ...state, ...patch }
  if (PERSISTED.some(k => k in patch)) {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(Object.fromEntries(PERSISTED.map(k => [k, state[k]]))))
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
