const CACHE_NAME = "rbbc-runtime-cache";

// INSTALL
self.addEventListener("install", (event) => {
  self.skipWaiting();
});

// ACTIVATE → pulisce TUTTE le cache vecchie
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.map((key) => caches.delete(key))
      )
    )
  );

  self.clients.claim();
});

// FETCH
self.addEventListener("fetch", (event) => {
  const request = event.request;

  // API sempre live
  if (request.url.includes("/api/")) {
    return;
  }

  // Risorse esterne (CDN, font, ecc.) → passano dirette alla rete
  if (new URL(request.url).origin !== self.location.origin) {
    return;
  }

  // HTML → sempre dal network (mai cache bloccante)
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match("/index.html"))
    );
    return;
  }

  // STATIC → stale-while-revalidate (strategia migliore)
  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(request);

      const fetchPromise = fetch(request)
        .then((networkResponse) => {
          cache.put(request, networkResponse.clone());
          return networkResponse;
        })
        .catch(() => cached);

      return cached || fetchPromise;
    })
  );
});
