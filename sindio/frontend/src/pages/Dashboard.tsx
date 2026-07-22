import { useState, useEffect, lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import MetricCard from '../components/MetricCard'
import AlertPanel from '../components/AlertPanel'
import type { Metric, Alert, SimulationResult, InfrastructureStatus, SimulationSummary } from '../types'
import { api } from '../services/api'
import { Gauge, AlertTriangle, AlertOctagon, Loader2, Server, Activity, BarChart3, Clock } from 'lucide-react'

const StressMap = lazy(() => import('../components/StressMap'))
const SimulationChart = lazy(() => import('../components/SimulationChart'))
const SimulationPanel = lazy(() => import('../components/SimulationPanel'))
const MonitorOverview = lazy(() => import('../components/MonitorOverview'))
const ScheduleStatus = lazy(() => import('../components/ScheduleStatus'))
const AlertFeed = lazy(() => import('../components/AlertFeed'))
const ClassificationPanel = lazy(() => import('../components/ClassificationPanel'))

function SkeletonBlock({ className = '' }: { className?: string }) {
  return <div className={`panel animate-pulse bg-sindio-panel ${className}`}>
    <div className="p-4 border-b border-sindio-border">
      <div className="h-4 w-32 bg-sindio-border rounded" />
    </div>
    <div className="p-4 space-y-3">
      <div className="h-3 w-full bg-sindio-border rounded" />
      <div className="h-3 w-3/4 bg-sindio-border rounded" />
      <div className="h-3 w-1/2 bg-sindio-border rounded" />
    </div>
  </div>
}

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
  const activeSystem = searchParams.get('system') || 'power'

  const setActiveSystem = (system: string) => {
    setSearchParams(prev => { const n = new URLSearchParams(prev); n.set('system', system); return n }, { replace: true })
  }

  const [metrics, setMetrics] = useState<Metric[]>([])
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [simulation, setSimulation] = useState<SimulationResult | undefined>()
  const [infra, setInfra] = useState<InfrastructureStatus | null>(null)
  const [metricsReady, setMetricsReady] = useState(false)
  const [alertsReady, setAlertsReady] = useState(false)
  const [infraLoading, setInfraLoading] = useState(true)

  useEffect(() => {
    setMetricsReady(false)
    setAlertsReady(false)
    setInfraLoading(true)
    setInfra(null)

    api.dashboard.metrics(activeSystem)
      .then(m => { setMetrics(m); setMetricsReady(true) })
      .catch(err => { console.error('[Dashboard] metrics error:', err); setMetricsReady(true) })

    api.dashboard.alerts()
      .then(a => { setAlerts(a); setAlertsReady(true) })
      .catch(err => { console.error('[Dashboard] alerts error:', err); setAlertsReady(true) })

    api.infrastructure.status(activeSystem)
      .then(i => { setInfra(i); setInfraLoading(false) })
      .catch(err => { console.error('[Dashboard] infrastructure error:', err); setInfraLoading(false) })
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
  }

  const riskAlerts = alerts.filter(a => a.level !== 'advisory').slice(0, 3)
  const showAlertFeed = activeSystem === 'alerts'
  const title = infraTitles[activeSystem] || 'Infrastructure Analysis'

  return (
    <div className="flex flex-1 w-full">
      <Sidebar activeSystem={activeSystem} onSelect={setActiveSystem} />
      {showAlertFeed ? (
        <main className="flex-1 p-4 sm:p-6 lg:p-6 max-w-6xl">
          <Suspense fallback={<SkeletonBlock className="h-96" />}>
            <AlertFeed />
          </Suspense>
        </main>
      ) : (
        <main className="flex-1 p-4 sm:p-8 lg:p-12">
          <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 mb-8">
            <div>
              <h1 className="text-3xl font-bold mb-2">{title}</h1>
              <p className="text-sindio-muted text-sm max-w-xl">
                {infraDescriptions[activeSystem] || 'Real-time predictive simulation of load distribution and infrastructure resilience.'}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="panel px-4 py-2">
                <div className="text-[10px] uppercase text-sindio-muted">Stability</div>
                <div className="text-lg font-semibold text-emerald-400">
                  {infraLoading ? <span className="animate-pulse">—</span> : infra ? `${infra.grid_stability}%` : '—'}
                </div>
              </div>
              <div className="panel px-4 py-2">
                <div className="text-[10px] uppercase text-sindio-muted">Load</div>
                <div className="text-lg font-semibold">
                  {infraLoading ? <span className="animate-pulse">—</span> : infra ? infra.current_load : '—'}
                </div>
              </div>
              <div className="panel px-4 py-2">
                <div className="text-[10px] uppercase text-sindio-muted">Nodes</div>
                <div className="text-lg font-semibold">
                  {infraLoading ? <span className="animate-pulse">—</span> : infra ? infra.active_nodes.toLocaleString() : '—'}
                </div>
              </div>
            </div>
          </div>

          {/* ── Mini summary cards ── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <div className="panel p-4 flex items-center gap-3">
              <div className="w-10 h-10 rounded bg-sindio-accent/10 flex items-center justify-center text-sindio-accent">
                <Server className="w-5 h-5" />
              </div>
              <div>
                <div className="text-lg font-bold">
                  {infraLoading ? <span className="animate-pulse">—</span> : infra ? infra.active_nodes.toLocaleString() : '—'}
                </div>
                <div className="text-[10px] uppercase text-sindio-muted tracking-wider">Assets Monitored</div>
              </div>
            </div>

            <div className="panel p-4 flex items-center gap-3">
              <div className={`w-10 h-10 rounded flex items-center justify-center ${infra ? (infra.grid_stability > 85 ? 'bg-emerald-400/10 text-emerald-400' : infra.grid_stability > 70 ? 'bg-yellow-400/10 text-yellow-400' : 'bg-red-400/10 text-red-400') : 'bg-sindio-border/20 text-sindio-muted'}`}>
                <Activity className="w-5 h-5" />
              </div>
              <div>
                <div className="text-lg font-bold">
                  {infraLoading ? <span className="animate-pulse">—</span> : infra ? `${infra.grid_stability}%` : '—'}
                </div>
                <div className="text-[10px] uppercase text-sindio-muted tracking-wider">Grid Stability</div>
              </div>
            </div>

            <div className="panel p-4 flex items-center gap-3">
              <div className={`w-10 h-10 rounded flex items-center justify-center ${infra ? (infra.capacity_percent < 70 ? 'bg-emerald-400/10 text-emerald-400' : infra.capacity_percent < 85 ? 'bg-yellow-400/10 text-yellow-400' : 'bg-red-400/10 text-red-400') : 'bg-sindio-border/20 text-sindio-muted'}`}>
                <BarChart3 className="w-5 h-5" />
              </div>
              <div>
                <div className="text-lg font-bold">
                  {infraLoading ? <span className="animate-pulse">—</span> : infra ? `${infra.capacity_percent}%` : '—'}
                </div>
                <div className="text-[10px] uppercase text-sindio-muted tracking-wider">Capacity Load</div>
              </div>
            </div>

            <div className="panel p-4 flex items-center gap-3">
              <div className={`w-10 h-10 rounded flex items-center justify-center ${infra ? (infra.latency_ms < 20 ? 'bg-emerald-400/10 text-emerald-400' : infra.latency_ms < 40 ? 'bg-yellow-400/10 text-yellow-400' : 'bg-red-400/10 text-red-400') : 'bg-sindio-border/20 text-sindio-muted'}`}>
                <Clock className="w-5 h-5" />
              </div>
              <div>
                <div className="text-lg font-bold">
                  {infraLoading ? <span className="animate-pulse">—</span> : infra ? `${infra.latency_ms}ms` : '—'}
                </div>
                <div className="text-[10px] uppercase text-sindio-muted tracking-wider">Response Time</div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            {metricsReady
              ? metrics.map(m => <MetricCard key={m.label} metric={m} />)
              : Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="panel p-4 animate-pulse">
                    <div className="h-3 w-16 bg-sindio-border rounded mb-2" />
                    <div className="h-6 w-24 bg-sindio-border rounded mb-1" />
                    <div className="h-3 w-12 bg-sindio-border rounded" />
                  </div>
                ))
            }
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-8 mb-8">
            <div className="xl:col-span-1 space-y-4">
              <Suspense fallback={<SkeletonBlock />}>
                <SimulationPanel onSimulationComplete={handleSimulationComplete} />
              </Suspense>
              <Suspense fallback={<SkeletonBlock />}>
                <MonitorOverview />
              </Suspense>
              <div className="panel">
                <div className="p-4 border-b border-sindio-border flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-sindio-warning" />
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-warning">Critical Risk Feed</h3>
                  </div>
                  <span className="text-[10px] bg-sindio-critical/10 text-sindio-critical px-2 py-0.5 rounded uppercase font-bold">{riskAlerts.length} Active</span>
                </div>
                <div className="divide-y divide-sindio-border">
                  {alertsReady
                    ? riskAlerts.map(a => (
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
                      ))
                      : Array.from({ length: 3 }).map((_, i) => (
                          <div key={i} className="p-4 animate-pulse">
                            <div className="flex items-start gap-3">
                              <div className="w-4 h-4 bg-sindio-border rounded mt-0.5" />
                              <div className="flex-1 space-y-2">
                                <div className="h-4 w-32 bg-sindio-border rounded" />
                                <div className="h-3 w-full bg-sindio-border rounded" />
                              </div>
                            </div>
                          </div>
                        ))
                  }
                  {alertsReady && riskAlerts.length === 0 && (
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
              <Suspense fallback={
                <div className="panel h-[500px] lg:h-[600px] flex items-center justify-center">
                  <Loader2 className="w-8 h-8 text-sindio-accent animate-spin" />
                </div>
              }>
                <StressMap />
              </Suspense>
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-8 mb-8">
            <div className="xl:col-span-2">
              <Suspense fallback={<SkeletonBlock className="h-52" />}>
                <SimulationChart result={simulation} />
              </Suspense>
            </div>
            <div className="space-y-6">
              {alertsReady
                ? <AlertPanel alerts={alerts} />
                : <div className="panel p-6 animate-pulse">
                    <div className="h-4 w-24 bg-sindio-border rounded mb-3" />
                    <div className="space-y-2">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <div key={i} className="h-8 bg-sindio-border rounded" />
                      ))}
                    </div>
                  </div>
              }
              <Suspense fallback={<SkeletonBlock />}>
                <ScheduleStatus />
              </Suspense>
            </div>
          </div>

          <Suspense fallback={<SkeletonBlock className="h-96" />}>
            <ClassificationPanel />
          </Suspense>
        </main>
      )}
    </div>
  )
}
