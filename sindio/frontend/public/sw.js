const CACHE_VERSION = 'sindio-v2'
const CACHE_NAME = `sindio-${CACHE_VERSION}`
const OFFLINE_QUEUE = 'sindio-offline-queue'

const PRECACHE_URLS = [
  '/',
  '/dashboard',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return
  if (event.request.url.includes('/api/')) return

  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone()
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone))
          }
          return response
        })
        .catch(() => cached || new Response('Offline', { status: 503 }))
      return cached || fetchPromise
    })
  )
})

self.addEventListener('sync', (event) => {
  if (event.tag === 'bg-sync-simulations') {
    event.waitUntil(processOfflineQueue())
  }
})

async function processOfflineQueue() {
  const db = await openDB()
  const tx = db.transaction(OFFLINE_QUEUE, 'readwrite')
  const store = tx.objectStore(OFFLINE_QUEUE)
  const tasks = await store.getAll()

  for (const task of tasks) {
    try {
      const response = await fetch('/api/v1/simulate/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(task.payload),
      })
      if (response.ok) {
        await store.delete(task.id)
        self.clients.matchAll().then((clients) => {
          clients.forEach((client) => {
            client.postMessage({ type: 'BG_SYNC_SUCCESS', taskId: task.id })
          })
        })
      }
    } catch {
      break
    }
  }
}

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(OFFLINE_QUEUE, 1)
    request.onupgradeneeded = () => {
      request.result.createObjectStore(OFFLINE_QUEUE, { keyPath: 'id' })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}
