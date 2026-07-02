import { WifiOff, AlertTriangle, X } from 'lucide-react'
import { useState } from 'react'
import { useBackendStatus } from '../services/BackendStatus'

export default function BackendBanner() {
  const { healthy, checked } = useBackendStatus()
  const [dismissed, setDismissed] = useState(false)

  if (!checked || healthy || dismissed) return null

  return (
    <div className="sticky top-0 z-[60] flex items-center justify-between gap-3 px-4 py-2 bg-amber-500/10 border-b border-amber-500/20 text-xs text-amber-400">
      <div className="flex items-center gap-2 min-w-0">
        <WifiOff className="w-3.5 h-3.5 flex-shrink-0" />
        <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
        <span className="truncate">
          Backend unavailable — displaying fallback data. Some metrics may not reflect live conditions.
        </span>
      </div>
      <button
        onClick={() => setDismissed(true)}
        className="flex-shrink-0 text-amber-400 hover:text-amber-300 transition-colors"
        aria-label="Dismiss"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}
