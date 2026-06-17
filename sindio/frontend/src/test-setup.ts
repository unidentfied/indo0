import '@testing-library/jest-dom'

const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { store = {} },
  }
})()

Object.defineProperty(window, 'localStorage', { value: localStorageMock, writable: true })

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
})

// Robust Mock for indexedDB used in tests
class MockIDBRequest extends EventTarget {
  result: any = null
  error: any = null
  onsuccess: any = null
  onerror: any = null
  onupgradeneeded: any = null
}

class MockIDBTransaction extends EventTarget {
  oncomplete: any = null
  onerror: any = null
  objectStore() {
    return {
      put: () => ({}),
      getAll: () => {
        const req = new MockIDBRequest()
        setTimeout(() => {
          req.result = []
          if (req.onsuccess) req.onsuccess()
        }, 0)
        return req
      },
      delete: () => ({}),
      clear: () => ({}),
    }
  }
}

class MockIDBDatabase extends EventTarget {
  objectStoreNames = {
    contains: () => true,
  }
  createObjectStore() {}
  transaction() {
    const tx = new MockIDBTransaction()
    setTimeout(() => {
      if (tx.oncomplete) tx.oncomplete()
    }, 0)
    return tx
  }
}

const mockIndexedDB = {
  open: () => {
    const req = new MockIDBRequest()
    setTimeout(() => {
      req.result = new MockIDBDatabase()
      if (req.onsuccess) req.onsuccess()
    }, 0)
    return req
  },
}

Object.defineProperty(window, 'indexedDB', {
  value: mockIndexedDB,
  writable: true,
})
Object.defineProperty(global, 'indexedDB', {
  value: mockIndexedDB,
  writable: true,
})
Object.defineProperty(globalThis, 'indexedDB', {
  value: mockIndexedDB,
  writable: true,
})

const mockFetch = (url: string) => {
  console.log("MOCK FETCH CALLED FOR URL:", url)
  let responseData: any = []
  if (url.includes('/api/infrastructure/')) {
    responseData = {
      grid_stability: 98,
      current_load: 'Medium',
      active_nodes: 12000,
    }
  }
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(responseData),
  })
}

Object.defineProperty(window, 'fetch', {
  value: mockFetch,
  writable: true,
})
if (typeof global !== 'undefined') {
  Object.defineProperty(global, 'fetch', {
    value: mockFetch,
    writable: true,
  })
}
Object.defineProperty(globalThis, 'fetch', {
  value: mockFetch,
  writable: true,
})
