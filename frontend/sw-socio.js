const CACHE_NAME = 'ump-socio-v1'

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll([
        '/socio.html',
        '/assets/img/logo.png',
      ])
    }).then(() => self.skipWaiting())
  )
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

  const options = {
    body:     data.body  || 'Você tem uma mensagem da sua UMP.',
    icon:     data.icon  || '/assets/img/logo.png',
    badge:    data.badge || '/assets/img/logo.png',
    tag:      'mensalidade-lembrete',
    renotify: false,
    vibrate:  [200, 100, 200],
    data:     { url: data.url || '/socio.html' },
    actions:  [
      { action: 'open',  title: '📱 Abrir Portal' },
      { action: 'close', title: '✕ Fechar' },
    ],
  }

  event.waitUntil(
    self.registration.showNotification(
      data.title || '💰 Lembrete de Mensalidade',
      options
    )
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()

  if (event.action === 'close') return

  const url = event.notification.data?.url || '/socio.html'
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(windowClients => {
        for (const client of windowClients) {
          if ('focus' in client) {
            client.focus()
            client.navigate(url)
            return
          }
        }
        if (clients.openWindow) return clients.openWindow(url)
      })
  )
})

self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') self.skipWaiting()
})