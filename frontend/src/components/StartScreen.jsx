// ── StartScreen ───────────────────────────────────────────────────────────────
// One tap to start. The tap is also what lets browsers (iPad Safari in
// particular) play the AI's voice and open the microphone.

const card = {
  width: "min(420px, calc(100vw - 32px))",
  padding: "28px 24px",
  borderRadius: 24,
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
  color: "#f4f4f5",
  fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
  textAlign: "center",
}

const button = (primary) => ({
  width: "100%", minHeight: 52, borderRadius: 14, border: "none", cursor: "pointer",
  fontSize: 16, fontWeight: 600, marginTop: 12, touchAction: "manipulation",
  background: primary ? "linear-gradient(90deg,#8b5cf6,#06b6d4)" : "rgba(255,255,255,0.08)",
  color: primary ? "#fff" : "rgba(255,255,255,0.85)",
})

export function StartScreen({ onStart }) {
  return (
    <div style={{
      position: "fixed", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
      background: "#0b0b10", padding: 16,
    }}>
      <div style={card}>
        <img src="/icons/icon.svg" alt="" width={64} height={64} style={{ borderRadius: 16 }} />
        <h1 style={{ fontSize: 24, margin: "16px 0 8px" }}>AlphaSurface</h1>
        <p style={{ margin: 0, color: "rgba(255,255,255,0.6)", lineHeight: 1.5, fontSize: 15 }}>
          Write and sketch with your pencil or finger. The AI reads your ink, answers next to it,
          and you can talk to it while you draw.
        </p>
        <button style={button(true)} onClick={() => onStart({ voiceEnabled: true })}>
          Start with voice
        </button>
        <button style={button(false)} onClick={() => onStart({ voiceEnabled: false })}>
          Start without voice
        </button>
      </div>
    </div>
  )
}
