import { Link } from 'react-router-dom'
import { useState, useMemo } from 'react'
import {
  Droplet, Zap, Route, Recycle, Footprints, TrainFront, Train, Plane,
  BellRing, BookOpen, User, LogOut, Trash2, AlertTriangle, ChevronDown, ChevronUp,
  Clock, Crown,
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

const TRIAL_DAYS = 14

const menuItems = [
  { icon: Zap, label: 'Power Systems', id: 'power' },
  { icon: Droplet, label: 'Water Grid', id: 'water' },
  { icon: Route, label: 'Road Networks', id: 'roads' },
  { icon: Recycle, label: 'Solid Waste', id: 'solid_waste' },
  { icon: Footprints, label: 'Sidewalks', id: 'sidewalks' },
  { icon: TrainFront, label: 'LRT Trains', id: 'lrt' },
  { icon: Train, label: 'SGR Trains', id: 'sgr' },
  { icon: Plane, label: 'Airports', id: 'airports' },
]

interface SidebarProps {
  activeSystem: string
  onSelect: (id: string) => void
}

export default function Sidebar({ activeSystem, onSelect }: SidebarProps) {
  const { user, logout, deleteAccount } = useAuth()
  const [profileOpen, setProfileOpen] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const displayName = user?.name || user?.email || user?.sub || 'User'
  const displayEmail = user?.email || user?.sub || ''

  const trialStatus = useMemo(() => {
    if (!user) return null
    if (user.is_paid) return { variant: 'paid' as const, label: 'Subscriber', textColor: 'text-green-300', barColor: 'bg-green-500', icon: Crown, iconBg: 'bg-green-500/20' }
    if (user.is_trial && user.trial_expires_at) {
      const now = new Date()
      const end = new Date(user.trial_expires_at)
      const total = end.getTime() - new Date(new Date(end).setDate(new Date(end).getDate() - TRIAL_DAYS)).getTime()
      const remaining = Math.max(0, end.getTime() - now.getTime())
      const pct = Math.floor((remaining / total) * 100)
      const days = Math.ceil(remaining / (1000 * 60 * 60 * 24))
      if (remaining <= 0) return { variant: 'expired' as const, label: 'Trial expired', pct: 0, days: 0, textColor: 'text-red-400', barColor: 'bg-red-500', icon: AlertTriangle, iconBg: 'bg-red-500/20' }
      if (days <= 3) return { variant: 'warning' as const, label: `${days}d remaining`, pct, days, textColor: 'text-yellow-300', barColor: 'bg-yellow-500', icon: Clock, iconBg: 'bg-yellow-500/20' }
      return { variant: 'active' as const, label: `${days}d remaining`, pct, days, textColor: 'text-sindio-accent', barColor: 'bg-sindio-accent', icon: Clock, iconBg: 'bg-sindio-accent/20' }
    }
    return null
  }, [user])

  const handleDeleteAccount = async () => {
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteAccount()
    } catch (err: any) {
      setDeleteError(err?.message ?? 'Failed to delete account')
      setDeleting(false)
      setShowDeleteConfirm(false)
    }
  }
  return (
    <aside className="w-64 border-r border-sindio-border bg-sindio-panel hidden lg:flex flex-col">
      <div className="p-6 border-b border-sindio-border">
        <div className="text-xs text-sindio-muted uppercase tracking-wider font-medium mb-1">Project Nairobi</div>
        <div className="font-semibold text-sindio-text">Central District</div>
      </div>

      <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
        <div className="text-[10px] uppercase text-sindio-muted tracking-wider font-semibold px-3 mb-2 mt-2">
          Infrastructure
        </div>
        {menuItems.map((item) => {
          const isActive = activeSystem === item.id
          return (
            <button
              key={item.id}
              onClick={() => onSelect(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left border-l-2 ${
                isActive
                  ? 'bg-sindio-accent/10 text-sindio-accent font-medium border-l-sindio-accent'
                  : 'text-sindio-muted hover:text-sindio-text hover:bg-sindio-border/50 border-l-transparent'
              }`}
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </button>
          )
        })}

        <div className="text-[10px] uppercase text-sindio-muted tracking-wider font-semibold px-3 mb-2 mt-6">
          Monitoring
        </div>
        <button
          onClick={() => onSelect('alerts')}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left border-l-2 ${
            activeSystem === 'alerts'
              ? 'bg-sindio-accent/10 text-sindio-accent font-medium border-l-sindio-accent'
              : 'text-sindio-muted hover:text-sindio-text hover:bg-sindio-border/50 border-l-transparent'
          }`}
        >
          <BellRing className="w-4 h-4" />
          Alert Feed
        </button>
      </nav>

      <div className="p-4 border-t border-sindio-border space-y-1">
        <Link to="/dashboard?system=alerts" className="flex items-center gap-3 px-3 py-2 text-sm text-sindio-muted hover:text-sindio-text hover:bg-sindio-border/50 rounded-lg transition-colors">
          <BellRing className="w-4 h-4" />
          Alerts History
        </Link>
        <Link to="/" className="flex items-center gap-3 px-3 py-2 text-sm text-sindio-muted hover:text-sindio-text hover:bg-sindio-border/50 rounded-lg transition-colors">
          <BookOpen className="w-4 h-4" />
          Documentation
        </Link>
      </div>

      <div className="border-t border-sindio-border">
        <button
          onClick={() => setProfileOpen(!profileOpen)}
          className="w-full flex items-center gap-3 p-4 text-sm hover:bg-sindio-border/20 transition-colors"
        >
          <div className="w-8 h-8 rounded-full bg-sindio-accent/20 border border-sindio-accent/30 flex items-center justify-center shrink-0">
            <User className="w-4 h-4 text-sindio-accent" />
          </div>
          <div className="flex-1 text-left min-w-0">
            <div className="font-medium text-sindio-text truncate">{displayName}</div>
            <div className="text-xs text-sindio-muted truncate">{displayEmail}</div>
          </div>
          {profileOpen ? <ChevronUp className="w-4 h-4 text-sindio-muted shrink-0" /> : <ChevronDown className="w-4 h-4 text-sindio-muted shrink-0" />}
        </button>

        {profileOpen && (
          <div className="px-4 pb-4 space-y-1">
            {trialStatus && (
              <div className="px-3 py-2.5 rounded-lg border border-sindio-border bg-sindio-dark/50 mb-2">
                <div className="flex items-center gap-2.5 mb-2">
                  <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${trialStatus.iconBg}`}>
                    <trialStatus.icon className={`w-3.5 h-3.5 ${trialStatus.textColor}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className={`text-xs font-semibold ${trialStatus.textColor}`}>
                      {trialStatus.label}
                    </div>
                    {trialStatus.variant !== 'paid' && trialStatus.variant !== 'expired' && (
                      <div className="text-[10px] text-sindio-muted">
                        Free trial · {TRIAL_DAYS - trialStatus.days}d used
                      </div>
                    )}
                    {trialStatus.variant === 'expired' && (
                      <div className="text-[10px] text-sindio-muted">Subscribe to continue</div>
                    )}
                    {trialStatus.variant === 'paid' && (
                      <div className="text-[10px] text-sindio-muted">Full access</div>
                    )}
                  </div>
                </div>
                {trialStatus.variant !== 'paid' && (
                  <div className="h-1 rounded-full bg-sindio-border overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${trialStatus.barColor}`}
                      style={{ width: `${trialStatus.pct}%` }}
                    />
                  </div>
                )}
              </div>
            )}
            <button
              onClick={logout}
              className="w-full flex items-center gap-3 px-3 py-2 text-sm text-sindio-muted hover:text-red-400 hover:bg-red-900/10 rounded-lg transition-colors"
            >
              <LogOut className="w-4 h-4" />
              Sign Out
            </button>

            {!showDeleteConfirm ? (
              <button
                onClick={() => setShowDeleteConfirm(true)}
                className="w-full flex items-center gap-3 px-3 py-2 text-sm text-sindio-muted hover:text-sindio-critical hover:bg-red-900/10 rounded-lg transition-colors"
              >
                <Trash2 className="w-4 h-4" />
                Delete Account
              </button>
            ) : (
              <div className="space-y-2 pt-2">
                <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-red-900/20 border border-red-900/30">
                  <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                  <p className="text-xs text-red-300">
                    This will permanently delete your account and all associated data. This action cannot be undone.
                  </p>
                </div>
                {deleteError && (
                  <p className="text-xs text-red-400 px-3">{deleteError}</p>
                )}
                <div className="flex gap-2 px-3">
                  <button
                    onClick={() => setShowDeleteConfirm(false)}
                    disabled={deleting}
                    className="flex-1 px-3 py-1.5 text-xs border border-sindio-border text-sindio-muted rounded hover:bg-sindio-border/30 transition-colors disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleDeleteAccount}
                    disabled={deleting}
                    className="flex-1 px-3 py-1.5 text-xs bg-red-600 hover:bg-red-700 text-white rounded transition-colors disabled:opacity-50"
                  >
                    {deleting ? 'Deleting…' : 'Confirm Delete'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  )
}
