import { Link, useLocation } from 'react-router-dom'
import { Menu, X, Sun, Moon, Maximize, Minimize } from 'lucide-react'
import { useState, useEffect, useCallback } from 'react'

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
  const isDash = location.pathname.startsWith('/dashboard')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [dark, setDark] = useState(() => {
    const stored = localStorage.getItem('theme')
    if (stored) return stored === 'dark'
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })

  useEffect(() => {
    if (dark) {
      document.documentElement.classList.add('dark')
      localStorage.setItem('theme', 'dark')
    } else {
      document.documentElement.classList.remove('dark')
      localStorage.setItem('theme', 'light')
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
            {isDash && (
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
            <Link to="/dashboard" className="btn-primary text-sm">
              Launch Dashboard
            </Link>
          </div>

          <button className="md:hidden p-2" onClick={() => setMobileOpen(!mobileOpen)}>
            {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {mobileOpen && (
        <div className="md:hidden border-t border-sindio-border dark:border-slate-800 px-4 py-4 space-y-3">
          {TABS.map((t) => (
            <Link
              key={t.system}
              to={`/dashboard?system=${t.system}`}
              className="block text-sindio-muted dark:text-slate-400 hover:text-sindio-text dark:hover:text-slate-200"
            >
              {t.label}
            </Link>
          ))}
          <button
            onClick={() => setDark(!dark)}
            className="flex items-center gap-2 text-sm text-sindio-muted dark:text-slate-400 hover:text-sindio-text dark:hover:text-slate-200"
          >
            {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            {dark ? 'Light Mode' : 'Dark Mode'}
          </button>
          <button
            onClick={toggleFullscreen}
            className="flex items-center gap-2 text-sm text-sindio-muted dark:text-slate-400 hover:text-sindio-text dark:hover:text-slate-200"
          >
            {fullscreen ? <Minimize className="w-4 h-4" /> : <Maximize className="w-4 h-4" />}
            {fullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
          </button>
          <Link to="/dashboard" className="btn-primary w-full justify-center mt-2">
            Launch Dashboard
          </Link>
        </div>
      )}
    </nav>
  )
}
