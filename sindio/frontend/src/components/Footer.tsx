import { Link } from 'react-router-dom'
import { Map, Shield, FileText, Cookie, Scale, Heart, HelpCircle, Mail, Newspaper, Briefcase, Info } from 'lucide-react'

const resources = [
  { icon: Shield, label: 'Privacy Policy', href: '/privacy' },
  { icon: Cookie, label: 'Cookie Policy', href: '/cookies' },
  { icon: Scale, label: 'Terms & Conditions', href: '/terms' },
  { icon: Heart, label: 'Service Status', href: '/status' },
]

const company = [
  { icon: Briefcase, label: 'Careers', href: '/careers' },
  { icon: HelpCircle, label: 'FAQ', href: '/faq' },
  { icon: Mail, label: 'Contact Us', href: '/contact' },
  { icon: Newspaper, label: 'Press', href: '/press' },
  { icon: Info, label: 'About', href: '/about' },
]

const faqItems = [
  {
    q: 'What infrastructure types does Sindio monitor?',
    a: 'Sindio supports eight infrastructure types through a single unified registry: power grids, water networks, road systems, solid waste collection, pedestrian sidewalks, light rail transit (LRT), standard gauge railway (SGR), and airport operations. Each type uses the same parameterized monitoring pipeline with configurable thresholds, physics engines, and data sources.',
  },
  {
    q: 'How does stress classification work?',
    a: 'Sindio employs long-window classification combining STL seasonal decomposition and rolling Spearman rank correlation across up to 18 months of TimescaleDB hypertable data. Assets are classified as recurring-only, density-driven, mixed, or unstable — enabling targeted intervention strategies per classification.',
  },
  {
    q: 'What happens when a data source becomes unavailable?',
    a: 'Every component includes graceful degradation. If PostGIS, Kafka, or an external API is unreachable, the system falls back to configurable synthetic data while tracking the mock-data ratio via Prometheus metrics. An alert triggers when mock data exceeds 10% for more than one hour.',
  },
  {
    q: 'Is Sindio suitable for cities other than Nairobi?',
    a: 'The unified registry and parameterized infrastructure monitor are designed for any dense urban environment. The current deployment is calibrated for Nairobi with local GIS boundaries, WorldPop raster data, and region-specific planning documents — but the core engine is location-agnostic.',
  },
  {
    q: 'What physics engines are integrated?',
    a: 'Power grid simulations use pandapower for load-flow analysis. Water networks use EPANET hydraulic models. Road networks use a modified cell-transmission model (CTM). Infrastructure types without dedicated engines (solid waste, sidewalks, LRT, SGR, airports) use configurable heuristic stress calculation.',
  },
]

export default function Footer() {
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
                  <Link to={r.href} className="flex items-center gap-2 text-sm text-sindio-muted hover:text-sindio-accent transition-colors">
                    <r.icon className="w-3.5 h-3.5" />
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
                  <Link to={c.href} className="flex items-center gap-2 text-sm text-sindio-muted hover:text-sindio-accent transition-colors">
                    <c.icon className="w-3.5 h-3.5" />
                    {c.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-sindio-muted mb-5">Platform</h4>
            <ul className="space-y-3">
              <li><Link to="/dashboard" className="flex items-center gap-2 text-sm text-sindio-muted hover:text-sindio-accent transition-colors">
                <FileText className="w-3.5 h-3.5" />Simulation Dashboard
              </Link></li>
              <li><Link to="/dashboard?system=alerts" className="flex items-center gap-2 text-sm text-sindio-muted hover:text-sindio-accent transition-colors">
                <FileText className="w-3.5 h-3.5" />Alert Feed
              </Link></li>
              <li><Link to="/dashboard?system=power" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">Power Grid</Link></li>
              <li><Link to="/dashboard?system=water" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">Water Systems</Link></li>
              <li><Link to="/dashboard?system=roads" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">Road Network</Link></li>
              <li><Link to="/dashboard?system=solid_waste" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">Solid Waste</Link></li>
              <li><Link to="/dashboard?system=sidewalks" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">Sidewalks</Link></li>
              <li><Link to="/dashboard?system=lrt" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">LRT</Link></li>
              <li><Link to="/dashboard?system=sgr" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">SGR</Link></li>
              <li><Link to="/dashboard?system=airports" className="text-sm text-sindio-muted hover:text-sindio-accent transition-colors">Airports</Link></li>
            </ul>
          </div>
        </div>

        {/* FAQ Section */}
        <div className="mt-14 pt-10 border-t border-sindio-border">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-sindio-muted mb-5">Frequently Asked Questions</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {faqItems.map((item, i) => (
              <div key={i} className="text-sm">
                <h5 className="font-medium text-white mb-2">{item.q}</h5>
                <p className="text-sindio-muted leading-relaxed">{item.a}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-14 pt-8 border-t border-sindio-border flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-sindio-muted">
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
