const CACHE_NAME = 'ump-gestao-v8'
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/pages/dashboard.html',
  '/pages/finances.html',
  '/pages/profile.html',
  '/pages/board.html',
  '/pages/members.html',
  '/pages/local-umps.html',
  '/pages/secretary.html',
  '/pages/president.html',
  '/pages/notices.html',
  '/assets/css/main.css',
  '/assets/css/components.css',
  '/assets/css/layout.v2.css',
  '/assets/js/api.js',
  '/assets/js/auth.js',
  '/assets/js/router.v3.js',
  '/assets/js/utils.js',
  '/assets/img/logo.png',
  '/manifest.json',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const url = event.request.url

  // Ignora tudo que não for http/https
  if (!url.startsWith('http')) return

  // Nunca cacheia chamadas à API
  if (url.includes('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() =>
        new Response(JSON.stringify({ detail: 'Sem conexão' }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        })
      )
    )
    return
  }

  // Nunca cacheia Backblaze
  if (url.includes('backblazeb2.com') || url.includes('backblaze.com')) return

  // Nunca cacheia fontes externas para evitar problemas
  if (url.includes('fonts.googleapis.com') || url.includes('fonts.gstatic.com')) {
    event.respondWith(fetch(event.request).catch(() => new Response('')))
    return
  }

  // Cache first para assets estáticos
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached
      return fetch(event.request).then(response => {
        if (response && response.ok && response.type !== 'opaque') {
          const clone = response.clone()
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone))
        }
        return response
      }).catch(() => {
        // Fallback para páginas HTML — redireciona para index
        if (event.request.destination === 'document') {
          return caches.match('/index.html')
        }
        return new Response('')
      })
    })
  )
})

// Recebe mensagem para forçar atualização do cache
self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') self.skipWaiting()
})