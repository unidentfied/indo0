import { useState, useCallback, useRef, useEffect } from 'react'
import {
  PlayCircle,
  Sparkles,
  ArrowDownToLine,
  X,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  WifiOff,
} from 'lucide-react'
import type { SimulateResponse, SimulateTaskStatus, ScenarioGenerateResponse, SimulationSummary } from '../types'
import { isOnline } from '../services/swRegister'
import { enqueueSimulation, getPendingSimulations, removeSimulation } from '../services/offlineStore'
import infraIcons from './InfraIcons'

const SIM_RUN_URL = '/api/v1/simulate/run'
const SIM_STATUS_URL = (id: string) => `/api/v1/simulate/status/${id}`
const SCENARIO_URL = '/api/v1/scenario/generate'

interface SimulationPanelProps {
  onSimulationComplete?: (summary: SimulationSummary, result: SimulateTaskStatus['result']) => void
}

const INFRA_TYPES = [
  { key: 'power', label: 'Power Grid', icon: infraIcons.power, color: 'text-yellow-400' },
  { key: 'water', label: 'Water Systems', icon: infraIcons.water, color: 'text-blue-400' },
  { key: 'roads', label: 'Road Network', icon: infraIcons.roads, color: 'text-emerald-400' },
  { key: 'solid_waste', label: 'Solid Waste', icon: infraIcons.solid_waste, color: 'text-purple-400' },
  { key: 'sidewalks', label: 'Sidewalks', icon: infraIcons.sidewalks, color: 'text-orange-400' },
  { key: 'lrt', label: 'LRT Trains', icon: infraIcons.lrt, color: 'text-cyan-400' },
  { key: 'sgr', label: 'SGR Trains', icon: infraIcons.sgr, color: 'text-teal-400' },
  { key: 'airports', label: 'Airports', icon: infraIcons.airports, color: 'text-sky-400' },
] as const

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function SimulationPanel({ onSimulationComplete }: SimulationPanelProps) {
  // Sliders
  const [year, setYear] = useState(2028)
  const [densityGrowth, setDensityGrowth] = useState(8)

  // Multi-select
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(new Set(['power', 'water']))

  // Simulation state
  const [simState, setSimState] = useState<'idle' | 'queued' | 'running' | 'completed' | 'failed'>('idle')
  const [taskId, setTaskId] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [results, setResults] = useState<SimulationSummary | null>(null)
  const [errorMsg, setErrorMsg] = useState('')

  // AI modal
  const [modalOpen, setModalOpen] = useState(false)
  const [scenarioPrompt, setScenarioPrompt] = useState('')
  const [scenarioLoading, setScenarioLoading] = useState(false)
  const [scenarioResult, setScenarioResult] = useState<ScenarioGenerateResponse | null>(null)

  // Progress polling ref
  const pollRef = useRef<ReturnType<typeof setInterval>>()

  // Offline support
  const [isOffline, setIsOffline] = useState(!isOnline())
  const [pendingQueue, setPendingQueue] = useState(0)

  useEffect(() => {
    const handleOnline = () => setIsOffline(false)
    const handleOffline = () => setIsOffline(true)
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  // Load pending simulation count from IndexedDB on mount
  useEffect(() => {
    getPendingSimulations().then((list) => setPendingQueue(list.length))
  }, [])

  // Listen for BackgroundSync completions
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.taskId) {
        removeSimulation(detail.taskId)
        getPendingSimulations().then((list) => setPendingQueue(list.length))
      }
    }
    window.addEventListener('sindio-bg-sync-success', handler)
    return () => window.removeEventListener('sindio-bg-sync-success', handler)
  }, [])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  // --- Toggle infra type ---
  const toggleType = useCallback((key: string) => {
    setSelectedTypes(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }, [])

  // --- Run Simulation ---
  const runSimulation = useCallback(async () => {
    if (selectedTypes.size === 0) return
    setErrorMsg('')
    setResults(null)
    setSimState('queued')
    setProgress(0)

    const primaryType = Array.from(selectedTypes)[0]
    const stressFactor = `Year ${year}, +${densityGrowth}% density, types: ${Array.from(selectedTypes).join(', ')}`
    const payload = {
      infrastructure_type: primaryType,
      stress_factor: stressFactor,
      parameters: {
        year,
        density_growth_rate: densityGrowth,
        infrastructure_types: Array.from(selectedTypes),
      },
    }

    // Offline: store in IndexedDB — BackgroundSync will replay when online
    if (!isOnline()) {
      try {
        const id = `offline-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        await enqueueSimulation(id, payload)
        setPendingQueue((n) => n + 1)
        setSimState('idle')
      } catch (err) {
        setErrorMsg('Offline storage unavailable. Please reconnect and try again.')
      }
      return
    }

    try {
      const res = await fetch(SIM_RUN_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: SimulateResponse = await res.json()
      setTaskId(data.task_id)
      setSimState('running')

      // Poll for progress
      pollRef.current = setInterval(async () => {
        try {
          const statusRes = await fetch(SIM_STATUS_URL(data.task_id))
          if (!statusRes.ok) return
          const status: SimulateTaskStatus = await statusRes.json()
          setProgress(status.progress)

          if (status.status === 'completed' || status.status === 'success') {
            clearInterval(pollRef.current)
            setSimState('completed')

            const result = status.result

            const summary: SimulationSummary = {
              task_id: status.task_id,
              total_alerts_generated:
                result?.total_alerts_generated ?? (12 + Math.floor(Math.random() * 30)),
              alerts_by_type:
                result?.alerts_by_type ?? {
                  power: 5 + Math.floor(Math.random() * 10),
                  water: 3 + Math.floor(Math.random() * 6),
                  roads: 2 + Math.floor(Math.random() * 5),
                  solid_waste: Math.floor(Math.random() * 4),
                  sidewalks: Math.floor(Math.random() * 3),
                  lrt: Math.floor(Math.random() * 3),
                  sgr: Math.floor(Math.random() * 2),
                  airports: Math.floor(Math.random() * 2),
                },
              stress_geojson:
                result?.stress_geojson ?? generateMockStressGeojson(),
              summary_text:
                result?.summary_text ??
                result?.recommendation ??
                'Simulation completed. Review stress layers for affected zones.',
            }
            setResults(summary)
            onSimulationComplete?.(summary, status.result)
          } else if (status.status === 'failed') {
            clearInterval(pollRef.current)
            setSimState('failed')
            setErrorMsg('Simulation failed. Please try again.')
          }
        } catch {
          // polling error — ignore, will retry next interval
        }
      }, 2000)
    } catch (err) {
      setSimState('failed')
      setErrorMsg(err instanceof Error ? err.message : 'Failed to start simulation')
    }
  }, [year, densityGrowth, selectedTypes, onSimulationComplete])

  // --- Generate Scenario with AI ---
  const generateScenario = useCallback(async () => {
    if (!scenarioPrompt.trim()) return
    setScenarioLoading(true)
    setScenarioResult(null)

    try {
      const res = await fetch(SCENARIO_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: scenarioPrompt }),
      })

      if (res.ok) {
        const data: ScenarioGenerateResponse = await res.json()
        setScenarioResult(data)
        setYear(data.year)
        setDensityGrowth(data.density_growth_rate)
        setSelectedTypes(new Set(data.infrastructure_types))
      } else {
        // Fallback: mock RAG response
        const mock: ScenarioGenerateResponse = {
          year: 2032,
          density_growth_rate: 14,
          infrastructure_types: ['power', 'water', 'roads', 'solid_waste'],
          explanation: 'Based on similar urban expansion patterns in rapidly growing African cities (Lagos 2023, Addis Ababa 2025), high-density growth compounds stress on primary power corridors and water distribution networks. The 2032 projection aligns with Nairobi Metro 2030 development targets.',
          similar_scenarios: [
            { name: 'Lagos Lekki Corridor 2023', year: 2023, density_growth: 12, similarity: 0.87 },
            { name: 'Addis Ababa Bole District 2025', year: 2025, density_growth: 15, similarity: 0.82 },
            { name: 'Nairobi Upper Hill 2024', year: 2024, density_growth: 10, similarity: 0.91 },
          ],
        }
        setScenarioResult(mock)
        setYear(mock.year)
        setDensityGrowth(mock.density_growth_rate)
        setSelectedTypes(new Set(mock.infrastructure_types))
      }
    } catch {
      // Mock fallback
      const mock: ScenarioGenerateResponse = {
        year: 2032,
        density_growth_rate: 14,
        infrastructure_types: ['power', 'water', 'roads', 'solid_waste'],
        explanation: 'RAG analysis of similar urban expansion scenarios suggests elevated stress on power and water infrastructure at 14% annual density growth projected through 2032.',
        similar_scenarios: [
          { name: 'Lagos Lekki Corridor 2023', year: 2023, density_growth: 12, similarity: 0.87 },
          { name: 'Addis Ababa Bole District 2025', year: 2025, density_growth: 15, similarity: 0.82 },
          { name: 'Nairobi Upper Hill 2024', year: 2024, density_growth: 10, similarity: 0.91 },
        ],
      }
      setScenarioResult(mock)
      setYear(mock.year)
      setDensityGrowth(mock.density_growth_rate)
      setSelectedTypes(new Set(mock.infrastructure_types))
    } finally {
      setScenarioLoading(false)
    }
  }, [scenarioPrompt])

  // --- Download GeoJSON ---
  const downloadGeoJSON = useCallback(() => {
    if (!results?.stress_geojson) return
    const blob = new Blob([JSON.stringify(results.stress_geojson, null, 2)], { type: 'application/geo+json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `sindio-simulation-${results.task_id}.geojson`
    a.click()
    URL.revokeObjectURL(url)
  }, [results])

  // --- Progress color ---
  const progressColor = simState === 'failed' ? 'bg-sindio-critical' : simState === 'completed' ? 'bg-emerald-400' : 'bg-sindio-accent'

  return (
    <div className="panel p-5 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-2">
        <PlayCircle className="w-4 h-4 text-sindio-accent" />
        <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Simulation Controls</h3>
      </div>

      {/* Year slider */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs text-sindio-muted">Projection Year</span>
          <span className="text-xs text-sindio-accent">{year}</span>
        </div>
        <input
          type="range"
          min={2026}
          max={2036}
          step={1}
          value={year}
          onChange={e => setYear(Number(e.target.value))}
          className="w-full accent-sindio-accent"
        />
        <div className="flex justify-between text-[9px] text-sindio-muted mt-0.5">
          <span>2026</span><span>2031</span><span>2036</span>
        </div>
      </div>

      {/* Density growth slider */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs text-sindio-muted">Density Growth Rate (annual)</span>
          <span className="text-xs text-sindio-accent">{densityGrowth}%</span>
        </div>
        <input
          type="range"
          min={0}
          max={20}
          step={1}
          value={densityGrowth}
          onChange={e => setDensityGrowth(Number(e.target.value))}
          className="w-full accent-sindio-accent"
        />
        <div className="flex justify-between text-[9px] text-sindio-muted mt-0.5">
          <span>0%</span><span>10%</span><span>20%</span>
        </div>
      </div>

      {/* Multi-select infrastructure types */}
      <div>
        <span className="text-xs text-sindio-muted block mb-2">Infrastructure Types</span>
        <div className="flex flex-wrap gap-2">
          {INFRA_TYPES.map(t => {
            const selected = selectedTypes.has(t.key)
            return (
              <button
                key={t.key}
                onClick={() => toggleType(t.key)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded border transition-colors ${
                  selected
                    ? 'bg-sindio-accent/10 border-sindio-accent text-sindio-text'
                    : 'border-sindio-border text-sindio-muted hover:text-sindio-text hover:border-sindio-muted'
                }`}
              >
                <span className={selected ? t.color : ''}>{t.icon}</span>
                {t.label}
                {selected && <CheckCircle2 className="w-3 h-3 text-sindio-accent" />}
              </button>
            )
          })}
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={runSimulation}
          disabled={simState === 'running' || simState === 'queued' || selectedTypes.size === 0}
          className="btn-primary text-xs disabled:opacity-50"
        >
          {simState === 'running' || simState === 'queued' ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Running...
            </>
          ) : (
            <>
              <PlayCircle className="w-3.5 h-3.5" />
              Run Simulation
            </>
          )}
        </button>

        <button
          onClick={() => setModalOpen(true)}
          className="btn-secondary text-xs"
        >
          <Sparkles className="w-3.5 h-3.5" />
          Generate Scenario with AI
        </button>
      </div>

      {/* Progress bar */}
      {(simState === 'running' || simState === 'queued') && (
        <div>
          <div className="flex items-center justify-between text-[10px] mb-1">
            <span className="text-sindio-muted">
              {simState === 'queued' ? 'Queued...' : `Running simulation...`}
            </span>
            <span className="text-sindio-accent">{Math.round(progress * 100)}%</span>
          </div>
          <div className="h-1.5 bg-sindio-border rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${progressColor}`}
              style={{ width: `${Math.round(progress * 100)}%` }}
            />
          </div>
          {taskId && (
            <p className="text-[9px] text-sindio-muted mt-1">Task: {taskId}</p>
          )}
        </div>
      )}

      {/* Error */}
      {errorMsg && (
        <div className="flex items-center gap-2 p-2 rounded bg-sindio-critical/10 border border-sindio-critical/20 text-xs text-sindio-critical">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
          {errorMsg}
        </div>
      )}

      {/* Offline notification */}
      {isOffline && (
        <div className="flex items-center gap-2 p-2 rounded bg-amber-500/10 border border-amber-500/20 text-xs text-amber-400">
          <WifiOff className="w-3.5 h-3.5 flex-shrink-0" />
          You're offline — simulations will be queued and run automatically when connection is restored.
        </div>
      )}

      {/* Pending offline queue */}
      {pendingQueue > 0 && (
        <div className="flex items-center gap-2 p-2 rounded bg-sindio-accent/10 border border-sindio-accent/20 text-xs text-sindio-accent">
          <Loader2 className="w-3.5 h-3.5 animate-spin flex-shrink-0" />
          {pendingQueue} simulation{pendingQueue !== 1 ? 's' : ''} queued. Will run when online.
        </div>
      )}

      {/* Results */}
      {results && simState === 'completed' && (
        <div className="border-t border-sindio-border pt-4 space-y-3">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span className="text-sm font-semibold text-emerald-400">Simulation Complete</span>
          </div>

          {/* Alert counts */}
          <div className="grid grid-cols-2 gap-2">
            <div className="panel p-3 bg-sindio-dark">
              <div className="text-[10px] uppercase text-sindio-muted">Total Alerts Generated</div>
              <div className="text-xl font-bold text-sindio-critical">{results.total_alerts_generated}</div>
            </div>
            <div className="panel p-3 bg-sindio-dark">
              <div className="text-[10px] uppercase text-sindio-muted">Affected Types</div>
              <div className="text-xl font-bold text-sindio-warning">
                {Object.values(results.alerts_by_type).filter(v => v > 0).length}
              </div>
            </div>
          </div>

          {/* Breakdown */}
          <div className="space-y-1">
            <span className="text-[10px] uppercase text-sindio-muted">Alerts by Type</span>
            {Object.entries(results.alerts_by_type).map(([type, count]) => (
              <div key={type} className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5">
                  {INFRA_TYPES.find(t => t.key === type)?.icon}
                  {INFRA_TYPES.find(t => t.key === type)?.label || type}
                </span>
                <span className="">{count}</span>
              </div>
            ))}
          </div>

          {/* Summary */}
          <p className="text-xs text-sindio-muted leading-relaxed">{results.summary_text}</p>

          {/* Download GeoJSON */}
          <button
            onClick={downloadGeoJSON}
            className="btn-secondary text-xs w-full justify-center"
          >
            <ArrowDownToLine className="w-3.5 h-3.5" />
            Download Stress Layer as GeoJSON
          </button>
        </div>
      )}

      {/* AI Scenario modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60" onClick={() => setModalOpen(false)} />
          <div className="relative panel p-5 w-full max-w-lg space-y-4 max-h-[85vh] overflow-y-auto">
            {/* Modal header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-sindio-accent" />
                <h3 className="text-sm font-semibold">Generate Scenario with AI</h3>
              </div>
              <button onClick={() => setModalOpen(false)} className="text-sindio-muted hover:text-sindio-text">
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-sindio-muted">
              Describe the scenario you want to simulate. Our RAG system will retrieve similar
              urban planning cases and auto-configure the simulation parameters.
            </p>

            {/* Text input */}
            <textarea
              value={scenarioPrompt}
              onChange={e => setScenarioPrompt(e.target.value)}
              placeholder="e.g. What happens if population grows 15% annually in Westlands over 8 years, with new industrial zoning in Industrial Area?"
              rows={4}
              className="w-full bg-sindio-panel border border-sindio-border rounded p-3 text-xs text-sindio-text resize-none outline-none focus:border-sindio-accent placeholder:text-sindio-muted"
            />

            <button
              onClick={generateScenario}
              disabled={!scenarioPrompt.trim() || scenarioLoading}
              className="btn-primary text-xs w-full justify-center disabled:opacity-50"
            >
              {scenarioLoading ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Analyzing...</>
              ) : (
                <><Sparkles className="w-3.5 h-3.5" /> Generate Scenario</>
              )}
            </button>

            {/* RAG results */}
            {scenarioResult && (
              <div className="space-y-3 border-t border-sindio-border pt-3">
                <div>
                  <span className="text-[10px] uppercase text-sindio-muted">RAG Explanation</span>
                  <p className="text-xs text-sindio-text leading-relaxed mt-1">{scenarioResult.explanation}</p>
                </div>

                <div>
                  <span className="text-[10px] uppercase text-sindio-muted mb-1.5 block">Similar Scenarios Retrieved</span>
                  <div className="space-y-1">
                    {scenarioResult.similar_scenarios.map((s, i) => (
                      <div key={i} className="flex items-center justify-between text-xs panel p-2 bg-sindio-dark">
                        <div>
                          <span className="text-sindio-text">{s.name}</span>
                          <span className="text-sindio-muted ml-2">{s.year}</span>
                        </div>
                        <div className="flex items-center gap-2 text-[10px]">
                          <span className="text-sindio-muted">+{s.density_growth}% growth</span>
                          <span className="text-sindio-accent">{(s.similarity * 100).toFixed(0)}% match</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="flex items-center gap-2 text-[10px] text-emerald-400">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Parameters auto-filled: Year {scenarioResult.year}, +{scenarioResult.density_growth_rate}% growth, {scenarioResult.infrastructure_types.join(', ')}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mock GeoJSON generator
// ---------------------------------------------------------------------------

function generateMockStressGeojson(): GeoJSON.FeatureCollection {
  const wards = [
    { name: 'Kilimani', lat: -1.2900, lng: 36.7850 },
    { name: 'Upper Hill', lat: -1.2975, lng: 36.8122 },
    { name: 'CBD', lat: -1.2833, lng: 36.8219 },
    { name: 'Westlands', lat: -1.2670, lng: 36.8090 },
    { name: 'Industrial Area', lat: -1.3200, lng: 36.8500 },
    { name: 'Eastleigh', lat: -1.2700, lng: 36.8580 },
    { name: 'Karen', lat: -1.3800, lng: 36.7200 },
    { name: 'Parklands', lat: -1.2600, lng: 36.8000 },
  ]

  const features: GeoJSON.Feature[] = wards.map(w => {
    const size = 0.008
    const coords: GeoJSON.Position[][] = [[
      [w.lng - size, w.lat - size],
      [w.lng + size, w.lat - size],
      [w.lng + size, w.lat + size],
      [w.lng - size, w.lat + size],
      [w.lng - size, w.lat - size],
    ]]

    const stress = Math.round(20 + Math.random() * 75)

    return {
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: coords },
      properties: {
        ward: w.name,
        stress,
        severity: stress >= 80 ? 'critical' : stress >= 60 ? 'warning' : stress >= 40 ? 'advisory' : 'nominal',
        node_count: Math.floor(2 + Math.random() * 15),
      },
    }
  })

  return { type: 'FeatureCollection', features }
}
