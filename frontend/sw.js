const CACHE_NAME = 'ump-gestao-v4';

// Apenas assets estáticos que mudam raramente
const STATIC_ASSETS = [
  '/assets/css/main.css',
  '/assets/css/components.css',
  '/assets/css/layout.css',
  '/assets/js/api.js',
  '/assets/js/auth.js',
  '/assets/js/router.v2.js',
  '/assets/js/utils.js',
  '/assets/img/logo.png',
  '/assets/img/ump_logo.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Nunca faz cache de chamadas à API
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

  // Network-first para páginas HTML — sempre busca versão mais recente
  // e só usa o cache como fallback offline
  if (request.destination === 'document' || url.pathname.endsWith('.html') || url.pathname === '/') {
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Cache-first para assets estáticos (CSS, JS, imagens)
  event.respondWith(
    caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok) {
        const clone = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
      }
      return response;
    }))
  );
});
