import { Link } from 'react-router-dom'
import { useState } from 'react'
import {
  Droplet, Zap, Route, Recycle, Footprints, TrainFront, Train, Plane,
  BellRing, BookOpen, User, LogOut, Trash2, AlertTriangle, ChevronDown, ChevronUp,
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

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
