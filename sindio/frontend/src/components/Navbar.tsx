import { Link, useLocation } from 'react-router-dom'
import { Menu, X, Sun, Moon, Maximize, Minimize, LogOut } from 'lucide-react'
import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import AuthModal from './AuthModal'

function prefetchDashboard() {
  import('../pages/Dashboard')
}

function readStoredTheme(): 'dark' | 'light' {
  try {
    const stored = window.localStorage?.getItem('theme')
    if (stored === 'dark' || stored === 'light') return stored
  } catch {
    // ignore storage failures
  }
  return prefersDarkMode() ? 'dark' : 'light'
}

function prefersDarkMode(): boolean {
  try {
    return window.matchMedia?.('(prefers-color-scheme: dark)')?.matches ?? false
  } catch {
    return false
  }
}

const TABS: { label: string; system: string }[] = [
  { label: 'Power',      system: 'power' },
  { label: 'Water',      system: 'water' },
  { label: 'Roads',      system: 'roads' },
  { label: 'Solid Waste', system: 'solid_waste' },
  { label: 'Sidewalks',  system: 'sidewalks' },
  { label: 'LRT',        system: 'lrt' },
  { label: 'SGR',        system: 'sgr' },
  { label: 'Airports',   system: 'airports' },
  { label: 'Alerts',     system: 'alerts' },
]

export default function Navbar() {
  const location = useLocation()
  const { isAuthenticated, logout } = useAuth()
  const isDash = location.pathname.startsWith('/dashboard')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [showAuth, setShowAuth] = useState(false)
  const [dark, setDark] = useState(() => readStoredTheme() === 'dark')

  useEffect(() => {
    if (dark) {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
    try {
      window.localStorage?.setItem('theme', dark ? 'dark' : 'light')
    } catch {
      // ignore
    }
  }, [dark])

  const [fullscreen, setFullscreen] = useState(false)

  useEffect(() => {
    const handler = () => setFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', handler)
    return () => document.removeEventListener('fullscreenchange', handler)
  }, [])

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      document.exitFullscreen()
    } else {
      document.documentElement.requestFullscreen()
    }
  }, [])

  return (
    <nav className="border-b border-sindio-border dark:border-slate-800 bg-sindio-panel/90 dark:bg-slate-950/90 backdrop-blur sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-8">
            <Link to="/" className="text-xl font-bold tracking-tight text-sindio-accent">
              Sindio
            </Link>
            {isDash && isAuthenticated && (
              <div className="hidden md:flex items-center gap-6 text-sm text-sindio-muted dark:text-slate-400">
                {TABS.map((t) => (
                  <Link
                    key={t.system}
                    to={`/dashboard?system=${t.system}`}
                    className="hover:text-sindio-text dark:hover:text-slate-200 transition-colors"
                  >
                    {t.label}
                  </Link>
                ))}
              </div>
            )}
          </div>

          <div className="hidden md:flex items-center gap-3">
            <button
              onClick={() => setDark(!dark)}
              className="p-2 rounded-lg text-sindio-muted dark:text-slate-400 hover:text-sindio-text dark:hover:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
              title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
            <button
              onClick={toggleFullscreen}
              className="p-2 rounded-lg text-sindio-muted dark:text-slate-400 hover:text-sindio-text dark:hover:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
              title={fullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
            >
              {fullscreen ? <Minimize className="w-4 h-4" /> : <Maximize className="w-4 h-4" />}
            </button>

            {isAuthenticated ? (
              <Link to="/dashboard" className="btn-primary text-sm" onMouseEnter={prefetchDashboard}>
                Launch Dashboard
              </Link>
            ) : (
              <button onClick={() => setShowAuth(true)} className="btn-primary text-sm">
                Sign In
              </button>
            )}
          </div>

          <button className="md:hidden p-2" onClick={() => setMobileOpen(!mobileOpen)}>
            {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {showAuth && <AuthModal onClose={() => setShowAuth(false)} />}

      {mobileOpen && (
        <div className="md:hidden border-t border-sindio-border dark:border-slate-800 px-4 py-4 space-y-3">
          {isDash && isAuthenticated && TABS.map((t) => (
            <Link
              key={t.system}
              to={`/dashboard?system=${t.system}`}
              onClick={() => setMobileOpen(false)}
              className="block text-sindio-muted dark:text-slate-400 hover:text-sindio-text dark:hover:text-slate-200"
            >
              {t.label}
            </Link>
          ))}
          <button
            onClick={() => { setDark(!dark); setMobileOpen(false); }}
            className="flex items-center gap-2 text-sm text-sindio-muted dark:text-slate-400 hover:text-sindio-text dark:hover:text-slate-200"
          >
            {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            {dark ? 'Light Mode' : 'Dark Mode'}
          </button>
          <button
            onClick={() => { toggleFullscreen(); setMobileOpen(false); }}
            className="flex items-center gap-2 text-sm text-sindio-muted dark:text-slate-400 hover:text-sindio-text dark:hover:text-slate-200"
          >
            {fullscreen ? <Minimize className="w-4 h-4" /> : <Maximize className="w-4 h-4" />}
            {fullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
          </button>
          {isAuthenticated ? (
            <button
              onClick={() => { logout(); setMobileOpen(false); }}
              className="flex items-center gap-2 text-sm text-red-400 hover:text-red-300"
            >
              <LogOut className="w-4 h-4" />
              Sign Out
            </button>
          ) : (
            <button onClick={() => { setShowAuth(true); setMobileOpen(false); }} className="btn-primary w-full justify-center">
              Sign In
            </button>
          )}
          {isAuthenticated ? (
            <Link to="/dashboard" className="btn-primary w-full justify-center mt-2" onMouseEnter={prefetchDashboard} onClick={() => setMobileOpen(false)}>
              Launch Dashboard
            </Link>
          ) : (
            <button onClick={() => { setShowAuth(true); setMobileOpen(false); }} className="btn-primary w-full justify-center mt-2">
              Launch Dashboard
            </button>
          )}
        </div>
      )}
    </nav>
  )
}
