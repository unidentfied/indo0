import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'

interface UserPayload {
  sub: string
  email?: string
  is_paid?: boolean
  is_trial?: boolean
  trial_expires_at?: string
  exp?: number
}

interface AuthState {
  token: string | null
  user: UserPayload | null
  isAuthenticated: boolean
  isLoading: boolean
}

interface AuthContextType extends AuthState {
  login: (email: string, password: string) => Promise<void>
  signup: (email: string, password: string) => Promise<void>
  logout: () => void
  hasActiveSubscription: boolean
}

const AuthContext = createContext<AuthContextType | null>(null)

function parseJwt(token: string): UserPayload | null {
  try {
    const base64 = token.split('.')[1]
    const json = atob(base64)
    return JSON.parse(json)
  } catch {
    return null
  }
}

const TOKEN_KEY = 'sindio_token'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    token: null,
    user: null,
    isAuthenticated: false,
    isLoading: true,
  })

  useEffect(() => {
    const stored = localStorage.getItem(TOKEN_KEY)
    if (stored) {
      const user = parseJwt(stored)
      if (user && user.exp ? (user.exp * 1000) > Date.now() : true) {
        setState({ token: stored, user, isAuthenticated: true, isLoading: false })
        return
      }
      localStorage.removeItem(TOKEN_KEY)
    }
    setState(s => ({ ...s, isLoading: false }))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const res = await fetch(`${(import.meta as any).env?.VITE_API_BASE_URL || ''}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) {
      const body = await res.text()
      throw new Error(body || 'Login failed')
    }
    const data = await res.json()
    localStorage.setItem(TOKEN_KEY, data.access_token)
    const user = parseJwt(data.access_token)
    setState({ token: data.access_token, user, isAuthenticated: true, isLoading: false })
  }, [])

  const signup = useCallback(async (email: string, password: string) => {
    const res = await fetch(`${(import.meta as any).env?.VITE_API_BASE_URL || ''}/auth/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) {
      const body = await res.text()
      throw new Error(body || 'Signup failed')
    }
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setState({ token: null, user: null, isAuthenticated: false, isLoading: false })
  }, [])

  const hasActiveSubscription = Boolean(
    state.user?.is_paid ||
    (state.user?.is_trial && state.user?.trial_expires_at && new Date(state.user.trial_expires_at) > new Date())
  )

  return (
    <AuthContext.Provider value={{ ...state, login, signup, logout, hasActiveSubscription }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
