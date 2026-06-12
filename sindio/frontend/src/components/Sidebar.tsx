import { Link } from 'react-router-dom'
import {
  Droplets, Zap, Route, Trash2, Footprints, TrainFront, TrainTrack, Plane,
  Bell, BookOpen,
} from 'lucide-react'

const menuItems = [
  { icon: Zap, label: 'Power Systems', id: 'power' },
  { icon: Droplets, label: 'Water Grid', id: 'water' },
  { icon: Route, label: 'Road Networks', id: 'roads' },
  { icon: Trash2, label: 'Solid Waste', id: 'solid_waste' },
  { icon: Footprints, label: 'Sidewalks', id: 'sidewalks' },
  { icon: TrainFront, label: 'LRT Trains', id: 'lrt' },
  { icon: TrainTrack, label: 'SGR Trains', id: 'sgr' },
  { icon: Plane, label: 'Airports', id: 'airports' },
]

interface SidebarProps {
  activeSystem: string
  onSelect: (id: string) => void
}

export default function Sidebar({ activeSystem, onSelect }: SidebarProps) {
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
          <Bell className="w-4 h-4" />
          Alert Feed
        </button>
      </nav>

      <div className="p-4 border-t border-sindio-border space-y-1">
        <Link to="/dashboard?system=alerts" className="flex items-center gap-3 px-3 py-2 text-sm text-sindio-muted hover:text-sindio-text hover:bg-sindio-border/50 rounded-lg transition-colors">
          <Bell className="w-4 h-4" />
          Alerts History
        </Link>
        <Link to="/" className="flex items-center gap-3 px-3 py-2 text-sm text-sindio-muted hover:text-sindio-text hover:bg-sindio-border/50 rounded-lg transition-colors">
          <BookOpen className="w-4 h-4" />
          Documentation
        </Link>
      </div>
    </aside>
  )
}
