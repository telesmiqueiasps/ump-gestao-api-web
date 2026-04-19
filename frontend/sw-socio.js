const CACHE_NAME = 'ump-socio-v1'

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k.startsWith('ump-socio-'))
            .map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const url = event.request.url
  if (!url.startsWith('http')) return
  if (url.includes('/api/')) return
  if (url.includes('backblazeb2.com')) return

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
            caches.open(CACHE_NAME).then(
              cache => cache.put(event.request, clone))
          }
          return response
        }).catch(() => cached || new Response(''))
      })
    )
    return
  }

  event.respondWith(fetch(event.request))
})

// ── Push notifications ────────────────────────────────────
self.addEventListener('push', (event) => {
  if (!event.data) return
  const data = event.data.json()

  event.waitUntil(
    self.registration.showNotification(data.title || 'Portal do Sócio', {
      body:    data.body  || 'Você tem mensalidades pendentes.',
      icon:    '/assets/img/192-maskable.png',
      badge:   '/assets/img/192-maskable.png',
      tag:     'mensalidade-lembrete',
      renotify: true,
      data:    { url: data.url || '/socio.html' },
    })
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = event.notification.data?.url || '/socio.html'
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(windowClients => {
        for (const client of windowClients) {
          if (client.url.includes('socio') && 'focus' in client) {
            return client.focus()
          }
        }
        if (clients.openWindow) return clients.openWindow(url)
      })
  )
})

self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') self.skipWaiting()
})