
import { Link, useLocation } from 'react-router-dom';
import { useState, useMemo, useEffect } from 'react';
import AuthModal from '../components/AuthModal';
import { useAuth } from '../contexts/AuthContext';

import {
  ArrowRight, Map, BrainCircuit, Clock, Play,
  Binary, Wifi, Shield, Database, AlertTriangle, GitBranch,
  Zap, CheckCircle, CreditCard,
} from 'lucide-react'

const MONTHLY_PRICE = 83800

const features = [
  {
    icon: Map,
    title: 'Unified Infrastructure Intelligence',
    description:
      'Consolidate monitoring across eight vital metropolitan sectors — from power grids and water networks to transit systems. Powered by a single registry configuration, a unified stress API, and comprehensive diagnostic visualization.',
    tags: ['8 Infrastructure Sectors', 'Centralized Registry', 'Unified Diagnostic API'],
  },
  {
    icon: BrainCircuit,
    title: 'Predictive Stress Analytics',
    description:
      'Utilize long-window STL seasonal decomposition and rolling Spearman correlation over 18+ months of TimescaleDB hypertable history. Distinguish systemic population growth from seasonal strain to design high-impact urban interventions.',
    tags: ['STL Seasonal Decomposition', 'Spearman Correlation (ρ)', 'TimescaleDB Analytics'],
  },
  {
    icon: Clock,
    title: 'Resilient Registry Scheduling',
    description:
      'Configure precise, sector-specific update intervals centrally. Designed with automatic Celery task queue fallbacks to ensure the platform remains responsive and operational under all system load profiles.',
    tags: ['Interval Orchestration', 'Celery Queue Fallback', 'Adaptive Thresholds'],
  },
]

const capabilities = [
  { icon: Binary, label: 'Unified Registry', desc: 'A centralized schema managing alert thresholds, intervals, data pipelines, and simulation parameters across all sectors.' },
  { icon: Wifi, label: 'Real-Time Stress API', desc: 'A singular high-performance endpoint exposing localized stress, baseline deviations, and actionable mitigation paths.' },
  { icon: Shield, label: 'Fault-Tolerant Architecture', desc: 'Built-in resilience layers that gracefully switch to synthetic fallbacks with automated Prometheus anomaly alerting.' },
  { icon: Database, label: 'Telemetry & Observability', desc: 'Deep metrics on database health, telemetry streaming, and machine learning model confidence mapped to pre-configured Grafana views.' },
]

const trialFeatures = [
  'Full access to all 8 infrastructure sectors',
  'Real-time stress monitoring dashboard',
  'Natural language infrastructure search',
  'Predictive analytics & STL decomposition',
  'Cascade failure analysis & ROI calculator',
  'Carbon impact & insurance risk dashboards',
  'Interactive PostGIS spatial heatmaps',
  'Live WebSocket alert feeds',
  'Priority simulation queue',
]

const proFeatures = [
  'Everything in the free trial',
  'Priority data ingestion pipelines',
  'Asset-level classification & shift detection',
  'Critical risk feed with priority routing',
  'Real-time data freshness monitoring',
  'CSV/GeoJSON data exports',
  'Long-window Spearman correlation',
  'Multi-user team accounts (coming soon)',
]

export default function LandingPage() {
  const { isAuthenticated } = useAuth()
  const location = useLocation()
  const [showAuth, setShowAuth] = useState(false)
  const [authMode, setAuthMode] = useState<'signin' | 'signup'>('signin')

  useEffect(() => {
    const state = location.state as { requireAuth?: boolean; from?: string } | null
    const params = new URLSearchParams(location.search)
    if (state?.requireAuth || params.get('auth') === 'signin') {
      setAuthMode('signin')
      setShowAuth(true)
    }
  }, [location.state, location.search])

  const [billingCycle, setBillingCycle] = useState<'monthly' | 'annual'>('monthly')

  const annualPrice = useMemo(() => Math.round(MONTHLY_PRICE * 12 * 0.8), [])
  const displayPrice = billingCycle === 'monthly' ? MONTHLY_PRICE : annualPrice

  const openAuth = () => setShowAuth(true)

  const dashboardLink = isAuthenticated ? (
    <Link to="/dashboard" className="btn-primary">
      Open Dashboard
      <ArrowRight className="w-4 h-4" />
    </Link>
  ) : (
    <button onClick={openAuth} className="btn-primary">
      Sign In
      <ArrowRight className="w-4 h-4" />
    </button>
  )

  return (
    <div>
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="max-w-7xl mx-auto px-6 sm:px-8 lg:px-12 pt-20 pb-24">
          <div className="max-w-2xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-sindio-border bg-sindio-panel text-[10px] uppercase tracking-wider text-sindio-accent font-medium mb-6">
              <span className="w-1.5 h-1.5 rounded-full bg-sindio-accent animate-pulse" />
              Simulation Active &mdash; Nairobi_Run_01
            </div>
            <h1 className="text-3xl xs:text-4xl sm:text-5xl md:text-6xl font-bold tracking-tight mb-6 leading-tight">
              Infrastructure Resilience<br />
              &amp; the <span className="text-sindio-accent">Metabolic Flow of Nairobi</span>
            </h1>
            <p className="text-sindio-muted text-lg mb-8 max-w-lg leading-relaxed">
              High-fidelity spatial modeling and long-window stress classification across eight critical systems. Engineered to optimize metropolitan load dynamics and preempt system failures.
            </p>
            <div className="flex flex-wrap items-center gap-4">
              {dashboardLink}
              {!isAuthenticated && (
                <button onClick={openAuth} className="btn-primary">
                  Sign Up
                  <ArrowRight className="w-4 h-4" />
                </button>
              )}
              <a href="#features" className="btn-secondary">Explore Features</a>
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

      {showAuth && <AuthModal onClose={() => setShowAuth(false)} initialMode={authMode} />}

      {/* Core Features */}
      <section id="features" className="border-t border-sindio-border py-20">
        <div className="max-w-7xl mx-auto px-6 sm:px-8 lg:px-12">
          <div className="flex items-end justify-between mb-12">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-sindio-accent font-medium mb-2">Core Architecture</div>
              <h2 className="text-3xl font-bold max-w-md">Data-Driven Resilience for Nairobi's Dense Urban Environment</h2>
            </div>
            {isAuthenticated ? (
              <Link to="/dashboard" className="hidden sm:flex items-center gap-2 text-sm text-sindio-accent hover:text-sindio-accent-hover transition-colors">
                Explore All Modules
                <ArrowRight className="w-4 h-4" />
              </Link>
            ) : (
              <button onClick={openAuth} className="hidden sm:flex items-center gap-2 text-sm text-sindio-accent hover:text-sindio-accent-hover transition-colors">
                Explore All Modules
                <ArrowRight className="w-4 h-4" />
              </button>
            )}
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
        <div className="max-w-7xl mx-auto px-6 sm:px-8 lg:px-12">
          <div className="text-center mb-12">
            <div className="text-[10px] uppercase tracking-wider text-sindio-accent font-medium mb-2">Platform Capabilities</div>
            <h2 className="text-3xl font-bold mb-4">Built for Urban Engineering at Scale</h2>
            <p className="text-sindio-muted max-w-xl mx-auto">
              Every system component is verified using real-world Nairobi spatial data, backed by TimescaleDB, PostGIS, and Qdrant vector search.
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

      {/* Platform Previews — Three Lenses */}
      <section className="border-t border-sindio-border py-20">
        <div className="max-w-7xl mx-auto px-6 sm:px-8 lg:px-12">
          <div className="text-center mb-12">
            <div className="text-[10px] uppercase tracking-wider text-sindio-accent font-medium mb-2">Platform</div>
            <h2 className="text-3xl font-bold mb-4">Three Lenses on Nairobi&rsquo;s Dynamics</h2>
            <p className="text-sindio-muted max-w-xl mx-auto">
              Explore interactive stress heatmaps, natural language search, live alert feeds, cascade analysis, and high-level health diagnostics — all powered by PostGIS spatial indexing and WebSockets.
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
                  <h3 className="font-semibold">System Overview</h3>
                </div>
                <p className="text-xs text-sindio-muted">A unified executive cockpit detailing sector health, active simulation scenarios, and real-time stress trends.</p>
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
                <p className="text-xs text-sindio-muted">High-fidelity Deck.gl spatial visualization rendering regional load profiles and PostGIS query-derived stress alerts.</p>
              </div>
            </div>
            <div className="panel overflow-hidden group">
              <div className="relative overflow-hidden">
                <img src="/images/nairobi-planning.jpg" alt="Alert Feed" className="w-full h-48 object-cover object-top group-hover:scale-105 transition-transform duration-500" />
                <div className="absolute inset-0 bg-gradient-to-t from-sindio-dark to-transparent" />
              </div>
              <div className="p-5">
                <div className="flex items-center gap-2 mb-2">
                  <AlertTriangle className="w-4 h-4 text-sindio-accent" />
                  <h3 className="font-semibold">Live Alert Feed</h3>
                </div>
                <p className="text-xs text-sindio-muted">Instantaneous WebSocket alert streams grouped by utility classification with automated priority routing and root-cause analysis.</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Pricing & Trial Section */}
      <section className="border-t border-sindio-border py-20 bg-gradient-to-b from-sindio-dark to-sindio-accent/5">
        <div className="max-w-7xl mx-auto px-6 sm:px-8 lg:px-12">
          <div className="text-center mb-12">
            <div className="text-[10px] uppercase tracking-wider text-sindio-accent font-medium mb-2">
              Pricing
            </div>
            <h2 className="text-3xl font-bold mb-4">Start with a 14-day free trial</h2>
            <p className="text-sindio-muted max-w-xl mx-auto">
              No credit card required. Full access to all features. Cancel anytime.
            </p>

            {/* Billing Toggle */}
            <div className="inline-flex items-center gap-3 mt-8 p-1 rounded-full border border-sindio-border bg-sindio-panel">
              <button
                onClick={() => setBillingCycle('monthly')}
                className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${
                  billingCycle === 'monthly'
                    ? 'bg-sindio-accent text-white'
                    : 'text-sindio-muted hover:text-white'
                }`}
              >
                Monthly
              </button>
              <button
                onClick={() => setBillingCycle('annual')}
                className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${
                  billingCycle === 'annual'
                    ? 'bg-sindio-accent text-white'
                    : 'text-sindio-muted hover:text-white'
                }`}
              >
                Annual
                <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-green-500/20 text-green-400 align-middle">
                  −20%
                </span>
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-4xl mx-auto">
            {/* Trial Card */}
            <div className="panel p-8 border-sindio-border hover:border-sindio-accent/30 transition-colors relative">
              <div className="absolute top-0 left-0 right-0 h-1 bg-sindio-accent rounded-t-xl" />
              <div className="flex items-center gap-2 mb-4">
                <Zap className="w-5 h-5 text-sindio-accent" />
                <h3 className="text-xl font-bold">14-Day Free Trial</h3>
              </div>
              <div className="mb-6">
                <span className="text-4xl font-bold">KES 0</span>
                <span className="text-sindio-muted text-sm ml-1">/ first 14 days</span>
              </div>
              <ul className="space-y-3 mb-8">
                {trialFeatures.map((f, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-sindio-muted">
                    <CheckCircle className="w-4 h-4 text-green-500 mt-0.5 shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
              <button onClick={openAuth} className="btn-primary w-full justify-center">
                Start 14-Day Trial
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>

            {/* Pro Subscription Card */}
            <div className="panel p-8 border-sindio-accent/40 bg-sindio-accent/5 relative">
              <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-sindio-accent to-purple-500 rounded-t-xl" />
              <div className="flex items-center gap-2 mb-4">
                <CreditCard className="w-5 h-5 text-sindio-accent" />
                <h3 className="text-xl font-bold">Sindio Pro</h3>
              </div>
              <div className="mb-1">
                <span className="text-4xl font-bold">KES {displayPrice.toLocaleString()}</span>
                <span className="text-sindio-muted text-sm ml-1">/ {billingCycle}</span>
              </div>
              {billingCycle === 'annual' && (
                <p className="text-xs text-green-400 mb-4">
                  Save KES {(MONTHLY_PRICE * 12 - annualPrice).toLocaleString()} per year with annual billing
                </p>
              )}
              {billingCycle === 'monthly' && (
                <p className="text-xs text-sindio-muted mb-4">Billed monthly</p>
              )}
              <ul className="space-y-3 mb-8">
                {proFeatures.map((f, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-sindio-muted">
                    <CheckCircle className="w-4 h-4 text-green-500 mt-0.5 shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
              <button onClick={openAuth} className="btn-primary w-full justify-center bg-sindio-accent hover:bg-sindio-accent-hover">
                Subscribe Now
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>

          <p className="text-center text-xs text-sindio-muted mt-8">
            All prices in Kenyan Shillings (KES). VAT inclusive where applicable.
          </p>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-sindio-border py-20 bg-sindio-accent/5">
        <div className="max-w-3xl mx-auto px-6 text-center">
          <h2 className="text-3xl font-bold mb-4">Ready to engineer the future of your city?</h2>
          <p className="text-sindio-muted mb-8">
            Join the next era of data-driven metropolitan planning and enhance infrastructure resilience.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-4">
            {isAuthenticated ? (
              <Link to="/dashboard" className="btn-primary">
                <Play className="w-4 h-4" />
                Open Dashboard
              </Link>
            ) : (
              <button onClick={openAuth} className="btn-primary">
                <Play className="w-4 h-4" />
                Get Started
              </button>
            )}
            {isAuthenticated ? (
              <Link to="/dashboard?system=alerts" className="btn-secondary">
                View Alert Feed
              </Link>
            ) : (
              <button onClick={openAuth} className="btn-secondary">
                View Alert Feed
              </button>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}
