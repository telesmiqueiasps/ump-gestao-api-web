const CACHE_NAME = 'ump-gestao-v1';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/pages/dashboard.html',
  '/pages/finances.html',
  '/pages/profile.html',
  '/pages/board.html',
  '/pages/members.html',
  '/pages/local-umps.html',
  '/assets/css/main.css',
  '/assets/css/components.css',
  '/assets/css/layout.css',
  '/assets/js/api.js',
  '/assets/js/auth.js',
  '/assets/js/router.js',
  '/assets/js/utils.js',
  '/assets/img/logo.png',
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
  // Nunca faz cache de chamadas à API
  if (event.request.url.includes('/api/')) {
    event.respondWith(fetch(event.request));
    return;
  }
  // Cache first para assets estáticos
  event.respondWith(
    caches.match(event.request).then(cached => cached || fetch(event.request).then(response => {
      if (response.ok) {
        const clone = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
      }
      return response;
    }))
  );
});
