import { useState, useEffect } from 'react'
import { api } from '../services/api'

interface WardHealth {
  ward: string
  health_score: number
  overall_health: string
  color: string
  stressed_assets: number
  avg_stress_pct: number
}

interface SnapshotData {
  city: string
  wards: WardHealth[]
  summary: { total_wards: number; wards_good: number; wards_moderate: number; wards_poor: number; health_pct: number }
}

const dotColor: Record<string, string> = {
  green: 'bg-emerald-500',
  amber: 'bg-yellow-500',
  red: 'bg-red-500',
}

const cardBorder: Record<string, string> = {
  green: 'border-emerald-500/20',
  amber: 'border-yellow-500/20',
  red: 'border-red-500/20',
}

const cardBg: Record<string, string> = {
  green: 'bg-emerald-500/5',
  amber: 'bg-yellow-500/5',
  red: 'bg-red-500/5',
}

export default function ConditionsSnapshot() {
  const [data, setData] = useState<SnapshotData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.snapshot.get('nairobi')
      .then(d => { setData(d as unknown as SnapshotData); setLoading(false) })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed')
        setLoading(false)
      })
  }, [])

  if (loading) {
    return <div className="panel rounded-xl p-4 text-sindio-muted text-sm">Loading Nairobi conditions...</div>
  }

  if (error) return <div className="text-red-400 text-sm p-4">{error}</div>
  if (!data) return null

  const poorWards = data.wards.filter(w => w.overall_health === 'poor')
  const moderateWards = data.wards.filter(w => w.overall_health === 'moderate')

  return (
    <div className="panel rounded-xl overflow-hidden">
      <div className="p-4 border-b border-sindio-border flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">Nairobi Conditions</h3>
        <span className="text-[10px] text-sindio-muted tabular-nums">{data.summary.health_pct}% healthy</span>
      </div>

      <div className="p-4 space-y-4">
        <div className="grid grid-cols-3 gap-2">
          <div className="text-center py-2.5 rounded bg-emerald-500/5 border border-emerald-500/20">
            <div className="text-lg font-semibold text-emerald-400">{data.summary.wards_good}</div>
            <div className="text-[10px] text-sindio-muted">Good</div>
          </div>
          <div className="text-center py-2.5 rounded bg-yellow-500/5 border border-yellow-500/20">
            <div className="text-lg font-semibold text-yellow-400">{data.summary.wards_moderate}</div>
            <div className="text-[10px] text-sindio-muted">Moderate</div>
          </div>
          <div className="text-center py-2.5 rounded bg-red-500/5 border border-red-500/20">
            <div className="text-lg font-semibold text-red-400">{data.summary.wards_poor}</div>
            <div className="text-[10px] text-sindio-muted">At Risk</div>
          </div>
        </div>

        {poorWards.length > 0 && (
          <div>
            <div className="text-xs font-medium text-red-400 mb-1.5">Wards Needing Attention</div>
            <div className="space-y-1">
              {poorWards.slice(0, 3).map(w => (
                <div key={w.ward} className="flex items-center justify-between bg-red-500/5 border border-red-500/20 rounded px-3 py-1.5 text-xs">
                  <span className="text-white">{w.ward}</span>
                  <span className="text-red-400 text-[10px] tabular-nums">{w.stressed_assets} assets</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {moderateWards.length > 0 && poorWards.length === 0 && (
          <div>
            <div className="text-xs font-medium text-yellow-400 mb-1.5">Wards to Watch</div>
            <div className="space-y-1">
              {moderateWards.slice(0, 3).map(w => (
                <div key={w.ward} className="flex items-center justify-between bg-yellow-500/5 border border-yellow-500/20 rounded px-3 py-1.5 text-xs">
                  <span className="text-white">{w.ward}</span>
                  <span className="text-yellow-400 text-[10px] tabular-nums">{w.health_score}%</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 max-h-[260px] overflow-y-auto">
          {data.wards.map(w => (
            <div key={w.ward} className={`flex items-center gap-1.5 ${cardBg[w.color]} ${cardBorder[w.color]} border rounded px-2 py-1`}>
              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotColor[w.color]}`} />
              <div className="min-w-0">
                <div className="text-[10px] text-white truncate">{w.ward}</div>
                <div className="text-[9px] text-sindio-muted tabular-nums">{w.health_score}%</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
