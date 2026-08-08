import { useState, useEffect } from 'react'
import { api } from '../services/api'
import { Trees, TrendingUp, Award, Loader2 } from 'lucide-react'

interface CarbonDashboardProps {
  citySlug: string
}

export default function CarbonDashboard({ citySlug }: CarbonDashboardProps) {
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.carbon.dashboard(citySlug)
        if (!cancelled) setData(result)
      } catch (err: unknown) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load carbon data')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [citySlug])

  if (loading) return <div className="flex items-center justify-center p-8 text-sindio-muted"><Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading carbon data...</div>
  if (error) return <div className="text-red-400 p-4 text-sm">{error}</div>
  if (!data) return null

  const savingsByType = data.savings_by_infra_type as Record<string, number> || {}
  const credits = data.credits as Record<string, unknown>[] || []

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent flex items-center gap-2">
        <Trees className="w-4 h-4" /> Carbon Credits
      </h3>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-sindio-panel rounded-lg p-3 border border-sindio-border">
          <div className="text-xs text-sindio-muted mb-1">Total Credits</div>
          <div className="text-xl font-bold text-white">{String(data.total_credits_issued)}</div>
        </div>
        <div className="bg-sindio-panel rounded-lg p-3 border border-sindio-border">
          <div className="text-xs text-sindio-muted mb-1">tCO₂e Saved</div>
          <div className="text-xl font-bold text-green-400">{String(data.total_tco2e_saved)}</div>
        </div>
        <div className="bg-sindio-panel rounded-lg p-3 border border-sindio-border">
          <div className="text-xs text-sindio-muted mb-1">Verified tCO₂e</div>
          <div className="text-xl font-bold text-green-500">{String(data.verified_tco2e)}</div>
        </div>
        <div className="bg-sindio-panel rounded-lg p-3 border border-sindio-border">
          <div className="text-xs text-sindio-muted mb-1">Total Value</div>
          <div className="text-xl font-bold text-yellow-400">KSh {String(data.total_value_kes || data.total_value_usd)}</div>
        </div>
      </div>

      {Object.keys(savingsByType).length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-sindio-muted mb-2 flex items-center gap-1">
            <TrendingUp className="w-4 h-4" /> Savings by Infrastructure Type (tCO₂e)
          </h4>
          <div className="space-y-1">
            {Object.entries(savingsByType).map(([type, tco2e]) => (
              <div key={type} className="flex items-center justify-between text-xs">
                <span className="text-sindio-muted capitalize">{type.replace('_', ' ')}</span>
                <div className="flex items-center gap-2">
                  <div className="w-32 bg-sindio-dark rounded-full h-2 overflow-hidden">
                    <div
                      className="h-full bg-green-500 rounded-full transition-all"
                      style={{ width: `${Math.min((Number(tco2e) / (Number(data.total_tco2e_saved) || 1)) * 100, 100)}%` }}
                    />
                  </div>
                  <span className="text-green-400 w-16 text-right">{String(tco2e)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {credits.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-sindio-muted mb-2 flex items-center gap-1">
            <Award className="w-4 h-4" /> Recent Credits
          </h4>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {credits.slice(0, 10).map((c) => (
              <div key={String(c.credit_id)} className="flex items-center justify-between text-xs bg-sindio-dark rounded p-2 border border-sindio-border">
                <div>
                  <span className="text-white font-medium">{String(c.credit_id).slice(0, 16)}...</span>
                  <span className="text-sindio-muted ml-2 capitalize">{String(c.infra_type)}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-green-400">{String(c.tco2e_saved)} tCO₂e</span>
                  <span className="text-yellow-400">KSh {String(c.total_value_kes || c.total_value_usd)}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${c.verification_status === 'verified' ? 'bg-green-900/50 text-green-400' : 'bg-yellow-900/50 text-yellow-400'}`}>
                    {String(c.verification_status)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
