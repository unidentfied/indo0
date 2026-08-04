import { Link } from 'react-router-dom'
import { useState } from 'react'
import { Map } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import AuthModal from './AuthModal'

const resources = [
  { label: 'Privacy Policy', href: '/privacy' },
  { label: 'Cookie Policy', href: '/cookies' },
  { label: 'Terms & Conditions', href: '/terms' },
]

const company = [
  { label: 'People', href: '/people' },
  { label: 'FAQ', href: '/faq' },
]

export default function Footer() {
  const { isAuthenticated } = useAuth()
  const [showAuth, setShowAuth] = useState(false)

  const platformLinks = [
    { label: 'Infrastructure Types', href: '/dashboard' },
    { label: 'Simulation Dashboard', href: '/dashboard' },
    { label: 'Alert Feed', href: '/dashboard?system=alerts' },
  ]

  return (
    <footer className="border-t border-sindio-border bg-sindio-panel">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-10">
          <div>
            <Link to="/" className="inline-flex items-center gap-2 mb-4">
              <Map className="w-5 h-5 text-sindio-accent" />
              <span className="text-lg font-bold text-sindio-accent">Sindio</span>
            </Link>
            <p className="text-sindio-muted text-sm leading-relaxed max-w-xs">
              Predictive infrastructure modelling and stress monitoring aimed at Nairobi. Eight systems, one unified pipeline.
            </p>
          </div>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-sindio-muted mb-5">Resources</h4>
            <ul className="space-y-3">
              {resources.map(r => (
                <li key={r.label}>
                  <Link to={r.href} className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">
                    {r.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-sindio-muted mb-5">Company</h4>
            <ul className="space-y-3">
              {company.map(c => (
                <li key={c.label}>
                  <Link to={c.href} className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">
                    {c.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-sindio-muted mb-5">Platform</h4>
            <ul className="space-y-3">
              {platformLinks.map(pl => (
                <li key={pl.label}>
                  {isAuthenticated ? (
                    <Link to={pl.href} className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">
                      {pl.label}
                    </Link>
                  ) : (
                    <button
                      onClick={() => setShowAuth(true)}
                      className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors"
                    >
                      {pl.label}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="mt-16 pt-8 border-t border-sindio-border text-xs text-sindio-muted text-left">
          COPYRIGHT &copy; 2026 SINDIO.NET ALL RIGHTS RESERVED.
        </div>
      </div>

      {showAuth && <AuthModal onClose={() => setShowAuth(false)} />}
    </footer>
  )
}
