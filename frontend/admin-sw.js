/* Minimal service worker — makes the JobifyPL admin panel installable (PWA).
   It is intentionally pass-through: it does NOT cache anything, so the admin
   never sees stale data and normal network behaviour is unchanged. Its only
   job is to satisfy the browser's install criteria. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => { /* network default; no caching */ });
