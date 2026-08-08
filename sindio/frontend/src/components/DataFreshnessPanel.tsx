import { useState, useEffect, useCallback } from 'react'
import { api } from '../services/api'

interface SourceStatus {
  id: string
  name: string
  type: string
  status: string
  color: string
  critical: boolean
  hours_since_update: number | null
  expected_interval_hours: number
  last_updated: string | null
  records_last_fetch: number
}

interface FreshnessData {
  sources: SourceStatus[]
  summary: Record<string, number>
  total_sources: number
  fresh_pct: number
  checked_at: string
}

const colorMap: Record<string, { bg: string; text: string; border: string }> = {
  green: { bg: 'bg-green-500/10', text: 'text-green-400', border: 'border-green-500/30' },
  amber: { bg: 'bg-yellow-500/10', text: 'text-yellow-400', border: 'border-yellow-500/30' },
  red: { bg: 'bg-red-500/10', text: 'text-red-400', border: 'border-red-500/30' },
  grey: { bg: 'bg-slate-500/10', text: 'text-slate-400', border: 'border-slate-500/30' },
}

const colorDot: Record<string, string> = {
  green: 'bg-green-500',
  amber: 'bg-yellow-500',
  red: 'bg-red-500',
  grey: 'bg-slate-500',
}

const statusLabel: Record<string, string> = {
  fresh: 'Fresh',
  stale: 'Stale',
  outdated: 'Outdated',
  offline: 'Offline',
}

function formatCheckedAt(iso: string): string {
  try {
    const then = new Date(iso)
    if (isNaN(then.getTime())) return ''
    const diffMs = Date.now() - then.getTime()
    const diffSec = Math.round(diffMs / 1000)
    if (diffSec < 10) return 'just now'
    if (diffSec < 60) return `${diffSec}s ago`
    const diffMin = Math.round(diffSec / 60)
    if (diffMin < 60) return `${diffMin}m ago`
    return `${Math.round(diffMin / 60)}h ago`
  } catch {
    return ''
  }
}

export default function DataFreshnessPanel() {
  const [data, setData] = useState<FreshnessData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const json = await api.dataFreshness() as unknown as FreshnessData
      if (!json || !Array.isArray(json.sources)) {
        throw new Error('Invalid response format')
      }
      setData(json)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    // Auto-refresh every 60 seconds
    const interval = setInterval(load, 60_000)
    return () => clearInterval(interval)
  }, [load])

  if (loading && !data) {
    return <div className="text-sindio-muted text-xs p-2">Checking data sources…</div>
  }

  if (error && !data) {
    return (
      <div className="flex items-center justify-between text-xs p-2">
        <span className="text-red-400">Data freshness unavailable</span>
        <button
          onClick={load}
          className="text-sindio-accent hover:text-white text-[10px] underline transition-colors"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-1">
        <h4 className="text-xs font-medium text-sindio-muted">Data Freshness</h4>
        <div className="flex items-center gap-2">
          {data.checked_at && (
            <span className="text-[10px] text-sindio-muted opacity-60">
              {formatCheckedAt(data.checked_at)}
            </span>
          )}
          <span className="text-[10px] text-sindio-muted tabular-nums">{data.fresh_pct}% fresh</span>
        </div>
      </div>

      <div className="flex gap-3 text-[10px] text-sindio-muted px-1">
        {Object.entries({fresh: 'green', stale: 'amber', outdated: 'red', offline: 'grey'}).map(([status, color]) => (
          <span key={status} className="flex items-center gap-1">
            <span className={`w-1.5 h-1.5 rounded-full ${colorDot[color]}`} />
            <span>{data.summary[status] || 0}</span>
            <span className="opacity-60">{statusLabel[status]}</span>
          </span>
        ))}
      </div>

      <div className="space-y-px max-h-80 overflow-y-auto">
        {data.sources.map(source => {
          const colors = colorMap[source.color] || colorMap.grey
          return (
            <div key={source.id} className={`flex items-center justify-between text-[10px] ${colors.bg} px-2 py-1.5 border-l-2 ${colors.border}`}>
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="text-white font-medium truncate">{source.name}</span>
                {source.critical && <span className="text-[8px] text-red-400 opacity-70 flex-shrink-0">CRITICAL</span>}
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                {source.hours_since_update !== null && (
                  <span className={colors.text}>
                    {source.hours_since_update < 1
                      ? `${Math.round(source.hours_since_update * 60)}m`
                      : `${source.hours_since_update.toFixed(1)}h`}
                  </span>
                )}
                <span className="text-sindio-muted tabular-nums">{source.records_last_fetch.toLocaleString()}</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

