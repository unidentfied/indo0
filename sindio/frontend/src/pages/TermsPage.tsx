import { ArrowLeft, ScrollText } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function TermsPage() {
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
          <ScrollText className="w-5 h-5 text-sindio-accent" />
        </div>
        <h1 className="text-3xl font-bold">Terms &amp; Conditions</h1>
      </div>
      <p className="text-sindio-muted text-sm mb-10">Last updated: 1 July 2026</p>

      <div className="space-y-8 text-sm text-sindio-text leading-relaxed">
        <section>
          <h2 className="text-base font-semibold mb-3">Service Description</h2>
          <p className="text-sindio-muted">
            Sindio provides an infrastructure stress monitoring and simulation platform for urban planning purposes. The platform aggregates publicly available infrastructure data and applies physics-engine modelling to surface stress indicators, failure predictions, and intervention recommendations.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-3">Accuracy &amp; Liability</h2>
          <p className="text-sindio-muted">
            All stress metrics, simulations, and alerts are computed from best-available data sources and physics models. They are provided for planning and informational purposes. Sindio makes no warranty regarding the accuracy of predictions, and accepts no liability for decisions made based on platform output. Verify critical findings against ground-truth data before acting.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-3">Acceptable Use</h2>
          <p className="text-sindio-muted">You agree not to:</p>
          <ul className="list-disc list-inside text-sindio-muted mt-2 space-y-1">
            <li>Submit simulation parameters designed to degrade or overload the compute pipeline</li>
            <li>Attempt to access, modify, or extract data beyond what the interface exposes</li>
            <li>Scrape, redistribute, or resell platform data or simulation outputs</li>
            <li>Use the platform for any purpose that violates Kenyan or applicable international law</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-3">Service Availability</h2>
          <p className="text-sindio-muted">
            Sindio is provided as-is. We reserve the right to modify, suspend, or discontinue the service at any time. Scheduled maintenance windows are communicated through the Service Status page.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-3">Open Source Components</h2>
          <p className="text-sindio-muted">
            The platform incorporates open-source libraries including pandapower, EPANET, and other tools distributed under their respective licences. No proprietary claim is made over these components.
          </p>
        </section>
      </div>
    </div>
  )
}
