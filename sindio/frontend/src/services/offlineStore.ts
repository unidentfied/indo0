/**
 * IndexedDB helper for offline simulation requests.
 *
 * When the user triggers a simulation while offline the request payload is
 * stored in `sindio-offline` / `pending-simulations`.  On reconnect the
 * service worker replays the request via BackgroundSync and clears the entry.
 * Until replayed, the UI shows a "Will run when online" banner.
 */

export interface PendingSimulation {
  id: string
  payload: {
    infrastructure_type: string
    stress_factor: string
    parameters?: Record<string, unknown>
  }
  queuedAt: string
}

const DB_NAME = 'sindio-offline'
const DB_VERSION = 1
const STORE_NAME = 'pending-simulations'

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

export async function enqueueSimulation(
  id: string,
  payload: PendingSimulation['payload'],
): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    tx.objectStore(STORE_NAME).put({
      id,
      payload,
      queuedAt: new Date().toISOString(),
    })
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

export async function getPendingSimulations(): Promise<PendingSimulation[]> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly')
    const req = tx.objectStore(STORE_NAME).getAll()
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

export async function removeSimulation(id: string): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    tx.objectStore(STORE_NAME).delete(id)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

export async function clearAllPending(): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    tx.objectStore(STORE_NAME).clear()
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

/**
 * Return true if `indexedDB` is available (it is in all modern browsers
 * including when in a service worker context).
 */
export function isOfflineStorageAvailable(): boolean {
  return typeof indexedDB !== 'undefined'
}
