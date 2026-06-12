import { Link } from 'react-router-dom'

export default function Footer() {
  return (
    <footer className="border-t border-sindio-border bg-sindio-panel">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
          <div className="md:col-span-2">
            <h3 className="text-lg font-bold text-sindio-accent mb-2">Sindio</h3>
            <p className="text-sindio-muted text-sm max-w-sm">
              An urban engineering framework designed for the precision-era of city planning. Harnessing metabolic data to build resilient futures.
            </p>
          </div>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-sindio-muted mb-4">Platform</h4>
            <ul className="space-y-2 text-sm text-sindio-muted">
              <li><Link to="/dashboard" className="hover:text-sindio-accent">Simulation</Link></li>
              <li><Link to="/dashboard?system=power" className="hover:text-sindio-accent">Power Grid</Link></li>
              <li><Link to="/dashboard?system=water" className="hover:text-sindio-accent">Water Systems</Link></li>
              <li><Link to="/dashboard?system=roads" className="hover:text-sindio-accent">Road Network</Link></li>
              <li><Link to="/dashboard?system=solid_waste" className="hover:text-sindio-accent">Solid Waste</Link></li>
              <li><Link to="/dashboard?system=sidewalks" className="hover:text-sindio-accent">Sidewalks</Link></li>
              <li><Link to="/dashboard?system=lrt" className="hover:text-sindio-accent">LRT Trains</Link></li>
              <li><Link to="/dashboard?system=sgr" className="hover:text-sindio-accent">SGR Trains</Link></li>
              <li><Link to="/dashboard?system=airports" className="hover:text-sindio-accent">Airports</Link></li>
            </ul>
          </div>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-sindio-muted mb-4">About</h4>
            <ul className="space-y-2 text-sm text-sindio-muted">
              <li><Link to="/dashboard?system=alerts" className="hover:text-sindio-accent">Alert Feed</Link></li>
              <li><Link to="/dashboard" className="hover:text-sindio-accent">Architecture</Link></li>
              <li><Link to="/dashboard" className="hover:text-sindio-accent">Service Status</Link></li>
              <li><Link to="/" className="hover:text-sindio-accent">Contact</Link></li>
            </ul>
          </div>
        </div>
        <div className="mt-12 pt-8 border-t border-sindio-border flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-sindio-muted">
          <p>© 2026 Sindio Urban Systems. Engineered for precision.</p>
          <div className="flex items-center gap-4">
            <span>BUILD: v0.1.0-alpha</span>
            <span>UPTIME: 99.99%</span>
          </div>
        </div>
      </div>
    </footer>
  )
}
