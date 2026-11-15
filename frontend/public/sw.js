// AlphaSurface service worker — makes the whiteboard installable and lets the
// app shell open offline. The canvas itself is stored locally by tldraw
// (IndexedDB), so drawing works offline; AI features need the network.
//
// Strategy:
//   navigations        → network first, fall back to cached shell
//   /assets/* (hashed) → cache first (immutable build output)
//   icons/manifest     → stale-while-revalidate
//   /api, /ws, /static → never cached (live AI traffic)

const VERSION = "v1"
const SHELL_CACHE = `alphasurface-shell-${VERSION}`
const ASSET_CACHE = `alphasurface-assets-${VERSION}`
const SHELL = ["/", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon.svg"]

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k.startsWith("alphasurface-") && ![SHELL_CACHE, ASSET_CACHE].includes(k))
          .map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  )
})

self.addEventListener("fetch", (event) => {
  const req = event.request
  if (req.method !== "GET") return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return
  if (/^\/(api|ws|static)(\/|$)/.test(url.pathname)) return

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone()
          caches.open(SHELL_CACHE).then((c) => c.put("/", copy))
          return res
        })
        .catch(() => caches.match("/"))
    )
    return
  }

  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok) {
          const copy = res.clone()
          caches.open(ASSET_CACHE).then((c) => c.put(req, copy))
        }
        return res
      }))
    )
    return
  }

  event.respondWith(
    caches.match(req).then((hit) => {
      const network = fetch(req).then((res) => {
        if (res.ok) {
          const copy = res.clone()
          caches.open(SHELL_CACHE).then((c) => c.put(req, copy))
        }
        return res
      }).catch(() => hit)
      return hit || network
    })
  )
})
