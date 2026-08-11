// service-worker.js — cache mínima del app shell para que la PWA abra
// instantáneamente desde la pantalla de inicio incluso con red lenta.
// Los datos (/expense-tracker/expenses*) van siempre a red: nunca queremos
// mostrar un total de gastos cacheado y desactualizado.

const CACHE_NAME = "expense-tracker-shell-v1";
const SHELL_FILES = [
  "/expense-tracker/",
  "/expense-tracker/index.html",
  "/expense-tracker/app.css",
  "/expense-tracker/app.js",
  "/expense-tracker/manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Datos: siempre red primero, sin fallback a caché desactualizada.
  if (url.pathname.includes("/expenses") || url.pathname.includes("/webhook")) {
    event.respondWith(fetch(event.request));
    return;
  }

  // App shell: cache-first para arranque instantáneo.
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
