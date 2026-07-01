import { ArrowLeft, Shield } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function PrivacyPage() {
  return (
    <div className="flex-1 p-4 sm:p-6 lg:p-8 max-w-3xl mx-auto">
      <Link
        to="/"
        className="inline-flex items-center gap-2 text-sm text-sindio-muted hover:text-sindio-accent transition-colors mb-8"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Home
      </Link>

      <div className="flex items-center gap-3 mb-3">
        <div className="w-10 h-10 rounded-lg bg-sindio-accent/10 flex items-center justify-center">
          <Shield className="w-5 h-5 text-sindio-accent" />
        </div>
        <h1 className="text-3xl font-bold">Privacy Policy</h1>
      </div>
      <p className="text-sindio-muted text-sm mb-10">Last updated: 1 July 2026</p>

      <div className="space-y-8 text-sm text-sindio-text leading-relaxed">
        <section>
          <h2 className="text-base font-semibold mb-3">Data We Collect</h2>
          <p className="text-sindio-muted">
            The Sindio platform processes infrastructure telemetry from publicly available sources and third-party APIs. We do not collect, store, or process personal identifiable information. The data we handle consists of:
          </p>
          <ul className="list-disc list-inside text-sindio-muted mt-2 space-y-1">
            <li>Anonymised spatial data aggregated at grid-cell level</li>
            <li>Infrastructure stress metrics, load readings, and failure predictions</li>
            <li>Simulation parameters submitted through the dashboard</li>
            <li>Service usage telemetry for operational monitoring</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-3">How We Use It</h2>
          <ul className="list-disc list-inside text-sindio-muted space-y-1">
            <li>To compute infrastructure stress indices and generate alerts</li>
            <li>To calibrate physics engine simulations against real-world readings</li>
            <li>To improve platform reliability through operational monitoring</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-3">Data Storage &amp; Retention</h2>
          <p className="text-sindio-muted">
            Infrastructure data is stored in TimescaleDB hypertables with configurable retention policies. Simulation results and user-submitted parameters are retained for 90 days unless extended by the session. No data is sold, shared with third parties, or used for advertising.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-3">Jurisdiction</h2>
          <p className="text-sindio-muted">
            Sindio operates under Kenyan data protection law and aligns with GDPR principles for cross-border data handling where applicable.
          </p>
        </section>
      </div>
    </div>
  )
}
