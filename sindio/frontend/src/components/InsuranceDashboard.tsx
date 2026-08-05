import { useState, useEffect } from 'react'
import { api } from '../services/api'
import { Shield, AlertTriangle, DollarSign, FileText, Loader2 } from 'lucide-react'

interface InsuranceDashboardProps {
  citySlug: string
}

export default function InsuranceDashboard({ citySlug }: InsuranceDashboardProps) {
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.insurance.dashboard(citySlug)
        if (!cancelled) setData(result)
      } catch (err: unknown) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load insurance data')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [citySlug])

  if (loading) return <div className="flex items-center justify-center p-8 text-sindio-muted"><Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading insurance data...</div>
  if (error) return <div className="text-red-400 p-4 text-sm">{error}</div>
  if (!data) return null

  const coverageByType = data.coverage_by_infra_type as Record<string, number> || {}
  const topRisks = data.top_risks as Record<string, unknown>[] || []
  const recentClaims = data.recent_claims as Record<string, unknown>[] || []

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-sindio-accent flex items-center gap-2">
        <Shield className="w-5 h-5" /> Parametric Insurance
      </h3>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-sindio-panel rounded-lg p-3 border border-sindio-border">
          <div className="text-xs text-sindio-muted mb-1">Active Policies</div>
          <div className="text-xl font-bold text-white">{String(data.active_policies)}</div>
        </div>
        <div className="bg-sindio-panel rounded-lg p-3 border border-sindio-border">
          <div className="text-xs text-sindio-muted mb-1">Coverage</div>
          <div className="text-xl font-bold text-green-400">KSh {String(data.total_coverage_kes || data.total_coverage_usd)}</div>
        </div>
        <div className="bg-sindio-panel rounded-lg p-3 border border-sindio-border">
          <div className="text-xs text-sindio-muted mb-1">Premium Pool</div>
          <div className="text-xl font-bold text-blue-400">KSh {String(data.total_premium_kes || data.total_premium_usd)}</div>
        </div>
        <div className="bg-sindio-panel rounded-lg p-3 border border-sindio-border">
          <div className="text-xs text-sindio-muted mb-1">Claims Paid</div>
          <div className="text-xl font-bold text-yellow-400">KSh {String(data.total_paid_kes || data.total_paid_usd)}</div>
        </div>
      </div>

      {Object.keys(coverageByType).length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-sindio-muted mb-2 flex items-center gap-1">
            <FileText className="w-4 h-4" /> Coverage by Infrastructure Type
          </h4>
          <div className="space-y-1">
            {Object.entries(coverageByType).map(([type, amount]) => (
              <div key={type} className="flex items-center justify-between text-xs">
                <span className="text-sindio-muted capitalize">{type.replace('_', ' ')}</span>
                <div className="flex items-center gap-2">
                  <div className="w-32 bg-sindio-dark rounded-full h-2 overflow-hidden">
                    <div
                      className="h-full bg-blue-500 rounded-full transition-all"
                      style={{ width: `${Math.min((Number(amount) / (Number(data.total_coverage_kes || data.total_coverage_usd) || 1)) * 100, 100)}%` }}
                    />
                  </div>
                  <span className="text-blue-400 w-16 text-right">KSh {String(amount)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {topRisks.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-sindio-muted mb-2 flex items-center gap-1">
            <AlertTriangle className="w-4 h-4" /> Top Risk Assets
          </h4>
          <div className="space-y-1">
            {topRisks.slice(0, 8).map((r) => (
              <div key={String(r.asset_id)} className="flex items-center justify-between text-xs bg-sindio-dark rounded p-2 border border-sindio-border">
                <span className="text-white capitalize">{String(r.infra_type)}</span>
                <div className="flex items-center gap-3">
                  <span className="text-sindio-muted">Risk: {String(r.risk_score)}</span>
                  <span className="text-red-400">Loss: KSh {String(r.expected_annual_loss_kes || r.expected_annual_loss_usd)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {recentClaims.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-sindio-muted mb-2 flex items-center gap-1">
            <DollarSign className="w-4 h-4" /> Recent Claims
          </h4>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {recentClaims.slice(0, 8).map((c) => (
              <div key={String(c.claim_id)} className="flex items-center justify-between text-xs bg-sindio-dark rounded p-2 border border-sindio-border">
                <div>
                  <span className="text-white font-medium">{String(c.claim_id).slice(0, 12)}...</span>
                  <span className="text-sindio-muted ml-2">Stress: {String(c.trigger_stress)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-yellow-400">KSh {String(c.payout_kes || c.payout_usd)}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${c.status === 'paid' ? 'bg-green-900/50 text-green-400' : c.status === 'pending' ? 'bg-yellow-900/50 text-yellow-400' : 'bg-red-900/50 text-red-400'}`}>
                    {String(c.status)}
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
