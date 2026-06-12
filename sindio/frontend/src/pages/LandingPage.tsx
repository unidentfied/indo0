import { Link } from 'react-router-dom'
import {
  ArrowRight, Map, GitBranch, Layers, BarChart3, Play,
  Clock, Binary, BrainCircuit, Database, Wifi, Shield,
} from 'lucide-react'

const features = [
  {
    icon: Map,
    title: 'Unified Infrastructure Monitor',
    description:
      'Single parameterized system for all 8 infrastructure types — power, water, roads, solid waste, sidewalks, LRT, SGR, and airports. One config key, one API endpoint, one dashboard view.',
    tags: ['Unified Registry', 'Single Stress API', '8 Infrastructure Types'],
  },
  {
    icon: BrainCircuit,
    title: 'RAG Classification Engine',
    description:
      'Long-window classification using STL seasonal decomposition and rolling Spearman correlation. Detects recurring stress vs density-driven patterns across 18+ months of data.',
    tags: ['STL Decomposition', 'Spearman ρ > 0.6', 'TimescaleDB Hypertables'],
  },
  {
    icon: Clock,
    title: 'Dynamic Scheduling',
    description:
      'Registry-driven scheduler with per-infrastructure-type intervals. Graceful fallback when Celery is unavailable — always returns schedule state from unified config.',
    tags: ['Registry-Driven Intervals', 'Celery Fallback', 'Per-Type Thresholds'],
  },
]

const capabilities = [
  {
    icon: Binary,
    label: 'Unified Registry',
    desc: 'Single source of truth for all per-type settings — thresholds, intervals, actions, data sources, and physics engines. Previously scattered across 7+ files.',
  },
  {
    icon: Wifi,
    label: 'Real-Time Monitoring',
    desc: 'Unified stress endpoint returns all stressed assets across all types with baseline deviation, failure mode, time-to-breach, and recommendation.',
  },
  {
    icon: Shield,
    label: 'Graceful Fallbacks',
    desc: 'Every component handles missing dependencies — no Celery, no DB, no Kafka. Synthetic data with mock_ratio tracking for data quality metrics.',
  },
  {
    icon: Database,
    label: 'Data Quality Tracking',
    desc: 'Prometheus metrics for real data ratio, mock fallback rate, and model confidence per infrastructure type. Alert when mock > 10% for > 1h.',
  },
]

export default function LandingPage() {
  return (
    <div>
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-20 pb-24">
          <div className="max-w-2xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-sindio-border bg-sindio-panel text-[10px] uppercase tracking-wider text-sindio-accent font-medium mb-6">
              <span className="w-1.5 h-1.5 rounded-full bg-sindio-accent animate-pulse" />
              Simulation Active — Nairobi_Run_01
            </div>
            <h1 className="text-5xl sm:text-6xl font-bold tracking-tight mb-6 leading-tight">
              Predicting the <br />
              Metabolic <br />
              <span className="text-sindio-accent">Flow of Nairobi</span>
            </h1>
            <p className="text-sindio-muted text-lg mb-8 max-w-lg leading-relaxed">
              High-fidelity spatial infrastructure modeling with long-window stress classification across eight infrastructure types. From recurring pattern detection to density-driven alerting — all data-driven, no policy mandates.
            </p>
            <div className="flex flex-wrap items-center gap-4">
              <Link to="/dashboard" className="btn-primary">
                Open Dashboard
                <ArrowRight className="w-4 h-4" />
              </Link>
              <a href="#features" className="btn-secondary">
                Explore Features
              </a>
            </div>
          </div>
        </div>

        <div className="absolute top-0 right-0 w-1/2 h-full opacity-20 pointer-events-none">
          <img
            src="/images/landing-reference.jpg"
            alt=""
            className="w-full h-full object-cover object-left"
            style={{ maskImage: 'linear-gradient(to left, black, transparent)', WebkitMaskImage: 'linear-gradient(to left, black, transparent)' }}
          />
        </div>
      </section>

      {/* Core Features */}
      <section id="features" className="border-t border-sindio-border py-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-end justify-between mb-12">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-sindio-accent font-medium mb-2">Core Architecture</div>
              <h2 className="text-3xl font-bold max-w-md">
                Data-Driven Resilience for Dense Urban Environments
              </h2>
            </div>
            <Link to="/dashboard" className="hidden sm:flex items-center gap-2 text-sm text-sindio-accent hover:text-sindio-accent-hover transition-colors">
              Explore All Modules
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {features.map((f) => (
              <div key={f.title} className="panel p-6 hover:border-sindio-accent/30 transition-colors group">
                <div className="w-10 h-10 rounded-lg bg-sindio-panel border border-sindio-border flex items-center justify-center mb-5 group-hover:border-sindio-accent/50 transition-colors">
                  <f.icon className="w-5 h-5 text-sindio-accent" />
                </div>
                <h3 className="text-lg font-semibold mb-3">{f.title}</h3>
                <p className="text-sm text-sindio-muted leading-relaxed mb-5">{f.description}</p>
                <div className="space-y-2">
                  {f.tags.map(tag => (
                    <div key={tag} className="flex items-center gap-2 text-xs text-sindio-muted">
                      <span className="w-1 h-1 rounded-full bg-sindio-accent" />
                      {tag}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Capability Grid */}
      <section className="border-t border-sindio-border py-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <div className="text-[10px] uppercase tracking-wider text-sindio-accent font-medium mb-2">Platform Capabilities</div>
            <h2 className="text-3xl font-bold mb-4">Built for Urban Engineering at Scale</h2>
            <p className="text-sindio-muted max-w-xl mx-auto">
              Every component is verified against TimescaleDB, PostGIS, and Qdrant — operational on real Nairobi infrastructure data.
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {capabilities.map(c => (
              <div key={c.label} className="panel p-5 text-center">
                <div className="w-8 h-8 mx-auto mb-3 rounded bg-sindio-accent/10 flex items-center justify-center">
                  <c.icon className="w-4 h-4 text-sindio-accent" />
                </div>
                <h4 className="text-sm font-semibold mb-1.5">{c.label}</h4>
                <p className="text-xs text-sindio-muted leading-relaxed">{c.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Platform Previews */}
      <section className="border-t border-sindio-border py-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <div className="text-[10px] uppercase tracking-wider text-sindio-accent font-medium mb-2">Platform Previews</div>
            <h2 className="text-3xl font-bold mb-4">Three Lenses on Nairobi</h2>
            <p className="text-sindio-muted max-w-xl mx-auto">
              From the stress heatmap to the alert feed, every view is powered by the same backend — PostGIS spatial queries, STL classification, and WebSocket streaming.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="panel overflow-hidden group">
              <div className="relative overflow-hidden">
                <img src="/images/landing-reference.jpg" alt="Landing Overview" className="w-full h-48 object-cover object-top group-hover:scale-105 transition-transform duration-500" />
                <div className="absolute inset-0 bg-gradient-to-t from-sindio-dark to-transparent" />
              </div>
              <div className="p-5">
                <div className="flex items-center gap-2 mb-2">
                  <Map className="w-4 h-4 text-sindio-accent" />
                  <h3 className="font-semibold">Landing Overview</h3>
                </div>
                <p className="text-xs text-sindio-muted">Executive view into system health, infrastructure types, and active simulation campaigns.</p>
              </div>
            </div>
            <div className="panel overflow-hidden group">
              <div className="relative overflow-hidden">
                <img src="/images/dashboard-reference.jpg" alt="Stress Map" className="w-full h-48 object-cover object-top group-hover:scale-105 transition-transform duration-500" />
                <div className="absolute inset-0 bg-gradient-to-t from-sindio-dark to-transparent" />
              </div>
              <div className="p-5">
                <div className="flex items-center gap-2 mb-2">
                  <GitBranch className="w-4 h-4 text-sindio-accent" />
                  <h3 className="font-semibold">Infrastructure Stress Map</h3>
                </div>
                <p className="text-xs text-sindio-muted">Deck.gl heatmap with toggleable layers, PostGIS spatial queries, and per-asset classification.</p>
              </div>
            </div>
            <div className="panel overflow-hidden group">
              <div className="relative overflow-hidden">
                <img src="/images/nairobi-planning.jpg" alt="Alert Feed" className="w-full h-48 object-cover object-top group-hover:scale-105 transition-transform duration-500" />
                <div className="absolute inset-0 bg-gradient-to-t from-sindio-dark to-transparent" />
              </div>
              <div className="p-5">
                <div className="flex items-center gap-2 mb-2">
                  <Layers className="w-4 h-4 text-sindio-accent" />
                  <h3 className="font-semibold">Alert Feed &amp; Scheduling</h3>
                </div>
                <p className="text-xs text-sindio-muted">WebSocket live alerts grouped by infrastructure type with countdown timers and RAG explanations.</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-sindio-border py-20 bg-sindio-accent/5">
        <div className="max-w-3xl mx-auto px-4 text-center">
          <h2 className="text-3xl font-bold mb-4">Ready to engineer the future of your city?</h2>
          <p className="text-sindio-muted mb-8">
            Join the world's most advanced urban planners in defining the next era of data-driven infrastructure resilience.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-4">
            <Link to="/dashboard" className="btn-primary">
              <Play className="w-4 h-4" />
              Open Dashboard
            </Link>
            <Link to="/dashboard?system=alerts" className="btn-secondary">
              View Alert Feed
            </Link>
          </div>
        </div>
      </section>
    </div>
  )
}
