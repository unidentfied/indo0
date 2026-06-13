import { useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { Gauge, ArrowDownToLine, Loader2 } from 'lucide-react'
import type { SimulationResult } from '../types'

type NetId = 'power' | 'water' | 'roads' | 'solid_waste' | 'sidewalks' | 'lrt' | 'sgr' | 'airports'

const networks: { id: NetId; label: string }[] = [
  { id: 'power', label: 'Power' },
  { id: 'water', label: 'Water' },
  { id: 'roads', label: 'Roads' },
  { id: 'solid_waste', label: 'Waste' },
  { id: 'sidewalks', label: 'Sidewalks' },
  { id: 'lrt', label: 'LRT' },
  { id: 'sgr', label: 'SGR' },
  { id: 'airports', label: 'Airports' },
]

export default function SimulationChart({
  result,
  loading,
}: {
  result?: SimulationResult
  loading?: boolean
}) {
  const [network, setNetwork] = useState<NetId>('power')

  const data = result?.projected_impacts && result.projected_impacts.length > 0
    ? result.projected_impacts
    : []

  const handleDownload = () => {
    if (data.length === 0) return
    const csv = 'time,load\n' + data.map(d => `${d.time},${d.load}`).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'sindio-simulation-impact.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="panel p-5">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <Gauge className="w-4 h-4 text-sindio-accent" />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Projected Impact</h3>
        </div>
        {data.length > 0 && (
          <button
            onClick={handleDownload}
            className="text-xs text-sindio-muted hover:text-sindio-accent flex items-center gap-1 transition-colors"
          >
            <ArrowDownToLine className="w-3 h-3" />
            Download Data
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-5">
        <span className="text-[10px] uppercase text-sindio-muted font-medium mr-1">Network</span>
        {networks.map((n) => (
          <button
            key={n.id}
            onClick={() => setNetwork(n.id)}
            className={`px-2.5 py-1 text-xs rounded-md border transition-all ${
              network === n.id
                ? 'bg-sindio-accent/10 border-sindio-accent/50 text-sindio-accent shadow-sm'
                : 'border-sindio-border text-sindio-muted hover:text-sindio-text hover:border-sindio-muted/50'
            }`}
          >
            {n.label}
          </button>
        ))}
      </div>

      {result && (
        <div className="text-xs text-sindio-muted mb-4 flex items-center gap-1.5">
          <span className="w-1 h-1 rounded-full bg-sindio-accent" />
          Stress Factor: {result.stress_factor}
        </div>
      )}

      <div className="h-52">
        {loading ? (
          <div className="h-full flex items-center justify-center">
            <div className="flex flex-col items-center gap-2 text-sindio-muted">
              <Loader2 className="w-5 h-5 animate-spin" />
              <span className="text-xs">Simulation in progress...</span>
            </div>
          </div>
        ) : data.length === 0 ? (
          <div className="h-full flex items-center justify-center text-xs text-sindio-muted">
            Run a simulation to see projected impacts
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--sindio-border)" vertical={false} opacity={0.5} />
              <XAxis dataKey="time" tick={{ fill: 'var(--sindio-muted)', fontSize: 11 }} axisLine={{ stroke: 'var(--sindio-border)', opacity: 0.3 }} tickLine={false} />
              <YAxis tick={{ fill: 'var(--sindio-muted)', fontSize: 11 }} axisLine={{ stroke: 'var(--sindio-border)', opacity: 0.3 }} tickLine={false} width={35} />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'var(--sindio-panel)',
                  border: '1px solid var(--sindio-border)',
                  borderRadius: '8px',
                  color: 'var(--sindio-text)',
                  fontSize: '12px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                }}
                cursor={{ fill: 'var(--sindio-border)', opacity: 0.15 }}
              />
              <Bar dataKey="load" fill="var(--sindio-accent)" radius={[4, 4, 0, 0]} maxBarSize={48} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {result?.failure_risk && (
        <div className="mt-4 flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${
            result.failure_risk === 'high' ? 'bg-sindio-critical' :
            result.failure_risk === 'medium' ? 'bg-sindio-warning' : 'bg-emerald-400'
          }`} />
          <span className="text-xs text-sindio-muted">
            Failure risk: <span className="font-semibold text-sindio-text">{result.failure_risk}</span>
          </span>
          {result.recommendation && (
            <span className="text-xs text-sindio-muted ml-2 truncate max-w-xs">{result.recommendation}</span>
          )}
        </div>
      )}
    </div>
  )
}
