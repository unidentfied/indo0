import { Link } from 'react-router-dom'
import { Map, Plus, Minus } from 'lucide-react'
import { useState } from 'react'

const resources = [
  { label: 'Privacy Policy', href: '/privacy' },
  { label: 'Cookie Policy', href: '/cookies' },
  { label: 'Terms & Conditions', href: '/terms' },
  { label: 'Service Status', href: '/status' },
]

const company = [
  { label: 'Careers', href: '/careers' },
  { label: 'FAQ', href: '/faq' },
  { label: 'Contact Us', href: '/contact' },
  { label: 'Press', href: '/press' },
  { label: 'About', href: '/about' },
]

const faqItems = [
  {
    q: 'What infrastructure types does Sindio monitor?',
    a: 'Sindio supports eight infrastructure types through a single unified registry: power grids, water networks, road systems, solid waste collection, pedestrian sidewalks, light rail transit (LRT), standard gauge railway (SGR), and airport operations. Each type uses the same parameterized monitoring pipeline with configurable thresholds, physics engines, and data sources.',
  },
  {
    q: 'How does stress classification work?',
    a: 'Sindio employs long-window classification combining STL seasonal decomposition and rolling Spearman rank correlation across up to 18 months of TimescaleDB hypertable data. Assets are classified as recurring-only, density-driven, mixed, or unstable — enabling targeted intervention strategies.',
  },
  {
    q: 'What happens when a data source becomes unavailable?',
    a: 'Every component includes graceful degradation. If PostGIS, Kafka, or an external API is unreachable, the system falls back to configurable synthetic data while tracking the mock-data ratio via Prometheus metrics. An alert triggers when fallback exceeds 10% for more than one hour.',
  },
  {
    q: 'Is Sindio suitable for cities other than Nairobi?',
    a: 'The unified registry and parameterized infrastructure monitor are designed for any dense urban environment. The current deployment is calibrated for Nairobi with local GIS boundaries, WorldPop raster data, and region-specific planning documents — the core engine is location-agnostic.',
  },
  {
    q: 'What physics engines are integrated?',
    a: 'Power grid simulations use pandapower. Water networks use EPANET hydraulic models. Road networks use a modified cell-transmission model. Infrastructure types without dedicated physics engines use configurable heuristic stress calculations.',
  },
]

export default function Footer() {
  const [openFaq, setOpenFaq] = useState<number | null>(null)

  return (
    <footer className="border-t border-sindio-border bg-sindio-panel">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-10">
          <div>
            <Link to="/" className="inline-flex items-center gap-2 mb-4">
              <Map className="w-5 h-5 text-sindio-accent" />
              <span className="text-lg font-bold text-sindio-accent">Sindio</span>
            </Link>
            <p className="text-sindio-muted text-sm leading-relaxed max-w-xs">
              Predictive infrastructure modelling for dense urban environments. Real-time stress monitoring across eight infrastructure types, unified under a single parameterized pipeline.
            </p>
          </div>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-sindio-muted mb-5">Resources</h4>
            <ul className="space-y-3">
              {resources.map(r => (
                <li key={r.label}>
                  <Link to={r.href} className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">
                    {r.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-sindio-muted mb-5">Company</h4>
            <ul className="space-y-3">
              {company.map(c => (
                <li key={c.label}>
                  <Link to={c.href} className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">
                    {c.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-sindio-muted mb-5">Platform</h4>
            <ul className="space-y-3">
              <li><Link to="/dashboard?system=power" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">Power Grid</Link></li>
              <li><Link to="/dashboard?system=water" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">Water Systems</Link></li>
              <li><Link to="/dashboard?system=roads" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">Road Network</Link></li>
              <li><Link to="/dashboard?system=solid_waste" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">Solid Waste</Link></li>
              <li><Link to="/dashboard?system=sidewalks" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">Sidewalks</Link></li>
              <li><Link to="/dashboard?system=lrt" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">LRT</Link></li>
              <li><Link to="/dashboard?system=sgr" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">SGR</Link></li>
              <li><Link to="/dashboard?system=airports" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">Airports</Link></li>
              <li className="pt-3 mt-3 border-t border-sindio-border/50">
                <Link to="/dashboard" className="text-sm text-sindio-accent hover:text-sindio-accent-hover transition-colors">Simulation Dashboard</Link>
              </li>
              <li>
                <Link to="/dashboard?system=alerts" className="text-sm text-sindio-accent hover:text-sindio-accent-hover transition-colors">Alert Feed</Link>
              </li>
            </ul>
          </div>
        </div>

        {/* FAQ — Accordion */}
        <div className="mt-16 pt-10 border-t border-sindio-border">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-sindio-muted mb-8">
            Frequently Asked Questions
          </h4>
          <div className="max-w-3xl">
            {faqItems.map((item, i) => (
              <div
                key={i}
                className="border-b border-sindio-border/50 last:border-b-0"
              >
                <button
                  onClick={() => setOpenFaq(openFaq === i ? null : i)}
                  className="w-full flex items-center justify-between py-4 text-left group"
                >
                  <span className="text-sm font-medium text-white group-hover:text-sindio-accent transition-colors pr-4">
                    {item.q}
                  </span>
                  <span className="flex-shrink-0 text-sindio-muted group-hover:text-sindio-accent transition-colors">
                    {openFaq === i ? (
                      <Minus className="w-4 h-4" />
                    ) : (
                      <Plus className="w-4 h-4" />
                    )}
                  </span>
                </button>
                <div
                  className={`overflow-hidden transition-all duration-300 ease-in-out ${
                    openFaq === i ? 'max-h-96 pb-4' : 'max-h-0'
                  }`}
                >
                  <p className="text-sm text-sindio-muted leading-relaxed">
                    {item.a}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-16 pt-8 border-t border-sindio-border flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-sindio-muted">
          <p>&copy; {new Date().getFullYear()} Sindio Urban Systems. All rights reserved.</p>
          <div className="flex items-center gap-4">
            <span>v0.1.0-alpha</span>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span>System Operational</span>
          </div>
        </div>
      </div>
    </footer>
  )
}
