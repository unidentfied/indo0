import { ArrowLeft, Cookie } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function CookiesPage() {
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
          <Cookie className="w-5 h-5 text-sindio-accent" />
        </div>
        <h1 className="text-3xl font-bold">Cookie Policy</h1>
      </div>
      <p className="text-sindio-muted text-sm mb-10">Last updated: 1 July 2026</p>

      <div className="space-y-8 text-sm text-sindio-text leading-relaxed">
        <section>
          <h2 className="text-base font-semibold mb-3">What Cookies We Use</h2>
          <p className="text-sindio-muted">
            Sindio uses a single first-party cookie to persist your display theme preference (light or dark mode). This cookie contains the string <code className="bg-sindio-panel border border-sindio-border px-1 py-0.5 rounded text-xs">'dark'</code> or <code className="bg-sindio-panel border border-sindio-border px-1 py-0.5 rounded text-xs">'light'</code> and expires after one year.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-3">What We Do Not Use</h2>
          <ul className="list-disc list-inside text-sindio-muted space-y-1">
            <li>No analytics or tracking cookies</li>
            <li>No third-party cookies from ad networks or social platforms</li>
            <li>No session cookies beyond theme persistence</li>
            <li>No fingerprinting or device identification</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-3">Managing Cookies</h2>
          <p className="text-sindio-muted">
            You can clear the theme cookie at any time through your browser settings. Clearing it will reset the display theme to your system default on the next visit. The dashboard functions identically with or without the cookie.
          </p>
        </section>
      </div>
    </div>
  )
}
