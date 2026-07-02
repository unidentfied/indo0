import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'

interface BackendStatus {
  healthy: boolean
  checked: boolean
  lastError: string | null
}

const BackendStatusContext = createContext<BackendStatus>({ healthy: true, checked: false, lastError: null })

export function useBackendStatus() {
  return useContext(BackendStatusContext)
}

const HEALTH_INTERVAL = 30000

export function BackendStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BackendStatus>({ healthy: true, checked: false, lastError: null })

  const check = useCallback(async () => {
    try {
      const res = await fetch('/health', { signal: AbortSignal.timeout(5000) })
      const body = await res.json().catch(() => ({}))
      const healthy = res.ok && (body.status === 'ok' || body.status === 'ready' || body.status === 'degraded')
      setStatus({
        healthy,
        checked: true,
        lastError: healthy ? null : (body.status || `HTTP ${res.status}`),
      })
    } catch (err) {
      setStatus({
        healthy: false,
        checked: true,
        lastError: err instanceof Error ? err.message : 'Backend unreachable',
      })
    }
  }, [])

  useEffect(() => {
    check()
    const id = setInterval(check, HEALTH_INTERVAL)
    return () => clearInterval(id)
  }, [check])

  return (
    <BackendStatusContext.Provider value={status}>
      {children}
    </BackendStatusContext.Provider>
  )
}
