import { useState, useEffect, useCallback } from 'react'
import { CalendarClock, RefreshCw } from 'lucide-react'
import { api } from '../services/api'
import infraIcons from './InfraIcons'

interface UpdateEntry {
  update_type: string
  display_name: string
  next_at: string
  interval_sec: number
  critical_interval_sec: number
  standard_interval_sec: number
  poll_interval_sec: number
  description: string
  mode: string
  critical_threshold: number
  last_run: string | null
  seconds_until_next: number | null
  region: string
}

interface NextUpdatesResponse {
  updates: UpdateEntry[]
}

function fmtSec(s: number): string {
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 86400) {
    const h = s / 3600
    return h === Math.floor(h) ? `${h}h` : `${h.toFixed(1)}h`
  }
  const d = s / 86400
  return d === Math.floor(d) ? `${d}d` : `${d.toFixed(1)}d`
}

function countdownStr(target: string): string {
  const diff = new Date(target).getTime() - Date.now()
  if (diff <= 0) return 'now'
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${s % 60}s`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

function relativeTime(iso: string | null): string {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 0) return 'just now'
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function progressPct(entry: UpdateEntry): number {
  if (!entry.last_run || !entry.next_at) return 0
  const start = new Date(entry.last_run).getTime()
  const end = new Date(entry.next_at).getTime()
  const now = Date.now()
  if (end <= start) return 100
  const pct = ((now - start) / (end - start)) * 100
  return Math.max(0, Math.min(100, pct))
}

const DISPLAY_ORDER = ['power', 'water', 'roads', 'solid_waste', 'sidewalks', 'lrt', 'sgr', 'airports']

export default function ScheduleStatus() {
  const [entries, setEntries] = useState<UpdateEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [, setTick] = useState(0)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await api.v1.nextUpdates() as unknown as NextUpdatesResponse
      const updates = d?.updates
      if (!updates || !Array.isArray(updates)) {
        throw new Error('Invalid schedule response')
      }
      setEntries(updates)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 30_000)
    return () => clearInterval(interval)
  }, [load])

  // Tick every second for live countdowns
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  const sorted = DISPLAY_ORDER
    .map(type => entries.find(e => e.update_type === type))
    .filter((e): e is UpdateEntry => !!e)

  // Also include any entries not in DISPLAY_ORDER
  const extra = entries.filter(e => !DISPLAY_ORDER.includes(e.update_type))
  const allSorted = [...sorted, ...extra]

  const criticalCount = allSorted.filter(e => e.mode === 'critical').length

  if (loading && entries.length === 0) {
    return (
      <div className="panel p-6">
        <div className="flex items-center gap-2 mb-4">
          <CalendarClock className="w-4 h-4 text-sindio-accent" />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Schedule Status</h3>
        </div>
        <div className="text-xs text-sindio-muted text-center py-8">Loading schedule…</div>
      </div>
    )
  }

  if (error && entries.length === 0) {
    return (
      <div className="panel p-6">
        <div className="flex items-center gap-2 mb-4">
          <CalendarClock className="w-4 h-4 text-sindio-accent" />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Schedule Status</h3>
        </div>
        <div className="flex flex-col items-center gap-2 py-8">
          <span className="text-red-400 text-xs">Schedule unavailable</span>
          <button onClick={load} className="text-sindio-accent hover:text-white text-[10px] underline transition-colors">
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="panel">
      <div className="p-4 border-b border-sindio-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CalendarClock className="w-4 h-4 text-sindio-accent" />
            <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Schedule Status</h3>
          </div>
          <div className="flex items-center gap-3">
            {criticalCount > 0 && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 font-bold uppercase tracking-wide">
                {criticalCount} critical
              </span>
            )}
            <span className="text-[10px] text-sindio-muted">
              {allSorted.length} systems
            </span>
            <button
              onClick={load}
              className="text-sindio-muted hover:text-white transition-colors"
              title="Refresh schedule"
            >
              <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-sindio-border">
              <th className="text-left p-3 text-sindio-muted font-medium uppercase tracking-wider text-[10px]">System</th>
              <th className="text-left p-3 text-sindio-muted font-medium uppercase tracking-wider text-[10px]">Poll</th>
              <th className="text-left p-3 text-sindio-muted font-medium uppercase tracking-wider text-[10px]">Deep Scan</th>
              <th className="text-left p-3 text-sindio-muted font-medium uppercase tracking-wider text-[10px]">Last Run</th>
              <th className="text-left p-3 text-sindio-muted font-medium uppercase tracking-wider text-[10px]">Next In</th>
              <th className="text-left p-3 text-sindio-muted font-medium uppercase tracking-wider text-[10px] hidden lg:table-cell">Progress</th>
              <th className="text-right p-3 text-sindio-muted font-medium uppercase tracking-wider text-[10px]">Mode</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-sindio-border">
            {allSorted.map(e => {
              const isCritical = e.mode === 'critical'
              const nextIn = countdownStr(e.next_at)
              const isImminent = (e.seconds_until_next ?? Infinity) < e.critical_interval_sec
              const pct = progressPct(e)

              return (
                <tr key={e.update_type} className="hover:bg-sindio-panel/50 transition-colors">
                  <td className="p-3">
                    <div className="flex items-center gap-2.5">
                      <span className="flex items-center justify-center w-7 h-7 rounded-lg bg-sindio-panel border border-sindio-border">
                        {infraIcons[e.update_type]}
                      </span>
                      <div className="flex flex-col">
                        <span className="font-medium text-sindio-text">{e.display_name}</span>
                        <span className="text-[9px] text-sindio-muted opacity-60">{e.region}</span>
                      </div>
                    </div>
                  </td>
                  <td className="p-3 text-sindio-muted font-mono">{fmtSec(e.poll_interval_sec)}</td>
                  <td className="p-3 text-sindio-muted font-mono">
                    <div className="flex flex-col">
                      <span>{fmtSec(e.interval_sec)}</span>
                      {isCritical && (
                        <span className="text-[9px] text-red-400 opacity-70">
                          crit: {fmtSec(e.critical_interval_sec)}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="p-3 text-sindio-muted font-mono">{relativeTime(e.last_run)}</td>
                  <td className={`p-3 font-mono ${isImminent ? 'text-sindio-warning font-semibold' : isCritical ? 'text-red-400' : 'text-sindio-muted'}`}>
                    {nextIn}
                  </td>
                  <td className="p-3 hidden lg:table-cell">
                    <div className="w-20 h-1.5 bg-sindio-border rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-1000 ${
                          pct > 90 ? 'bg-red-500' : pct > 70 ? 'bg-yellow-500' : 'bg-emerald-500'
                        }`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </td>
                  <td className="p-3 text-right">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] uppercase font-bold tracking-wide ${
                      isCritical ? 'bg-red-500/10 text-red-400' : 'bg-emerald-400/10 text-emerald-400'
                    }`}>
                      {e.mode}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

