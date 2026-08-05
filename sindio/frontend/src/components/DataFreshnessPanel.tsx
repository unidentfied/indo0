import { useState, useEffect } from 'react'

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

export default function DataFreshnessPanel() {
  const [data, setData] = useState<FreshnessData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const response = await fetch('/api/v1/data-freshness/')
        if (!response.ok) throw new Error('Failed')
        const json = await response.json()
        setData(json)
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Failed to load')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) return <div className="text-sindio-muted text-xs p-2">Checking data sources...</div>
  if (error) return <div className="text-red-400 text-xs p-2">{error}</div>
  if (!data) return null

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-1">
        <h4 className="text-xs font-medium text-sindio-muted">Data Freshness</h4>
        <span className="text-[10px] text-sindio-muted tabular-nums">{data.fresh_pct}% fresh</span>
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
