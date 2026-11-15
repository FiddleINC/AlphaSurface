// ── App.jsx ───────────────────────────────────────────────────────────────────
// Root component. Was 1264 lines. Now 50.
// All logic lives in dedicated modules.

import { useCallback, useState } from "react"
import { Tldraw } from "tldraw"
import "tldraw/tldraw.css"

import { activatePlaybackContext, setPlaybackEnabled } from "./audio/AudioPlayback"
import { AlphaSurfaceInner } from "./agent/AlphaSurfaceInner"
import { AlphaMainMenu } from "./components/AlphaMainMenu"
import { StartScreen } from "./components/StartScreen"

export default function App() {
  // Shown on every launch: the start tap unlocks audio playback and the mic.
  const [config, setConfig] = useState(null)

  const handleLaunch = useCallback((cfg) => {
    setPlaybackEnabled(cfg.voiceEnabled)
    if (cfg.voiceEnabled) activatePlaybackContext()
    setConfig(cfg)
  }, [])

  if (!config) return <StartScreen onStart={handleLaunch} />

  return (
    <div style={{ position: "fixed", inset: 0 }}>
      {/* tldraw reads its license from VITE_TLDRAW_LICENSE_KEY (see README).
          Without one it runs unlicensed on localhost for development. */}
      <Tldraw
        persistenceKey="alphasurface"
        forceMobile
        components={{ MainMenu: AlphaMainMenu }}
      >
        <AlphaSurfaceInner config={config} />
      </Tldraw>
    </div>
  )
}
