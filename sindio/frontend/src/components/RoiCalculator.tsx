import { useState, useEffect } from 'react'
import { api } from '../services/api'
import { Calculator, DollarSign, Clock, ArrowRight, Loader2, BarChart3 } from 'lucide-react'

interface UpgradeOption {
  asset_id: string
  name: string
  typical_cost_kes: number
  typical_annual_savings_kes: number
  description: string
  payback_years: number
}

interface RoiResult {
  upgrade_cost_kes: number
  estimated_annual_savings_kes: number
  payback_period_years: number
  five_year_roi_pct: number
  ten_year_roi_pct: number
  twenty_year_roi_pct: number
  avoided_outage_days_per_year: number
  avoided_outage_cost_per_year_kes: number
  maintenance_savings_per_year_kes: number
  efficiency_gain_savings_per_year_kes: number
  npv_kes: number
  recommendation: string
  breakdown: Record<string, { annual: number; description: string }>
}

const infraLabels: Record<string, string> = {
  power: 'Power Grid',
  water: 'Water Network',
  roads: 'Road Network',
  solid_waste: 'Solid Waste',
  sidewalks: 'Sidewalks',
  lrt: 'LRT',
  sgr: 'SGR',
  airports: 'Airports',
}

export default function RoiCalculator() {
  const [infraType, setInfraType] = useState('power')
  const [options, setOptions] = useState<UpgradeOption[]>([])
  const [selectedOption, setSelectedOption] = useState<number | null>(null)
  const [customCost, setCustomCost] = useState('')
  const [description, setDescription] = useState('')
  const [lifespan, setLifespan] = useState(20)
  const [result, setResult] = useState<RoiResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.roi.upgradeOptions(infraType).then((data: any) => {
      setOptions(Array.isArray(data) ? data : (data?.options || []))
    }).catch(() => {})
    setSelectedOption(null)
    setResult(null)
    setError(null)
  }, [infraType])

  const calculate = async () => {
    const cost = selectedOption !== null ? options[selectedOption].typical_cost_kes : parseFloat(customCost)
    const desc = selectedOption !== null ? options[selectedOption].description : description
    if (!cost || cost <= 0) return

    setLoading(true)
    setError(null)
    try {
      const r = await api.roi.calculate({
        infra_type: infraType,
        asset_id: selectedOption !== null ? options[selectedOption].asset_id : 'custom',
        upgrade_cost_kes: cost,
        upgrade_description: desc || 'Custom upgrade',
        asset_lifespan_years: lifespan,
      }) as unknown as RoiResult
      setResult(r)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'ROI calculation failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-sindio-accent flex items-center gap-2">
        <Calculator className="w-5 h-5" /> Adaptation ROI Calculator
      </h3>

      <div className="flex flex-wrap gap-2">
        {Object.entries(infraLabels).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setInfraType(key)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
              infraType === key
                ? 'border-sindio-accent bg-sindio-accent/10 text-sindio-accent'
                : 'border-sindio-border text-sindio-muted hover:border-sindio-muted'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {options.length > 0 && (
        <div>
          <label className="text-xs text-sindio-muted block mb-2">Upgrade Option</label>
          <div className="space-y-1">
            {options.map((opt, i) => (
              <button
                key={opt.asset_id}
                type="button"
                onClick={() => { setSelectedOption(i); setCustomCost(''); setDescription('') }}
                className={`w-full text-left p-3 rounded-lg border text-xs transition-colors ${
                  selectedOption === i
                    ? 'border-sindio-accent bg-sindio-accent/5'
                    : 'border-sindio-border bg-sindio-dark hover:border-sindio-muted'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-white font-medium">{opt.name}</span>
                  <span className="text-sindio-accent">KSh {opt.typical_cost_kes.toLocaleString()}</span>
                </div>
                <div className="text-sindio-muted mt-1">{opt.description}</div>
                <div className="flex items-center gap-4 mt-1 text-[10px]">
                  <span className="text-green-400">Save ~KSh {opt.typical_annual_savings_kes.toLocaleString()}/yr</span>
                  <span className="text-sindio-muted">Payback: {opt.payback_years}yr</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex items-center gap-3">
        <div className="flex-1">
          <label className="text-xs text-sindio-muted block mb-1">Custom Cost (KES)</label>
          <input
            type="number"
            value={customCost}
            onChange={(e) => { setCustomCost(e.target.value); setSelectedOption(null); setDescription('') }}
            placeholder="e.g. 250000"
            className="w-full bg-sindio-dark border border-sindio-border rounded-lg px-3 py-2 text-sm text-white"
          />
        </div>
        <div className="w-24">
          <label className="text-xs text-sindio-muted block mb-1">Lifespan</label>
          <input
            type="number"
            value={lifespan}
            onChange={(e) => setLifespan(parseInt(e.target.value) || 20)}
            min={5}
            max={50}
            className="w-full bg-sindio-dark border border-sindio-border rounded-lg px-3 py-2 text-sm text-white"
          />
        </div>
        <button
          onClick={calculate}
          disabled={loading || (!selectedOption && !customCost)}
          className="btn-primary text-sm py-2 self-end"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}
          Calculate ROI
        </button>
      </div>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      {result && (
        <div className="space-y-4">
          <div className={`p-3 rounded-lg border text-sm font-medium ${
            result.recommendation === 'high' ? 'border-green-500/30 bg-green-500/10 text-green-400' :
            result.recommendation === 'medium' ? 'border-yellow-500/30 bg-yellow-500/10 text-yellow-400' :
            'border-red-500/30 bg-red-500/10 text-red-400'
          }`}>
            {result.recommendation === 'high' ? '✓ Strong business case — proceed with upgrade' :
             result.recommendation === 'medium' ? '◉ Moderate return — review assumptions' :
             '✗ Low return — reconsider scope'}
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="bg-sindio-dark rounded-lg p-3 border border-sindio-border text-center">
              <div className="text-lg font-bold text-sindio-accent">KSh {Math.round(result.upgrade_cost_kes).toLocaleString()}</div>
              <div className="text-[10px] text-sindio-muted">Upgrade Cost</div>
            </div>
            <div className="bg-sindio-dark rounded-lg p-3 border border-sindio-border text-center">
              <div className="text-lg font-bold text-green-400">KSh {Math.round(result.estimated_annual_savings_kes).toLocaleString()}</div>
              <div className="text-[10px] text-sindio-muted">Annual Savings</div>
            </div>
            <div className="bg-sindio-dark rounded-lg p-3 border border-sindio-border text-center">
              <div className="text-lg font-bold text-yellow-400">{result.payback_period_years}yr</div>
              <div className="text-[10px] text-sindio-muted">Payback Period</div>
            </div>
            <div className="bg-sindio-dark rounded-lg p-3 border border-sindio-border text-center">
              <div className="text-lg font-bold text-green-500">{result.five_year_roi_pct}%</div>
              <div className="text-[10px] text-sindio-muted">5-Year ROI</div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="bg-sindio-dark rounded-lg p-3 border border-sindio-border text-center">
              <div className="text-sm font-bold text-sindio-accent">{result.ten_year_roi_pct}%</div>
              <div className="text-[10px] text-sindio-muted">10-Year ROI</div>
            </div>
            <div className="bg-sindio-dark rounded-lg p-3 border border-sindio-border text-center">
              <div className="text-sm font-bold text-sindio-accent">{result.twenty_year_roi_pct}%</div>
              <div className="text-[10px] text-sindio-muted">20-Year ROI</div>
            </div>
          </div>

          <div>
            <h4 className="text-xs font-medium text-sindio-muted mb-2 flex items-center gap-1">
              <BarChart3 className="w-3.5 h-3.5" /> Savings Breakdown
            </h4>
            <div className="space-y-1">
              {Object.entries(result.breakdown).map(([key, val]) => (
                <div key={key} className="flex items-center justify-between text-xs bg-sindio-dark rounded p-2 border border-sindio-border">
                  <span className="text-sindio-muted">{val.description}</span>
                  <span className="text-green-400">KSh {Math.round(val.annual).toLocaleString()}/yr</span>
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="flex items-center gap-2 bg-sindio-dark rounded-lg p-2 border border-sindio-border">
              <Clock className="w-4 h-4 text-sindio-warning" />
              <div>
                <div className="text-xs font-bold text-white">{result.avoided_outage_days_per_year} days/yr</div>
                <div className="text-[10px] text-sindio-muted">Outages Avoided</div>
              </div>
            </div>
            <div className="flex items-center gap-2 bg-sindio-dark rounded-lg p-2 border border-sindio-border">
              <DollarSign className="w-4 h-4 text-green-400" />
              <div>
                <div className="text-xs font-bold text-white">KSh {Math.round(result.npv_kes).toLocaleString()}</div>
                <div className="text-[10px] text-sindio-muted">NPV (5% discount)</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
