import { createRoot } from 'react-dom/client'
import React from 'react'
import App from './App.jsx'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  
  componentDidCatch(error, errorInfo) {
    console.error("AlphaSurface Error Boundary caught an error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ color: '#ef4444', background: '#020617', padding: '40px', fontFamily: 'sans-serif', height: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
          <h2>Something went wrong.</h2>
          <p style={{ color: '#94a3b8' }}>Please refresh the page.</p>
        </div>
      );
    }
    return this.props.children; 
  }
}

createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
)

// Installable PWA: register the service worker in production builds only
// (in dev it would cache Vite's modules and fight hot reload).
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(err =>
      console.warn("[AlphaSurface] Service worker registration failed", err)
    )
  })
}
