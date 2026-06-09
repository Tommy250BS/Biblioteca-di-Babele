const CACHE = "rbbc-v4";
const ASSETS = ["/", "/index.html"];

// INSTALL: salva asset iniziali
self.addEventListener("install", (event) => {
  self.skipWaiting(); // forza attivazione immediata

  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ASSETS))
  );
});

// ACTIVATE: elimina vecchie cache
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE)
          .map((key) => caches.delete(key))
      )
    )
  );

  self.clients.claim(); // prende subito controllo delle pagine aperte
});

// FETCH: Network First per HTML, Cache First per il resto
self.addEventListener("fetch", (event) => {
  if (event.request.url.includes("/api/")) return;

  // HTML → sempre aggiornato
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match("/index.html"))
    );
    return;
  }

  // Static assets → cache-first
  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request).then((response) => {
        return caches.open(CACHE).then((cache) => {
          cache.put(event.request, response.clone());
          return response;
        });
      });
    })
  );
});
