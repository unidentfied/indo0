import { X, Activity, Info } from 'lucide-react'
import type { AssetDetail } from '../types'

interface StressDrawerProps {
  asset: AssetDetail | null
  onClose: () => void
}

function stressColor(s: number): string {
  if (s >= 80) return 'text-sindio-critical'
  if (s >= 60) return 'text-sindio-warning'
  if (s >= 40) return 'text-yellow-400'
  return 'text-emerald-400'
}

function stressBg(s: number): string {
  if (s >= 80) return 'bg-sindio-critical'
  if (s >= 60) return 'bg-sindio-warning'
  if (s >= 40) return 'bg-yellow-400'
  return 'bg-emerald-400'
}

function maxStress(ts: { stress: number }[]): number {
  return Math.max(...ts.map(t => t.stress), 100)
}

export default function StressDrawer({ asset, onClose }: StressDrawerProps) {
  if (!asset) return null

  const chartH = 160
  const chartW = 280
  const points = asset.timeseries
  const maxS = maxStress(points)
  const padX = 40
  const padY = 20

  const xScale = (i: number) => padX + (i / Math.max(points.length - 1, 1)) * (chartW - padX * 2)
  const yScale = (v: number) => chartH - padY - (v / maxS) * (chartH - padY * 2)

  const linePath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xScale(i)} ${yScale(p.stress)}`)
    .join(' ')

  const areaPath = linePath + ` L ${xScale(points.length - 1)} ${chartH - padY} L ${padX} ${chartH - padY} Z`

  return (
    <div className="fixed inset-y-0 right-0 w-full max-w-sm panel border-l border-sindio-border z-50 overflow-y-auto shadow-2xl animate-slide-in">
      <div className="sticky top-0 bg-sindio-dark p-4 border-b border-sindio-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-sindio-accent" />
          <h2 className="text-sm font-semibold uppercase tracking-wider">Asset Detail</h2>
        </div>
        <button onClick={onClose} className="text-sindio-muted hover:text-sindio-text transition-colors">
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="p-4 space-y-5">
        {/* Header */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs uppercase text-sindio-muted">{asset.system_type}</span>
            <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded ${asset.stress >= 80 ? 'bg-sindio-critical/10 text-sindio-critical' : asset.stress >= 60 ? 'bg-sindio-warning/10 text-sindio-warning' : 'bg-emerald-400/10 text-emerald-400'}`}>
              {asset.classification}
            </span>
          </div>
          <h3 className="text-lg font-bold">{asset.node_name}</h3>
          <p className="text-xs text-sindio-muted">
            {asset.lat.toFixed(4)}, {asset.lng.toFixed(4)}
          </p>
        </div>

        {/* Stress gauge */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] uppercase text-sindio-muted">Current Stress</span>
            <span className={`text-sm font-bold ${stressColor(asset.stress)}`}>
              {asset.stress}%
            </span>
          </div>
          <div className="h-2 bg-sindio-border rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${stressBg(asset.stress)}`}
              style={{ width: `${Math.min(asset.stress, 100)}%` }}
            />
          </div>
        </div>

        {/* Timeseries chart */}
        <div>
          <h4 className="text-[10px] uppercase text-sindio-muted mb-2 font-semibold">24h Stress Trend</h4>
          <svg viewBox={`0 0 ${chartW} ${chartH}`} className="w-full" preserveAspectRatio="xMidYMid meet">
            {/* Grid lines */}
            {[0, 0.25, 0.5, 0.75, 1].map(pct => (
              <g key={pct}>
                <line
                  x1={padX} y1={yScale(maxS * pct)}
                  x2={chartW - padX} y2={yScale(maxS * pct)}
                  stroke="var(--sindio-border)" strokeWidth="1"
                />
                <text x={padX - 8} y={yScale(maxS * pct) + 4} fill="#64748b" fontSize="9" textAnchor="end">
                  {Math.round(maxS * pct)}
                </text>
              </g>
            ))}
            {/* Area */}
            <path d={areaPath} fill="url(#stressGradient)" opacity="0.3" />
            {/* Line */}
            <path d={linePath} fill="none" stroke="#3b82f6" strokeWidth="2" />
            {/* Dots */}
            {points.map((p, i) => (
              <circle key={i} cx={xScale(i)} cy={yScale(p.stress)} r="3" fill="#3b82f6" />
            ))}
            <defs>
              <linearGradient id="stressGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ef4444" />
                <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
              </linearGradient>
            </defs>
          </svg>
        </div>

        {/* RAG Explanation */}
        <div className="panel p-3 bg-sindio-dark">
          <div className="flex items-center gap-2 mb-2">
            <Info className="w-3.5 h-3.5 text-sindio-accent" />
            <h4 className="text-[10px] uppercase text-sindio-muted font-semibold">RAG Explanation</h4>
          </div>
          <p className="text-xs text-sindio-text leading-relaxed">{asset.explanation}</p>
        </div>

        {/* Recommendation */}
        <div className="panel p-3 bg-sindio-accent/5 border-sindio-accent/20">
          <h4 className="text-[10px] uppercase text-sindio-accent font-semibold mb-1">Recommendation</h4>
          <p className="text-xs text-sindio-text leading-relaxed">{asset.recommendation}</p>
        </div>
      </div>
    </div>
  )
}
