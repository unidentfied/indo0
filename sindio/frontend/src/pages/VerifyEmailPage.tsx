import { useState, useEffect } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { CheckCircle, XCircle, Loader2 } from 'lucide-react'

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading')
  const [message, setMessage] = useState('Verifying your email...')

  useEffect(() => {
    const token = searchParams.get('token')
    if (!token) {
      setStatus('error')
      setMessage('No verification token provided. Please use the link from your email.')
      return
    }

    const base = (import.meta as any).env?.VITE_API_BASE_URL || ''
    fetch(`${base}/auth/verify-email/${encodeURIComponent(token)}`)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: 'Verification failed' }))
          throw new Error(body.detail || 'Verification failed')
        }
        const body = await res.json()
        setStatus('success')
        setMessage(body.detail || 'Email verified successfully')
      })
      .catch((err) => {
        setStatus('error')
        setMessage(err.message || 'Verification failed. The link may have expired.')
      })
  }, [searchParams])

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 bg-sindio-dark text-sindio-text text-center border-l border-sindio-border">
      <div className={`w-20 h-20 rounded-2xl border flex items-center justify-center mb-6 shadow-xl ${
        status === 'success' ? 'bg-sindio-panel border-green-500/30 shadow-green-500/10' :
        status === 'error' ? 'bg-sindio-panel border-red-500/30 shadow-red-500/10' :
        'bg-sindio-panel border-sindio-border shadow-sindio-accent/10'
      }`}>
        {status === 'loading' && <Loader2 className="w-10 h-10 text-sindio-accent animate-spin" />}
        {status === 'success' && <CheckCircle className="w-10 h-10 text-green-400" />}
        {status === 'error' && <XCircle className="w-10 h-10 text-red-400" />}
      </div>

      <h1 className="text-2xl font-bold mb-2">
        {status === 'loading' ? 'Verifying Email' : status === 'success' ? 'Email Verified' : 'Verification Failed'}
      </h1>
      <p className="text-sindio-muted max-w-sm mx-auto leading-relaxed mb-8">{message}</p>

      <div className="flex gap-4">
        {status === 'success' && (
          <button
            className="btn-primary"
            onClick={() => {
              const modal = document.querySelector('[data-auth-trigger]') as HTMLElement | null
              modal?.click()
            }}
          >
            Sign In
          </button>
        )}
        <Link to="/" className="btn-primary">
          Return Home
        </Link>
      </div>
    </div>
  )
}
