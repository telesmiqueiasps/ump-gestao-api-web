const CACHE_NAME = 'ump-gestao-v7'

// Apenas imagens são cacheadas
const STATIC_ASSETS = [
  '/assets/img/logo.png',
  '/assets/img/192-maskable.png',
  '/assets/img/512-maskable.png',
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
        keys.map(k => caches.delete(k)) // apaga TODOS os caches antigos
      ))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const url = event.request.url

  // Ignora tudo que não for http/https
  if (!url.startsWith('http')) return

  // NUNCA cacheia JS, CSS, HTML ou chamadas de API
  if (
    url.includes('/api/') ||
    url.includes('backblazeb2.com') ||
    url.includes('fonts.googleapis.com') ||
    url.includes('fonts.gstatic.com') ||
    url.endsWith('.js') ||
    url.endsWith('.css') ||
    url.endsWith('.html') ||
    url.includes('.js?') ||
    url.includes('.css?') ||
    url.includes('.html?')
  ) {
    event.respondWith(
      fetch(event.request).catch(() => {
        // Se falhar, retorna response vazio
        return new Response('Network error', { status: 503 })
      })
    )
    return
  }

  // Cache apenas para imagens
  if (
    url.includes('/assets/img/') ||
    url.endsWith('.png') ||
    url.endsWith('.jpg') ||
    url.endsWith('.webp') ||
    url.endsWith('.ico')
  ) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        if (cached) return cached
        return fetch(event.request).then(response => {
          if (response && response.ok) {
            const clone = response.clone()
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone))
          }
          return response
        }).catch(err => {
          // Se falhar, tenta servir do cache ou retorna erro
          return caches.match(event.request) || new Response('Network error', { status: 503 })
        })
      })
    )
    return
  }

  // Todo o resto vai direto para a rede sem cache
  event.respondWith(
    fetch(event.request).catch(() => {
      return new Response('Network error', { status: 503 })
    })
  )
})

self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') self.skipWaiting()
})