/**
 * Service worker registration.
 *
 * Registers sw.js and listens for BackgroundSync success messages from
 * the service worker.  Dispatches a custom DOM event so components can
 * react to sync completions.
 */

let _registration: ServiceWorkerRegistration | null = null

export async function registerServiceWorker(): Promise<void> {
  if (!('serviceWorker' in navigator)) return

  // Automatically unregister service worker on localhost to prevent caching issues in development
  if (typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')) {
    try {
      const registrations = await navigator.serviceWorker.getRegistrations()
      for (const registration of registrations) {
        await registration.unregister()
        console.log('[sw] Unregistered service worker on localhost to bypass dev cache')
      }
    } catch (err) {
      console.warn('[sw] Failed to unregister service worker:', err)
    }
    return
  }

  try {
    _registration = await navigator.serviceWorker.register('/sw.js', {
      scope: '/',
      updateViaCache: 'none',
    })
    console.log('[sw] Registered — scope:', _registration.scope)

    _registration.addEventListener('updatefound', () => {
      const installing = _registration?.installing
      if (installing) {
        installing.addEventListener('statechange', () => {
          if (installing.state === 'installed' && navigator.serviceWorker.controller) {
            console.log('[sw] Update available — refresh to activate.')
          }
        })
      }
    })
  } catch (err) {
    console.warn('[sw] Registration failed:', err)
  }

  // Listen for BG_SYNC_SUCCESS messages from the service worker
  navigator.serviceWorker.addEventListener('message', (event) => {
    if (event.data?.type === 'BG_SYNC_SUCCESS') {
      window.dispatchEvent(
        new CustomEvent('sindio-bg-sync-success', {
          detail: { taskId: event.data.taskId },
        }),
      )
    }
  })
}

export function getSWRegistration(): ServiceWorkerRegistration | null {
  return _registration
}

/**
 * Return true if the browser is currently online.  React components
 * should combine this with the `online` / `offline` event for live updates.
 */
export function isOnline(): boolean {
  return typeof navigator !== 'undefined' && navigator.onLine
}
