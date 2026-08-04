/**
 * LLM Wiki service worker — caches static assets only.
 * API responses (/api/*) are never cached.
 */
const CACHE_NAME = "llm-wiki-static-v1";

const STATIC_ASSETS = [
  "/",
  "/index.html",
  "/app.js",
  "/graph.js",
  "/styles.css",
  "/manifest.json",
  "/vendor/cytoscape.min.js",
  "/vendor/marked.min.js",
  "/vendor/dompurify.min.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => undefined),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
    ),
  );
  self.clients.claim();
});

function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}

function isStaticAsset(url) {
  if (isApiRequest(url)) return false;
  const path = url.pathname;
  if (path === "/" || path.endsWith(".html")) return true;
  if (path.endsWith(".js") || path.endsWith(".css")) return true;
  if (path.endsWith(".png") || path.endsWith(".svg") || path.endsWith(".ico")) return true;
  if (path === "/manifest.json") return true;
  if (path.startsWith("/vendor/")) return true;
  return false;
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;
  if (isApiRequest(url)) return;
  if (!isStaticAsset(url)) return;

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        if (!response || response.status !== 200 || response.type === "opaque") {
          return response;
        }
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return response;
      });
    }),
  );
});
