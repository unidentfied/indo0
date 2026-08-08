import { useState, useEffect } from 'react'
import { api } from '../services/api'
import { Workflow, Zap, Droplets, Car, Wifi, Users, Clock, ArrowRight, Loader2, XCircle, ChevronDown } from 'lucide-react'

interface CascadeAsset {
  asset_id: string
  asset_type: string
  name: string
  ward: string
}

interface CascadeResult {
  cascade_chain: Array<{
    asset_id: string
    asset_type: string
    failure_cause: string
    cascade_depth: number
    time_offset_minutes: number
    description: string
  }>
  affected_wards: Record<string, {
    pop_affected: number
    power_out: boolean
    water_out: boolean
    roads_blocked: number
    cell_service_loss: boolean
  }>
  critical_facilities: Array<{
    name: string
    type: string
    ward: string
    impact: string
  }>
  summary: {
    asset_name: string
    asset_type: string
    total_population_affected: number
    sectors_impacted: string[]
    wards: string[]
    cascade_depth: number
    estimated_restoration_hours: number
    critical_facilities_count: number
  }
}

const typeIcons: Record<string, React.ReactNode> = {
  power_substation: <Zap className="w-3.5 h-3.5 text-yellow-400" />,
  water_pump: <Droplets className="w-3.5 h-3.5 text-blue-400" />,
  water_pipe: <Droplets className="w-3.5 h-3.5 text-blue-400" />,
  traffic_signal: <Car className="w-3.5 h-3.5 text-orange-400" />,
  road_cell: <Car className="w-3.5 h-3.5 text-orange-400" />,
  cell_tower: <Wifi className="w-3.5 h-3.5 text-purple-400" />,
}

function getTypeIcon(type: string) {
  for (const [key, icon] of Object.entries(typeIcons)) {
    if (type.includes(key) || key.includes(type)) return icon
  }
  return <XCircle className="w-3.5 h-3.5 text-sindio-muted" />
}

function getTypeColor(type: string): string {
  if (type.includes('power')) return 'border-yellow-500/30 bg-yellow-500/5'
  if (type.includes('water')) return 'border-blue-500/30 bg-blue-500/5'
  if (type.includes('road') || type.includes('signal')) return 'border-orange-500/30 bg-orange-500/5'
  if (type.includes('cell')) return 'border-purple-500/30 bg-purple-500/5'
  return 'border-sindio-border bg-sindio-panel'
}

export default function CascadePanel() {
  const [assets, setAssets] = useState<CascadeAsset[]>([])
  const [selectedAsset, setSelectedAsset] = useState('power_substation:Ngong_Substation')
  const [result, setResult] = useState<CascadeResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.cascade.assets().then((raw: unknown) => {
      const data = raw as Record<string, unknown>
      const assetsWrapper = data.assets as Record<string, unknown[]> | undefined
      if (!assetsWrapper) return
      const substations = (assetsWrapper.power_substations || []) as Record<string, unknown>[]
      const pumps = (assetsWrapper.water_pumps || []) as Record<string, unknown>[]
      const flat = [...substations, ...pumps].map(a => {
        const servesWards = a.serves_wards as string[] | undefined
        return {
          asset_id: a.asset_id as string,
          asset_type: a.type as string,
          name: a.name as string,
          ward: (a.wards_count as number || servesWards?.[0] || '') as string,
        }
      }) as CascadeAsset[]
      setAssets(flat)
    }).catch(() => {})
  }, [])

  const analyze = async () => {
    setLoading(true)
    setError(null)
    try {
      const [assetType, assetId] = selectedAsset.includes(':') ? selectedAsset.split(':', 2) : ['power_substation', selectedAsset]
      const r = await api.cascade.analyze(assetType, assetId) as unknown as CascadeResult
      setResult(r)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Cascade analysis failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (assets.length > 0 && !selectedAsset) setSelectedAsset(`${assets[0].asset_type}:${assets[0].asset_id}`)
  }, [assets])

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent flex items-center gap-2">
        <Workflow className="w-4 h-4" /> Cascade Failure Analysis
      </h3>

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs text-sindio-muted block mb-1">Select Asset</label>
          <div className="relative">
            <select
              value={selectedAsset}
              onChange={(e) => setSelectedAsset(e.target.value)}
              className="w-full bg-sindio-dark border border-sindio-border rounded-lg px-3 py-2 text-sm text-white appearance-none cursor-pointer"
            >
              <optgroup label="Power Substations">
                {assets.filter(a => a.asset_type === 'power_substation').map(a => (
                  <option key={a.asset_id} value={`power_substation:${a.asset_id}`}>{a.name}</option>
                ))}
              </optgroup>
              <optgroup label="Water Pumps">
                {assets.filter(a => a.asset_type === 'water_pump').map(a => (
                  <option key={a.asset_id} value={`water_pump:${a.asset_id}`}>{a.name}</option>
                ))}
              </optgroup>
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-sindio-muted pointer-events-none" />
          </div>
        </div>
        <button
          onClick={analyze}
          disabled={loading}
          className="btn-primary text-sm py-2"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}
          Analyze Cascade
        </button>
      </div>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      {result && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <div className="bg-sindio-dark rounded-lg p-3 border border-sindio-border text-center">
              <div className="text-lg font-bold text-red-400">{result.summary.total_population_affected.toLocaleString()}</div>
              <div className="text-[10px] text-sindio-muted">People Affected</div>
            </div>
            <div className="bg-sindio-dark rounded-lg p-3 border border-sindio-border text-center">
              <div className="text-lg font-bold text-yellow-400">{result.summary.sectors_impacted.length}</div>
              <div className="text-[10px] text-sindio-muted">Sectors Disrupted</div>
            </div>
            <div className="bg-sindio-dark rounded-lg p-3 border border-sindio-border text-center">
              <div className="text-lg font-bold text-sindio-accent">{result.summary.wards.length}</div>
              <div className="text-[10px] text-sindio-muted">Wards Affected</div>
            </div>
            <div className="bg-sindio-dark rounded-lg p-3 border border-sindio-border text-center">
              <div className="text-lg font-bold text-sindio-warning">{result.summary.cascade_depth}</div>
              <div className="text-[10px] text-sindio-muted">Cascade Depth</div>
            </div>
            <div className="bg-sindio-dark rounded-lg p-3 border border-sindio-border text-center">
              <div className="text-lg font-bold text-sindio-accent">{result.summary.estimated_restoration_hours}h</div>
              <div className="text-[10px] text-sindio-muted">Est. Restoration</div>
            </div>
          </div>

          <div>
            <h4 className="text-sm font-medium text-sindio-muted mb-2 flex items-center gap-1">
              <Users className="w-4 h-4" /> Cascading Failure Chain
            </h4>
            <div className="space-y-1 max-h-80 overflow-y-auto">
              {result.cascade_chain.map((event, i) => (
                <div
                  key={i}
                  className={`flex items-center gap-3 p-2 rounded border-l-2 text-xs ${getTypeColor(event.asset_type)}`}
                >
                  <span className="text-[10px] text-sindio-muted w-6 text-right">+{event.time_offset_minutes}m</span>
                  {getTypeIcon(event.asset_type)}
                  <span className="text-sindio-text flex-1">{event.description}</span>
                  {event.cascade_depth > 0 && (
                    <span className="text-[10px] bg-sindio-accent/10 text-sindio-accent px-1.5 py-0.5 rounded">
                      L{event.cascade_depth}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div>
            <h4 className="text-sm font-medium text-sindio-muted mb-2">Affected Wards</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {Object.entries(result.affected_wards).map(([ward, info]) => (
                <div key={ward} className="bg-sindio-dark rounded-lg p-3 border border-sindio-border">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium text-white">{ward}</span>
                    <span className="text-xs text-sindio-muted">{info.pop_affected.toLocaleString()} people</span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px]">
                    {info.power_out && <span className="text-yellow-400 bg-yellow-400/10 px-1.5 py-0.5 rounded">No Power</span>}
                    {info.water_out && <span className="text-blue-400 bg-blue-400/10 px-1.5 py-0.5 rounded">No Water</span>}
                    {info.roads_blocked > 0 && <span className="text-orange-400 bg-orange-400/10 px-1.5 py-0.5 rounded">{info.roads_blocked} Roads</span>}
                    {info.cell_service_loss && <span className="text-purple-400 bg-purple-400/10 px-1.5 py-0.5 rounded">No Cell</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {result.critical_facilities.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-sindio-muted mb-2 flex items-center gap-1">
                <Clock className="w-4 h-4" /> Critical Facilities at Risk
              </h4>
              <div className="space-y-1">
                {result.critical_facilities.map((fac, i) => (
                  <div key={i} className="flex items-center justify-between bg-sindio-dark rounded p-2 border border-sindio-border text-xs">
                    <span className="text-white">{fac.name}</span>
                    <span className="text-sindio-muted capitalize">{fac.type}</span>
                    <span className="text-red-400 text-[10px]">{fac.impact}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
