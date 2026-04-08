const CACHE_NAME = 'ump-gestao-v8'

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const url = event.request.url

  // Ignora tudo que não for http/https
  if (!url.startsWith('http')) return

  // NUNCA intercepta HTML — deixa ir direto para a rede
  if (
    event.request.destination === 'document' ||
    url.endsWith('.html') ||
    url.includes('.html?')
  ) return

  // NUNCA intercepta JS ou CSS
  if (
    url.endsWith('.js') || url.includes('.js?') ||
    url.endsWith('.css') || url.includes('.css?')
  ) return

  // NUNCA intercepta API ou Backblaze
  if (url.includes('/api/') || url.includes('backblazeb2.com')) return

  // Cache apenas imagens
  if (
    url.endsWith('.png') || url.endsWith('.jpg') ||
    url.endsWith('.webp') || url.endsWith('.ico') ||
    url.endsWith('.svg')
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
        }).catch(() => cached || new Response(''))
      })
    )
    return
  }

  // Todo o resto vai direto para a rede sem cache
  event.respondWith(fetch(event.request))
})

self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') self.skipWaiting()
})
