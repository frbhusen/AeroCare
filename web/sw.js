// Service worker: caches the APP SHELL only (HTML/CSS/JS/images). Never caches /api/ responses.
// Strategy: network-first (always fresh when online), cached copy when offline.
const CACHE = "hc-shell-v1";
const SHELL = [
  "/", "/index.html", "/manifest.json", "/img/icon.svg",
  "/css/tokens.css", "/css/base.css", "/css/components.css", "/css/shell.css", "/css/media.css", "/css/print.css",
  "/js/core/boot.js", "/js/core/api.js", "/js/core/dom.js", "/js/core/events.js", "/js/core/i18n.js", "/js/core/state.js",
  "/js/core/perm.js", "/js/core/registry.js", "/js/core/router.js", "/js/core/shell.js", "/js/core/topbar.js",
  "/js/core/department.js", "/js/core/index.js", "/js/core/locales/en.js", "/js/core/locales/ar.js", "/js/modules.js",
  "/js/auth/login.js", "/js/auth/session.js", "/js/portal/index.js", "/js/center/index.js",
  "/js/offline/idb.js", "/js/offline/queue.js", "/js/offline/cache.js", "/js/offline/status.js", "/js/offline/sync-panel.js",
  "/js/components/icons.js", "/js/components/states.js", "/js/components/toast.js", "/js/components/modal.js",
  "/js/components/table.js", "/js/components/form.js", "/js/components/tabs.js", "/js/components/patient-search.js",
  "/js/components/uploader.js", "/js/components/image-viewer.js", "/js/components/print.js", "/js/components/barcode.js",
  "/js/components/connectivity.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith("hc-shell-") && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return; // never touch the API

  const isPage = req.mode === "navigate";
  event.respondWith((async () => {
    try {
      const res = await fetch(req);
      const type = res.headers.get("Content-Type") || "";
      // unknown paths fall back to index.html on the server: don't cache HTML under a .js/.css name
      const htmlForAsset = !isPage && /\.(js|css|json|svg|png)$/.test(url.pathname) && type.includes("text/html");
      if (res.ok && !htmlForAsset) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(isPage ? "/index.html" : req, copy));
      }
      return res;
    } catch (err) {
      const cached = await caches.match(isPage ? "/index.html" : req);
      if (cached) return cached;
      throw err;
    }
  })());
});
