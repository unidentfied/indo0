import { useState, useEffect } from 'react'
import { BarChart3, ChevronDown, ChevronUp, Info, ExternalLink } from 'lucide-react'
import type { ClassificationSummary, ClassificationType } from '../types'
import { api } from '../services/api'
import { InfraIcon } from './InfraIcons'

const typeColors: Record<ClassificationType, string> = {
  recurring_only: 'bg-amber-500',
  density_driven_only: 'bg-blue-500',
  mixed: 'bg-purple-500',
  unstable: 'bg-slate-500',
}

const typeTextColors: Record<ClassificationType, string> = {
  recurring_only: 'text-amber-400',
  density_driven_only: 'text-blue-400',
  mixed: 'text-purple-400',
  unstable: 'text-slate-400',
}

const typeLabels: Record<ClassificationType, string> = {
  recurring_only: 'Recurring',
  density_driven_only: 'Density-Driven',
  mixed: 'Mixed',
  unstable: 'Unstable',
}

function DataWindowBadge({ required, actual, stlRequired }: { required: number; actual: number; stlRequired: number }) {
  const meetsMin = actual >= required
  const meetsSTL = actual >= stlRequired

  return (
    <div className="flex items-center gap-2 text-[10px]">
      <span className={`px-1.5 py-0.5 rounded font-medium ${meetsMin ? 'bg-emerald-400/10 text-emerald-400' : 'bg-sindio-critical/10 text-sindio-critical'}`}>
        {actual}mo / {required}mo min
      </span>
      {!meetsSTL && (
        <span className="px-1.5 py-0.5 rounded bg-sindio-warning/10 text-sindio-warning" title={`STL recurring detection requires ${stlRequired} months`}>
          STL needs {stlRequired}mo
        </span>
      )}
      {meetsSTL && (
        <span className="px-1.5 py-0.5 rounded bg-emerald-400/10 text-emerald-400">
          STL eligible
        </span>
      )}
    </div>
  )
}

interface ClassificationExample {
  asset_id: string
  ward: string
  stress_ml: number
  confidence: number
  failure_mode: string
  recommendation: string
  spearman_rho: number | null
  recurrence_pct: number | null
  density_pct: number | null
  dominant_period_hours: number | null
  updated_at: string
}

export default function ClassificationPanel() {
  const [summaries, setSummaries] = useState<ClassificationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [selectedClass, setSelectedClass] = useState<{ infraType: string; classType: ClassificationType } | null>(null)
  const [examples, setExamples] = useState<ClassificationExample[]>([])
  const [examplesLoading, setExamplesLoading] = useState(false)

  useEffect(() => {
    api.monitor.classification()
      .then(d => { setSummaries(d?.summaries || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!selectedClass) return
    setExamplesLoading(true)
    api.monitor.classificationExamples(selectedClass.infraType, selectedClass.classType, 5)
      .then(d => { setExamples(d?.examples || []); setExamplesLoading(false) })
      .catch(() => setExamplesLoading(false))
  }, [selectedClass])

  if (loading) {
    return (
      <div className="panel p-6">
        <div className="flex items-center gap-2 mb-4">
          <BarChart3 className="w-4 h-4 text-sindio-accent" />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Stress Classification</h3>
        </div>
        <div className="text-xs text-sindio-muted text-center py-8">Loading classification data...</div>
      </div>
    )
  }

  return (
    <div className="panel">
      <div className="p-4 border-b border-sindio-border">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-sindio-accent" />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Stress Classification</h3>
          <span className="ml-auto text-[10px] bg-sindio-accent/10 text-sindio-accent px-2 py-0.5 rounded uppercase font-bold">
            {summaries.length} Types
          </span>
        </div>
        <p className="text-[10px] text-sindio-muted mt-1">
          Root-cause analysis: recurring patterns vs population density correlation. Minimum 6–12 months data per type.
        </p>
      </div>

      {/* Legend */}
      <div className="px-4 py-2 border-b border-sindio-border flex flex-wrap gap-3">
        {(Object.keys(typeLabels) as ClassificationType[]).map(t => (
          <div key={t} className="flex items-center gap-1.5 text-[10px]">
            <span className={`w-2 h-2 rounded-full ${typeColors[t]}`} />
            <span className="text-sindio-muted">{typeLabels[t]}</span>
          </div>
        ))}
      </div>

      {/* Per-type rows */}
      <div className="divide-y divide-sindio-border">
        {summaries.map(s => {
          const isExpanded = expanded === s.infrastructure_type
          const dist = s.classification_distribution
          const entries: { type: ClassificationType; entry: typeof dist.recurring_only }[] = [
            { type: 'recurring_only', entry: dist.recurring_only },
            { type: 'density_driven_only', entry: dist.density_driven_only },
            { type: 'mixed', entry: dist.mixed },
            { type: 'unstable', entry: dist.unstable },
          ]

          return (
            <div key={s.infrastructure_type}>
              <button
                className="w-full px-4 py-3 hover:bg-sindio-panel/50 text-left transition-colors"
                onClick={() => {
                  if (isExpanded) {
                    setExpanded(null)
                    setSelectedClass(null)
                  } else {
                    setExpanded(s.infrastructure_type)
                  }
                }}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2.5">
                    <span className="flex items-center justify-center w-7 h-7 rounded-lg bg-sindio-panel border border-sindio-border">
                      <InfraIcon type={s.infrastructure_type} />
                    </span>
                    <span className="text-xs font-medium text-sindio-text">{s.display_name}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <DataWindowBadge
                      required={s.data_window.minimum_required_months}
                      actual={s.data_window.actual_available_months}
                      stlRequired={s.data_window.stl_recurring_requires_months}
                    />
                    {isExpanded ? <ChevronUp className="w-3 h-3 text-sindio-muted" /> : <ChevronDown className="w-3 h-3 text-sindio-muted" />}
                  </div>
                </div>

                {/* Stacked bar */}
                <div className="h-2 rounded-full bg-sindio-panel overflow-hidden flex">
                  {entries.map(({ type, entry }) => (
                    <div
                      key={type}
                      className={`${typeColors[type]} transition-all`}
                      style={{ width: `${entry.percentage}%` }}
                      title={`${typeLabels[type]}: ${entry.percentage}%`}
                    />
                  ))}
                </div>

                {/* Percentages */}
                <div className="flex items-center justify-between mt-1">
                  <div className="flex gap-3">
                    {entries.map(({ type, entry }) => (
                      <span key={type} className={`text-[10px] ${typeTextColors[type]}`}>
                        {entry.percentage}%
                      </span>
                    ))}
                  </div>
                  <span className="text-[10px] text-sindio-muted">
                    ρ={s.avg_spearman_rho} conf={s.avg_confidence}
                  </span>
                </div>
              </button>

              {/* Expanded detail */}
              {isExpanded && (
                <div className="px-4 pb-4 bg-sindio-panel/30">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
                    {/* Classification breakdown */}
                    <div className="space-y-2">
                      <div className="text-[10px] uppercase text-sindio-muted font-medium">Classification Breakdown</div>
                      {entries.map(({ type, entry }) => (
                        <button
                          key={type}
                          className={`w-full text-left flex items-start gap-2 p-1.5 rounded transition-colors ${selectedClass?.infraType === s.infrastructure_type && selectedClass?.classType === type ? 'bg-sindio-accent/10 ring-1 ring-sindio-accent/30' : 'hover:bg-sindio-panel'}`}
                          onClick={() => setSelectedClass(selectedClass?.infraType === s.infrastructure_type && selectedClass?.classType === type ? null : { infraType: s.infrastructure_type, classType: type })}
                        >
                          <span className={`w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 ${typeColors[type]}`} />
                          <div>
                            <div className="text-xs font-medium flex items-center gap-1">
                              {typeLabels[type]}
                              <ExternalLink className="w-2.5 h-2.5 text-sindio-muted/50" />
                            </div>
                            <div className="text-[10px] text-sindio-muted">{entry.count} assets ({entry.percentage}%)</div>
                            <div className="text-[10px] text-sindio-muted/70">{entry.description}</div>
                          </div>
                        </button>
                      ))}
                    </div>

                    {/* Detection thresholds */}
                    <div className="space-y-2">
                      <div className="text-[10px] uppercase text-sindio-muted font-medium">Detection Thresholds</div>
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-sindio-muted">Spearman ρ (density)</span>
                          <span className="font-medium">&gt; {s.thresholds.spearman_rho_for_density}</span>
                        </div>
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-sindio-muted">STL seasonal strength</span>
                          <span className="font-medium">&gt; {s.thresholds.stl_seasonal_strength_min}</span>
                        </div>
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-sindio-muted">Peak timing CV</span>
                          <span className="font-medium">&lt; {s.thresholds.recurring_peak_cv_max}</span>
                        </div>
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-sindio-muted">STL requires</span>
                          <span className="font-medium">{s.data_window.stl_recurring_requires_months} months</span>
                        </div>
                      </div>

                      <div className="mt-3 p-2 rounded bg-sindio-panel border border-sindio-border">
                        <div className="flex items-start gap-1.5">
                          <Info className="w-3 h-3 text-sindio-accent mt-0.5 flex-shrink-0" />
                          <div className="text-[10px] text-sindio-muted leading-relaxed">
                            <strong className="text-sindio-text">Recurring</strong> = seasonal/temporal pattern via STL decomposition (≥3 years data).
                            <br />
                            <strong className="text-sindio-text">Density-Driven</strong> = Spearman correlation with population growth (≥{s.data_window.density_requires_months} months).
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Example assets */}
                    <div className="space-y-2">
                      <div className="text-[10px] uppercase text-sindio-muted font-medium">
                        {selectedClass ? (
                          <span className="flex items-center gap-1">
                            Example Assets
                            <span className={`px-1 py-0.5 rounded text-[9px] ${typeTextColors[selectedClass.classType]} bg-sindio-panel`}>
                              {typeLabels[selectedClass.classType]}
                            </span>
                          </span>
                        ) : (
                          'Example Assets'
                        )}
                      </div>
                      {examplesLoading ? (
                        <div className="text-[10px] text-sindio-muted text-center py-4">Loading examples...</div>
                      ) : !selectedClass ? (
                        <div className="text-[10px] text-sindio-muted text-center py-4">Click a classification to see examples</div>
                      ) : examples.length === 0 ? (
                        <div className="text-[10px] text-sindio-muted text-center py-4">No examples found</div>
                      ) : (
                        <div className="space-y-1.5">
                          {examples.map(ex => (
                            <div key={ex.asset_id} className="p-2 rounded bg-sindio-panel border border-sindio-border">
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-xs font-mono font-medium text-sindio-text">{ex.asset_id}</span>
                                <span className="text-[10px] text-sindio-muted">{ex.ward}</span>
                              </div>
                              <div className="flex items-center gap-2 text-[10px]">
                                <span className="text-sindio-muted">stress</span>
                                <span className={`font-medium ${ex.stress_ml > 0.7 ? 'text-sindio-critical' : ex.stress_ml > 0.4 ? 'text-sindio-warning' : 'text-emerald-400'}`}>
                                  {(ex.stress_ml * 100).toFixed(0)}%
                                </span>
                                <span className="text-sindio-muted">conf</span>
                                <span className="font-medium text-sindio-text">{(ex.confidence * 100).toFixed(0)}%</span>
                              </div>
                              <div className="text-[10px] text-sindio-muted mt-1">
                                <span className="text-sindio-muted">mode:</span> {ex.failure_mode}
                              </div>
                              {ex.spearman_rho !== null && (
                                <div className="text-[10px] text-sindio-muted">
                                  <span className="text-sindio-muted">ρ={ex.spearman_rho}</span>
                                </div>
                              )}
                              {ex.recurrence_pct !== null && (
                                <div className="text-[10px] text-sindio-muted">
                                  <span className="text-sindio-muted">recurrence</span> {(ex.recurrence_pct * 100).toFixed(0)}%
                                </div>
                              )}
                              {ex.density_pct !== null && (
                                <div className="text-[10px] text-sindio-muted">
                                  <span className="text-sindio-muted">density</span> {(ex.density_pct * 100).toFixed(0)}%
                                </div>
                              )}
                              <div className="text-[10px] text-sindio-muted/70 mt-1 italic truncate" title={ex.recommendation}>
                                {ex.recommendation}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
