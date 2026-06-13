import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import MetricCard from '../components/MetricCard'
import AlertPanel from '../components/AlertPanel'
import SimulationChart from '../components/SimulationChart'
import StressMap from '../components/StressMap'
import SimulationPanel from '../components/SimulationPanel'
import AlertFeed from '../components/AlertFeed'
import MonitorOverview from '../components/MonitorOverview'
import ScheduleStatus from '../components/ScheduleStatus'
import ClassificationPanel from '../components/ClassificationPanel'
import type { Metric, Alert, SimulationResult, InfrastructureStatus, SimulationSummary } from '../types'
import { Gauge, AlertTriangle, AlertOctagon, Loader2 } from 'lucide-react'

const infraTitles: Record<string, string> = {
  power: 'Power System Analysis',
  water: 'Water Grid Analysis',
  roads: 'Road Network Analysis',
  solid_waste: 'Solid Waste Analysis',
  sidewalks: 'Sidewalks Analysis',
  lrt: 'LRT Train Analysis',
  sgr: 'SGR Train Analysis',
  airports: 'Airport Analysis',
}

const infraDescriptions: Record<string, string> = {
  power: 'Real-time grid stability monitoring with predictive overload detection and cascading failure analysis across 14,204 nodes.',
  water: 'Pressure stability tracking and leak detection across 8,432 sensor nodes with flow rate optimization.',
  roads: 'Traffic flow monitoring across 3,210 junctions with congestion prediction and rerouting recommendations.',
  solid_waste: 'Collection route optimization and capacity monitoring for 156 active waste transfer stations.',
  sidewalks: 'Pedestrian flow analysis and obstruction detection across 2,840 monitored walkway segments.',
  lrt: 'Train scheduling and signal monitoring across 24 stations with delay prediction and maintenance alerts.',
  sgr: 'Track integrity monitoring and freight/passenger scheduling across 48 sensor-equipped track sections.',
  airports: 'Flight throughput monitoring and runway status tracking with maintenance window planning.',
}

export default function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeSystem, setActiveSystem] = useState(searchParams.get('system') || 'power')
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [simulation, setSimulation] = useState<SimulationResult | undefined>()
  const [infra, setInfra] = useState<InfrastructureStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [simLoading, setSimLoading] = useState(false)

  // Sync URL → state (Navbar tabs use Link which changes URL directly)
  useEffect(() => {
    const fromUrl = searchParams.get('system')
    if (fromUrl) {
      setActiveSystem(prev => fromUrl !== prev ? fromUrl : prev)
    }
  }, [searchParams, setActiveSystem])

  // Sync state → URL (Sidebar calls onSelect which sets state directly)
  useEffect(() => {
    setSearchParams(prev => { const n = new URLSearchParams(prev); n.set('system', activeSystem); return n })
  }, [activeSystem])

  useEffect(() => {
    setLoading(true)
    const promises = [
      fetch(`/api/dashboard/metrics?system=${activeSystem}`)
        .then(r => r.ok ? r.json() : Promise.reject())
        .catch(() => []),
      fetch('/api/dashboard/alerts')
        .then(r => r.ok ? r.json() : Promise.reject())
        .catch(() => []),
      fetch(`/api/infrastructure/${activeSystem}`)
        .then(r => r.ok ? r.json() : Promise.reject())
        .catch(() => null),
    ]

    Promise.all(promises).then(([m, a, i]) => {
      setMetrics(m)
      setAlerts(a)
      setInfra(i)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [activeSystem])

  const handleSimulationComplete = (summary: SimulationSummary, result: SimulationResult | null) => {
    if (result) setSimulation(result)
    if (summary.total_alerts_generated > 0) {
      setAlerts(prev => [
        { id: `sim-${summary.task_id}`, timestamp: new Date().toISOString(), level: 'advisory',
          category: 'utilities', title: summary.summary_text,
          description: `${summary.total_alerts_generated} stress points identified across ${Object.values(summary.alerts_by_type).filter(v => v > 0).length} infrastructure types.` },
        ...prev,
      ])
    }
    setSimLoading(false)
  }

  const riskAlerts = alerts.filter(a => a.level !== 'advisory').slice(0, 3)
  const showAlertFeed = activeSystem === 'alerts'
  const title = infraTitles[activeSystem] || 'Infrastructure Analysis'

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-sindio-dark">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 text-sindio-accent animate-spin" />
          <span className="text-sm text-sindio-muted">Loading {infraTitles[activeSystem] || 'dashboard'}...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-1 w-full">
      <Sidebar activeSystem={activeSystem} onSelect={setActiveSystem} />
      {showAlertFeed ? (
        <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-6xl">
          <AlertFeed />
        </main>
      ) : (
        <main className="flex-1 p-4 sm:p-6 lg:p-8">
          <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 mb-6">
            <div>
              <h1 className="text-3xl font-bold mb-2">{title}</h1>
              <p className="text-sindio-muted text-sm max-w-xl">
                {infraDescriptions[activeSystem] || 'Real-time predictive simulation of load distribution and infrastructure resilience.'}
              </p>
            </div>
            {infra && (
              <div className="flex items-center gap-3">
                <div className="panel px-4 py-2">
                  <div className="text-[10px] uppercase text-sindio-muted">Stability</div>
                  <div className="text-lg font-semibold text-emerald-400">{infra.grid_stability}%</div>
                </div>
                <div className="panel px-4 py-2">
                  <div className="text-[10px] uppercase text-sindio-muted">Load</div>
                  <div className="text-lg font-semibold">{infra.current_load}</div>
                </div>
                <div className="panel px-4 py-2">
                  <div className="text-[10px] uppercase text-sindio-muted">Nodes</div>
                  <div className="text-lg font-semibold">{infra.active_nodes.toLocaleString()}</div>
                </div>
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            {metrics.map(m => <MetricCard key={m.label} metric={m} />)}
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-6">
            <div className="xl:col-span-1 space-y-4">
              <SimulationPanel onSimulationComplete={handleSimulationComplete} />
              <MonitorOverview />
              <div className="panel">
                <div className="p-4 border-b border-sindio-border flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-sindio-warning" />
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-warning">Critical Risk Feed</h3>
                  </div>
                  <span className="text-[10px] bg-sindio-critical/10 text-sindio-critical px-2 py-0.5 rounded uppercase font-bold">{riskAlerts.length} Active</span>
                </div>
                <div className="divide-y divide-sindio-border">
                  {riskAlerts.map(a => (
                    <div key={a.id} className="p-4">
                      <div className="flex items-start gap-3">
                        <div className={`mt-0.5 ${a.level === 'critical' ? 'text-sindio-critical' : 'text-sindio-warning'}`}>
                          {a.level === 'critical' ? <AlertOctagon className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
                        </div>
                        <div>
                          <h4 className="text-sm font-medium mb-1">{a.title}</h4>
                          <p className="text-xs text-sindio-muted">{a.description}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                  {riskAlerts.length === 0 && (
                    <div className="p-4 text-xs text-sindio-muted text-center">No active critical or warning alerts.</div>
                  )}
                </div>
              </div>
            </div>

            <div className="xl:col-span-2">
              <div className="panel p-3 mb-4">
                <div className="flex items-center gap-2">
                  <Gauge className="w-4 h-4 text-sindio-accent" />
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Infrastructure Stress Map</h3>
                  {infra && (
                    <div className="ml-auto flex items-center gap-3">
                      <div className="text-xs text-sindio-muted">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block mr-1" />
                        {infra.active_nodes.toLocaleString()} nodes scanned
                      </div>
                    </div>
                  )}
                </div>
              </div>
              <StressMap />
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-6">
            <div className="xl:col-span-2">
              <SimulationChart result={simulation} />
            </div>
            <div className="space-y-6">
              <AlertPanel alerts={alerts} />
              <ScheduleStatus />
            </div>
          </div>

          <ClassificationPanel />
        </main>
      )}
    </div>
  )
}
