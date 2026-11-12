// Knwlge's service worker: makes the app installable and keeps its own files (HTML shell, CSS, scripts, fonts,
// icons) in a cache so it opens fast. It never caches /api: courses, answers and accounts always come from the server.
// The server stamps VERSION from the app's files, so a new build gets a fresh cache and the old one is dropped.
const VERSION = "__VERSION__";
const CACHE = `knwlge-${VERSION}`;
const SHELL = ["/", "/static/app.css", "/manifest.webmanifest", "/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith("knwlge-") && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const cacheable = (url) => url.origin === self.location.origin
  && (url.pathname.startsWith("/static/") || url.pathname.startsWith("/vendor/") || /^\/[a-z0-9-]+\.png$/.test(url.pathname)
      || url.pathname === "/manifest.webmanifest");

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;   // data: always the network

  if (req.mode === "navigate") {
    // the page itself: the network first (so updates show), the cached shell when offline
    event.respondWith(fetch(req).then((res) => {
      if (res.ok && url.pathname === "/") caches.open(CACHE).then((c) => c.put("/", res.clone()));
      return res;
    }).catch(() => caches.match("/")));
    return;
  }
  if (cacheable(url)) {
    // the app's own files: from the cache once fetched (this cache is per build, so it can't go stale)
    event.respondWith(caches.open(CACHE).then(async (c) => {
      const hit = await c.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok) c.put(req, res.clone());
      return res;
    }));
  }
});
