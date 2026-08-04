import React, { useState, useMemo, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { Eye, EyeOff } from 'lucide-react'

interface AuthModalProps {
  onClose: () => void
  initialMode?: 'signin' | 'signup'
}

function passwordStrength(pw: string): { score: number; label: string } {
  let score = 0
  if (pw.length >= 8) score++
  if (pw.length >= 12) score++
  if (/[A-Z]/.test(pw)) score++
  if (/[0-9]/.test(pw)) score++
  if (/[^A-Za-z0-9]/.test(pw)) score++
  if (score <= 1) return { score, label: 'Weak' }
  if (score <= 3) return { score, label: 'Fair' }
  if (score <= 4) return { score, label: 'Strong' }
  return { score, label: 'Very Strong' }
}

export default function AuthModal({ onClose, initialMode = 'signin' }: AuthModalProps) {
  const { login, signup, isAuthenticated } = useAuth()
  const [mode, setMode] = useState<'signin' | 'signup'>(initialMode)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [termsAccepted, setTermsAccepted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [verificationSent, setVerificationSent] = useState(false)

  useEffect(() => {
    if (isAuthenticated) onClose()
  }, [isAuthenticated, onClose])

  const strength = useMemo(() => passwordStrength(password), [password])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (mode === 'signup' && !termsAccepted) {
      setError('You must accept the Terms & Conditions and Privacy Policy.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      if (mode === 'signin') {
        await login(email, password)
      } else {
        const autoVerified = await signup(name, email, password)
        if (!autoVerified) {
          setVerificationSent(true)
        }
      }
    } catch (err: any) {
      setError(err?.message ?? `${mode === 'signin' ? 'Sign in' : 'Sign up'} failed`)
    } finally {
      setLoading(false)
    }
  }

  const handleClose = () => {
    if (!loading) onClose()
  }

  const switchMode = () => {
    setError(null)
    setMode(mode === 'signin' ? 'signup' : 'signin')
    setTermsAccepted(false)
  }

  const strengthColors: Record<string, string> = {
    'Weak': 'bg-red-500',
    'Fair': 'bg-yellow-500',
    'Strong': 'bg-green-500',
    'Very Strong': 'bg-green-600',
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-20 bg-black/60 backdrop-blur-sm">
      <div className="bg-sindio-panel rounded-xl shadow-xl w-full max-w-md mx-4 p-6 relative max-h-[90vh] overflow-y-auto">
        <button
          type="button"
          className="absolute top-3 right-3 text-sindio-muted hover:text-sindio-accent"
          onClick={handleClose}
          disabled={loading}
        >
          ✕
        </button>

        {verificationSent ? (
          <div className="text-center">
            <h2 className="text-xl font-semibold mb-4 text-sindio-accent">
              Check your email!
            </h2>
            <p className="text-sindio-muted mb-6">
              A verification link has been sent to <strong>{email}</strong>.
            </p>
            <button type="button" className="btn-primary w-full" onClick={handleClose}>
              Close
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <h2 className="text-2xl font-bold mb-1 text-sindio-accent">
              {mode === 'signin' ? 'Sign in' : 'Create your account'}
            </h2>
            <p className="text-sm text-sindio-muted mb-6">
              {mode === 'signin'
                ? 'Access your Sindio dashboard'
                : 'Start your 14-day free trial'}
            </p>

            {error && (
              <div className="bg-red-900/30 border border-red-500/50 text-red-300 p-3 rounded mb-4 text-sm">
                {error}
              </div>
            )}

            {mode === 'signup' && (
              <div className="mb-4">
                <label htmlFor="auth-name" className="block text-sm font-medium text-sindio-muted mb-1">
                  Full Name
                </label>
                <input
                  id="auth-name"
                  type="text"
                  autoComplete="name"
                  className="w-full px-3 py-2 border border-sindio-border rounded bg-sindio-dark text-sindio-text focus:outline-none focus:border-sindio-accent focus:ring-1 focus:ring-sindio-accent transition"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={loading}
                  placeholder="Your name"
                />
              </div>
            )}

            <div className="mb-4">
              <label htmlFor="auth-email" className="block text-sm font-medium text-sindio-muted mb-1">
                Email
              </label>
              <input
                id="auth-email"
                type="email"
                required
                autoComplete="email"
                className="w-full px-3 py-2 border border-sindio-border rounded bg-sindio-dark text-sindio-text focus:outline-none focus:border-sindio-accent focus:ring-1 focus:ring-sindio-accent transition"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={loading}
              />
            </div>

            <div className="mb-1">
              <label htmlFor="auth-password" className="block text-sm font-medium text-sindio-muted mb-1">
                Password
              </label>
              <div className="relative">
                <input
                  id="auth-password"
                  type={showPassword ? 'text' : 'password'}
                  required
                  minLength={8}
                  className="w-full px-3 py-2 pr-10 border border-sindio-border rounded bg-sindio-dark text-sindio-text focus:outline-none focus:border-sindio-accent transition"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={loading}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-sindio-muted hover:text-white"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {mode === 'signup' && password.length > 0 && (
              <div className="mb-4">
                <div className="flex gap-1 mb-1">
                  {[1, 2, 3, 4, 5].map(i => (
                    <div
                      key={i}
                      className={`h-1 flex-1 rounded ${i <= strength.score ? strengthColors[strength.label] || 'bg-green-500' : 'bg-sindio-border'}`}
                    />
                  ))}
                </div>
                <p className="text-xs text-sindio-muted">Password strength: <span className="font-medium">{strength.label}</span></p>
              </div>
            )}

            {mode === 'signup' && (
              <div className="mb-4">
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={termsAccepted}
                    onChange={(e) => setTermsAccepted(e.target.checked)}
                    className="mt-1 accent-sindio-accent"
                    disabled={loading}
                  />
                  <span className="text-xs text-sindio-muted leading-relaxed">
                    I agree to the{' '}
                    <a href="/terms" target="_blank" rel="noopener noreferrer" className="text-sindio-accent hover:underline">Terms & Conditions</a>
                    {' '}and{' '}
                    <a href="/privacy" target="_blank" rel="noopener noreferrer" className="text-sindio-accent hover:underline">Privacy Policy</a>
                  </span>
                </label>
              </div>
            )}

            <button
              type="submit"
              className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50"
              disabled={loading || (mode === 'signup' && !termsAccepted)}
            >
              {loading
                ? (mode === 'signin' ? 'Signing in…' : 'Creating account…')
                : (mode === 'signin' ? 'Sign in' : 'Create Account')
              }
            </button>

            <p className="text-center text-sm text-sindio-muted mt-4">
              {mode === 'signin' ? "Don't have an account?" : 'Already have an account?'}{' '}
              <button
                type="button"
                onClick={switchMode}
                className="text-sindio-accent hover:underline font-medium"
                disabled={loading}
              >
                {mode === 'signin' ? 'Sign up' : 'Sign in'}
              </button>
            </p>
          </form>
        )}
      </div>
    </div>
  )
}
