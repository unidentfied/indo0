import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'

interface UserPayload {
  sub: string
  email?: string
  name?: string | null
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
  signup: (name: string, email: string, password: string) => Promise<{ verified: boolean; verificationEmailSent: boolean }>
  resendVerification: (email: string) => Promise<void>
  logout: () => void
  deleteAccount: () => Promise<void>
  hasActiveSubscription: boolean
}

const AuthContext = createContext<AuthContextType | null>(null)

function parseJwt(token: string): UserPayload | null {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
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
      if (user && typeof user.exp === 'number' && (user.exp * 1000) > Date.now()) {
        setState({ token: stored, user, isAuthenticated: true, isLoading: false })
        return
      }
      localStorage.removeItem(TOKEN_KEY)
    }
    setState(s => ({ ...s, isLoading: false }))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    let res: Response
    try {
      res = await fetch(`${(import.meta as any).env?.VITE_API_BASE_URL || ''}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
    } catch {
      throw new Error('Unable to reach the server. Please check your connection and try again.')
    }
    if (!res.ok) {
      let detail = 'Login failed'
      try {
        const body = JSON.parse(await res.text())
        detail = body.detail || detail
      } catch {}
      throw new Error(detail)
    }
    const data = await res.json()
    localStorage.setItem(TOKEN_KEY, data.access_token)
    const user = parseJwt(data.access_token)
    setState({ token: data.access_token, user, isAuthenticated: true, isLoading: false })
  }, [])

  const signup = useCallback(async (name: string, email: string, password: string) => {
    let res: Response
    try {
      res = await fetch(`${(import.meta as any).env?.VITE_API_BASE_URL || ''}/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password }),
      })
    } catch {
      throw new Error('Unable to reach the server. Please check your connection and try again.')
    }
    if (!res.ok) {
      let detail = 'Signup failed'
      try {
        const body = JSON.parse(await res.text())
        detail = body.detail || detail
      } catch {}
      throw new Error(detail)
    }
    const data = await res.json()
    const verified = !!data.verified
    if (verified && data.access_token) {
      localStorage.setItem(TOKEN_KEY, data.access_token)
      const user = parseJwt(data.access_token)
      setState({ token: data.access_token, user, isAuthenticated: true, isLoading: false })
    }
    return { verified, verificationEmailSent: !!data.verification_email_sent }
  }, [])

  const resendVerification = useCallback(async (email: string) => {
    let res: Response
    try {
      res = await fetch(`${(import.meta as any).env?.VITE_API_BASE_URL || ''}/auth/resend-verification`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
    } catch {
      throw new Error('Unable to reach the server. Please check your connection and try again.')
    }
    if (!res.ok) {
      let detail = 'Failed to resend verification email'
      try {
        const body = JSON.parse(await res.text())
        detail = body.detail || detail
      } catch {}
      throw new Error(detail)
    }
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setState({ token: null, user: null, isAuthenticated: false, isLoading: false })
  }, [])

  const deleteAccount = useCallback(async () => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) throw new Error('Not authenticated')
    const res = await fetch(`${(import.meta as any).env?.VITE_API_BASE_URL || ''}/auth/account`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    })
    if (!res.ok) {
      let detail = 'Failed to delete account'
      try { const body = JSON.parse(await res.text()); detail = body.detail || detail } catch {}
      throw new Error(detail)
    }
    localStorage.removeItem(TOKEN_KEY)
    setState({ token: null, user: null, isAuthenticated: false, isLoading: false })
  }, [])

  const hasActiveSubscription = Boolean(
    state.user?.is_paid ||
    (state.user?.is_trial && state.user?.trial_expires_at && new Date(state.user.trial_expires_at) > new Date())
  )

  return (
    <AuthContext.Provider value={{ ...state, login, signup, resendVerification, logout, deleteAccount, hasActiveSubscription }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
