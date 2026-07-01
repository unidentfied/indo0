import { useState, useEffect } from 'react'
import { Gauge } from 'lucide-react'
import { api } from '../services/api'
import infraIcons from './InfraIcons'

interface PerTypeSummary {
  infrastructure_type: string
  display_name: string
  total_assets: number
  stressed_assets: number
  critical_assets: number
  warning_assets: number
  avg_stress: number
  mock_data_ratio: number
  report_alignment_pct: number
}

interface MonitorData {
  timestamp: string
  total_assets_monitored: number
  total_stressed_assets: number
  total_critical_assets: number
  total_warning_assets: number
  overall_mock_ratio: number
  per_type_summary: PerTypeSummary[]
}

function stressColor(v: number): string {
  if (v > 0.7) return 'text-sindio-critical'
  if (v > 0.4) return 'text-sindio-warning'
  return 'text-emerald-400'
}

function stressBg(v: number): string {
  if (v > 0.7) return 'bg-sindio-critical'
  if (v > 0.4) return 'bg-sindio-warning'
  return 'bg-emerald-400'
}

export default function MonitorOverview() {
  const [data, setData] = useState<MonitorData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.monitor.stress()
      .then(d => { setData(d as unknown as MonitorData); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="panel p-6">
        <div className="flex items-center gap-2 mb-4">
          <Gauge className="w-4 h-4 text-sindio-accent" />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Unified Monitor</h3>
        </div>
        <div className="text-xs text-sindio-muted text-center py-8">Loading monitoring data...</div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="panel p-6">
        <div className="flex items-center gap-2 mb-4">
          <Gauge className="w-4 h-4 text-sindio-accent" />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Unified Monitor</h3>
        </div>
        <div className="text-xs text-sindio-muted text-center py-8">Monitor unavailable</div>
      </div>
    )
  }

  const criticalPct = data.total_assets_monitored > 0
    ? (data.total_critical_assets / data.total_assets_monitored * 100).toFixed(1)
    : '0'

  return (
    <div className="panel">
      <div className="p-4 border-b border-sindio-border">
        <div className="flex items-center gap-2">
          <Gauge className="w-4 h-4 text-sindio-accent" />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Unified Monitor</h3>
          <span className="ml-auto text-[10px] bg-sindio-accent/10 text-sindio-accent px-2 py-0.5 rounded uppercase font-bold">
            {data.per_type_summary.length} Types
          </span>
        </div>
      </div>

      {/* Summary stats */}
      <div className="p-4 grid grid-cols-2 gap-3 border-b border-sindio-border">
        <div>
          <div className="text-[10px] uppercase text-sindio-muted">Total Assets</div>
          <div className="text-lg font-semibold">{data.total_assets_monitored.toLocaleString()}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-sindio-muted">Stressed</div>
          <div className={`text-lg font-semibold ${stressColor(data.total_stressed_assets / Math.max(data.total_assets_monitored, 1))}`}>
            {data.total_stressed_assets.toLocaleString()}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-sindio-muted">Critical</div>
          <div className="text-lg font-semibold text-sindio-critical">{data.total_critical_assets.toLocaleString()} ({criticalPct}%)</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-sindio-muted">Data Quality</div>
          <div className="text-lg font-semibold text-sindio-muted">{(data.overall_mock_ratio * 100).toFixed(0)}% synthetic</div>
        </div>
      </div>

      {/* Per-type breakdown */}
      <div className="divide-y divide-sindio-border">
        {data.per_type_summary.map(t => {
          const pct = t.total_assets > 0 ? Math.round(t.stressed_assets / t.total_assets * 100) : 0
          return (
            <div key={t.infrastructure_type} className="px-4 py-3">
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2.5">
                  <span className="flex items-center justify-center w-7 h-7 rounded-lg bg-sindio-panel border border-sindio-border">
                    {infraIcons[t.infrastructure_type] || <span className="text-sindio-muted">?</span>}
                  </span>
                  <span className="text-xs font-medium text-sindio-text">{t.display_name}</span>
                </div>
                <span className={`text-xs font-semibold ${stressColor(t.avg_stress)}`}>{(t.avg_stress * 100).toFixed(1)}%</span>
              </div>
              <div className="h-1.5 rounded-full bg-sindio-panel overflow-hidden">
                <div className={`h-full rounded-full ${stressBg(t.avg_stress)}`} style={{ width: `${Math.min(pct, 100)}%` }} />
              </div>
              <div className="flex items-center justify-between mt-1">
                <span className="text-[10px] text-sindio-muted">{t.stressed_assets.toLocaleString()} / {t.total_assets.toLocaleString()} stressed</span>
                <span className="text-[10px] text-sindio-muted">{(t.report_alignment_pct * 100).toFixed(0)}% aligned</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
