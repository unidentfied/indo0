import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  ChevronDown,
  ChevronUp,
  Wifi,
  FileText,
  AlertTriangle,
  AlertOctagon,
  Info,
  Clock,
} from 'lucide-react'
import type { AlertV1, NextUpdate } from '../types'
import infraIcons from './InfraIcons'

const REST_URL = '/api/v1/alerts'
const UPDATES_URL = '/api/v1/next_updates'
const PAGE_SIZE = 20

// ---------------------------------------------------------------------------
// Icons & colors
// ---------------------------------------------------------------------------

const levelIcon = (level: string) => {
  switch (level) {
    case 'critical': return <AlertOctagon className="w-4 h-4 text-sindio-critical" />
    case 'warning': return <AlertTriangle className="w-4 h-4 text-sindio-warning" />
    default: return <Info className="w-4 h-4 text-sindio-accent" />
  }
}

const levelBg = (level: string) => {
  switch (level) {
    case 'critical': return 'border-l-sindio-critical bg-sindio-critical/5'
    case 'warning': return 'border-l-sindio-warning bg-sindio-warning/5'
    default: return 'border-l-sindio-accent bg-sindio-accent/5'
  }
}

const levelDot = (level: string) => {
  switch (level) {
    case 'critical': return 'bg-sindio-critical'
    case 'warning': return 'bg-sindio-warning'
    default: return 'bg-sindio-accent'
  }
}

// ---------------------------------------------------------------------------
// Countdown timer
// ---------------------------------------------------------------------------

function useCountdown(targetISO: string) {
  const [left, setLeft] = useState('')

  useEffect(() => {
    const tick = () => {
      const diff = new Date(targetISO).getTime() - Date.now()
      if (diff <= 0) { setLeft('now'); return }
      const d = Math.floor(diff / 86_400_000)
      const h = Math.floor((diff % 86_400_000) / 3_600_000)
      const m = Math.floor((diff % 3_600_000) / 60_000)
      const s = Math.floor((diff % 60_000) / 1000)
      const parts = []
      if (d > 0) parts.push(`${d}d`)
      if (h > 0) parts.push(`${h}h`)
      if (m > 0) parts.push(`${m}m`)
      parts.push(`${s}s`)
      setLeft(parts.join(' '))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [targetISO])

  return left
}

function CountdownBadge({ nextAt, label }: { nextAt: string; label: string }) {
  const left = useCountdown(nextAt)
  return (
    <span className="text-[10px] text-sindio-muted flex items-center gap-1">
      <Clock className="w-3 h-3" />
      Next {label} check in {left}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AlertFeed() {
  const [alerts, setAlerts] = useState<AlertV1[]>([])
  const [updates, setUpdates] = useState<NextUpdate[]>([])
  const [loading, setLoading] = useState(true)

  // Filters
  const [wardFilter, setWardFilter] = useState('')
  const [severityMin, setSeverityMin] = useState(0)
  const [classTab, setClassTab] = useState<'all' | 'recurring' | 'density_driven' | 'hybrid'>('all')

  // Pagination
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  // Accordion
  const [expandedTypes, setExpandedTypes] = useState<Set<string>>(new Set(['power', 'water', 'roads', 'solid_waste', 'sidewalks', 'lrt', 'sgr', 'airports']))

  const fetchData = useCallback(async () => {
    try {
      const [alertsRes, updatesRes] = await Promise.all([
        fetch(REST_URL),
        fetch(UPDATES_URL),
      ])
      if (alertsRes.ok) {
        const data = await alertsRes.json()
        setAlerts(data.alerts || [])
      }
      if (updatesRes.ok) {
        const data = await updatesRes.json()
        setUpdates(data.updates || [])
      }
    } catch {
      // keep current state on fetch failure
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [fetchData])

  // Reset visible count when filters change
  useEffect(() => {
    setVisibleCount(PAGE_SIZE)
  }, [wardFilter, severityMin, classTab])

  // --- compute filtered alerts ---
  const filtered = useMemo(() => {
    return alerts.filter(a => {
      if (wardFilter && a.ward !== wardFilter) return false
      if (a.severity_score < severityMin) return false
      if (classTab === 'recurring' && a.classification !== 'recurring') return false
      if (classTab === 'density_driven' && a.classification !== 'density_driven') return false
      if (classTab === 'hybrid' && a.classification !== 'hybrid') return false
      return true
    })
  }, [alerts, wardFilter, severityMin, classTab])

  // --- group by infrastructure_type ---
  const grouped = useMemo(() => {
    const map = new Map<string, AlertV1[]>()
    for (const a of filtered) {
      const key = a.infrastructure_type
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(a)
    }
    return map
  }, [filtered])

  // --- unique wards ---
  const wards = useMemo(() => {
    const set = new Set(alerts.map(a => a.ward).filter(Boolean))
    return Array.from(set).sort()
  }, [alerts])

  // --- visible alerts ---
  const visibleAlerts = useMemo(() => filtered.slice(0, visibleCount), [filtered, visibleCount])
  const hasMore = visibleCount < filtered.length

  // --- toggle accordion ---
  const toggleType = (t: string) => {
    setExpandedTypes(prev => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t); else next.add(t)
      return next
    })
  }

  // --- export PDF ---
  const handleExport = () => {
    window.print()
  }

  // --- type label ---
  const typeLabel = (t: string) => {
    switch (t) {
      case 'power': return 'Power Systems'
      case 'water': return 'Water Grid'
      case 'roads': return 'Road Network'
      case 'solid_waste': return 'Solid Waste'
      case 'sidewalks': return 'Sidewalks'
      case 'lrt': return 'LRT Trains'
      case 'sgr': return 'SGR Trains'
      case 'airports': return 'Airports'
      default: return t.charAt(0).toUpperCase() + t.slice(1)
    }
  }

  const updateForType = (t: string) => updates.find(u => u.update_type === t)

  const typeOrder = ['power', 'water', 'roads', 'solid_waste', 'sidewalks', 'lrt', 'sgr', 'airports']
  const sortedTypes = typeOrder.filter(t => grouped.has(t))

  return (
    <div className="space-y-4">
      {/* --- Header --- */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold">Alert Feed</h2>
          <span className="flex items-center gap-1 text-[10px] uppercase font-bold px-2 py-0.5 rounded bg-emerald-400/10 text-emerald-400">
            <Wifi className="w-3 h-3" />
            Live
          </span>
        </div>
        <button
          onClick={handleExport}
          className="btn-secondary text-xs px-3 py-1.5"
        >
          <FileText className="w-3.5 h-3.5" />
          Export to PDF
        </button>
      </div>

      {/* --- Filter bar --- */}
      <div className="panel p-3 flex flex-wrap items-center gap-3">
        {/* Ward dropdown */}
        <select
          value={wardFilter}
          onChange={e => setWardFilter(e.target.value)}
          className="bg-sindio-panel border border-sindio-border text-sindio-text text-xs rounded px-2 py-1.5 outline-none focus:border-sindio-accent"
        >
          <option value="">All Wards</option>
          {wards.map(w => <option key={w} value={w}>{w}</option>)}
        </select>

        {/* Severity slider */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase text-sindio-muted whitespace-nowrap">Severity &ge;</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={severityMin}
            onChange={e => setSeverityMin(Number(e.target.value))}
            className="accent-sindio-accent w-20"
          />
          <span className="text-xs text-sindio-accent w-6">{severityMin.toFixed(2)}</span>
        </div>

        {/* Classification tabs */}
        <div className="flex items-center gap-1">
          {(['all', 'recurring', 'density_driven', 'hybrid'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setClassTab(tab)}
              className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                classTab === tab
                  ? 'bg-sindio-accent/10 border-sindio-accent text-sindio-accent'
                  : 'border-sindio-border text-sindio-muted hover:text-sindio-text'
              }`}
            >
              {tab === 'all' ? 'All' : tab === 'density_driven' ? 'Density' : tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>

        <span className="text-[10px] text-sindio-muted ml-auto">
          {filtered.length} alert{filtered.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* --- Alert accordion feed --- */}
      {loading ? (
        <div className="panel p-8 text-center text-sindio-muted text-sm">Loading alerts...</div>
      ) : sortedTypes.length === 0 ? (
        <div className="panel p-8 text-center text-sindio-muted text-sm">No alerts match the current filters.</div>
      ) : (
        <div className="space-y-2">
          {sortedTypes.map(type => {
            const items = grouped.get(type)!
            const update = updateForType(type)
            const expanded = expandedTypes.has(type)

            return (
              <div key={type} className="panel overflow-hidden">
                {/* Accordion header */}
                <button
                  onClick={() => toggleType(type)}
                  className="w-full p-3 flex items-center justify-between hover:bg-sindio-border/20 transition-colors text-left"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-sindio-accent">{infraIcons[type]}</span>
                    <div>
                      <span className="text-sm font-semibold">{typeLabel(type)}</span>
                      <span className="ml-2 text-[10px] text-sindio-muted">
                        {items.length} alert{items.length !== 1 ? 's' : ''}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {update && <CountdownBadge nextAt={update.next_at} label={type} />}
                    {expanded ? <ChevronUp className="w-4 h-4 text-sindio-muted" /> : <ChevronDown className="w-4 h-4 text-sindio-muted" />}
                  </div>
                </button>

                {/* Accordion body */}
                {expanded && (
                  <div className="divide-y divide-sindio-border">
                    {items.map(a => (
                      <div
                        key={a.id}
                        className={`p-3 pl-4 border-l-2 ${levelBg(a.level)} hover:bg-sindio-border/10 transition-colors`}
                      >
                        <div className="flex items-start gap-3">
                          <div className="mt-0.5 flex-shrink-0">{levelIcon(a.level)}</div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-0.5">
                              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${levelDot(a.level)}`} />
                              <span className="text-xs font-semibold truncate">{a.title}</span>
                              {a.classification && (
                                <span className="text-[9px] uppercase bg-sindio-border/30 px-1.5 py-0.5 rounded flex-shrink-0">
                                  {a.classification === 'density_driven' ? 'density' : a.classification}
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-sindio-muted line-clamp-2">{a.description}</p>
                            <div className="flex items-center gap-3 mt-1.5 text-[10px] text-sindio-muted">
                              <span>{a.timestamp}</span>
                              <span>{a.ward}</span>
                              <span className="text-sindio-accent">{(a.severity_score * 100).toFixed(0)}%</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* --- Infinite scroll (Load More) --- */}
      {hasMore && (
        <div className="text-center">
          <button
            onClick={() => setVisibleCount(prev => prev + PAGE_SIZE)}
            className="btn-secondary text-xs px-4 py-2"
          >
            Load More ({filtered.length - visibleCount} remaining)
          </button>
        </div>
      )}

      {/* --- Hidden printable report --- */}
      <div className="hidden print:block print:m-0 print:p-4 print:bg-white print:text-black">
        <h1 className="text-2xl font-bold mb-2">Sindio — Nairobi Urban Planning Alert Report</h1>
        <p className="text-sm text-gray-600 mb-4">
          Generated: {new Date().toLocaleString()} &bull; {filtered.length} active alerts
        </p>

        <h2 className="text-lg font-semibold mb-1 mt-4">Summary by Infrastructure Type</h2>
        <table className="w-full text-sm mb-4 border-collapse">
          <thead>
            <tr className="border-b">
              <th className="text-left py-1">Type</th>
              <th className="text-left py-1">Count</th>
              <th className="text-left py-1">Critical</th>
              <th className="text-left py-1">Warning</th>
            </tr>
          </thead>
          <tbody>
            {sortedTypes.map(t => {
              const items = grouped.get(t)!
              return (
                <tr key={t} className="border-b">
                  <td className="py-1 font-medium">{typeLabel(t)}</td>
                  <td className="py-1">{items.length}</td>
                  <td className="py-1">{items.filter(a => a.level === 'critical').length}</td>
                  <td className="py-1">{items.filter(a => a.level === 'warning').length}</td>
                </tr>
              )
            })}
          </tbody>
        </table>

        <h2 className="text-lg font-semibold mb-1 mt-4">Active Alerts</h2>
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b">
              <th className="text-left py-1">ID</th>
              <th className="text-left py-1">Time</th>
              <th className="text-left py-1">Level</th>
              <th className="text-left py-1">Type</th>
              <th className="text-left py-1">Ward</th>
              <th className="text-left py-1">Title</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(a => (
              <tr key={a.id} className="border-b">
                <td className="py-1">{a.id}</td>
                <td className="py-1">{a.timestamp}</td>
                <td className="py-1">{a.level}</td>
                <td className="py-1">{a.infrastructure_type}</td>
                <td className="py-1">{a.ward}</td>
                <td className="py-1">{a.title}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <p className="text-[10px] text-gray-400 mt-4">
          Report includes timestamped snapshots of alert data. Map snapshots require separate GIS export workflow.
        </p>
      </div>
    </div>
  )
}
