import { AlertTriangle, AlertOctagon, Info } from 'lucide-react'
import type { Alert } from '../types'

export default function AlertPanel({ alerts }: { alerts: Alert[] }) {
  return (
    <div className="panel">
      <div className="p-4 border-b border-sindio-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-sindio-warning" />
          <h3 className="text-sm font-semibold uppercase tracking-wider">Temporally Spaced Alerts</h3>
        </div>
        <span className="text-xs text-sindio-muted">{alerts.length} active</span>
      </div>
      <div className="divide-y divide-sindio-border max-h-96 overflow-y-auto">
        {alerts.map((alert) => {
          const Icon = alert.level === 'critical' ? AlertOctagon : alert.level === 'warning' ? AlertTriangle : Info
          const levelColor =
            alert.level === 'critical'
              ? 'text-sindio-critical border-sindio-critical'
              : alert.level === 'warning'
              ? 'text-sindio-warning border-sindio-warning'
              : 'text-sindio-advisory border-sindio-advisory'

          return (
            <div key={alert.id} className="p-4 flex gap-3 hover:bg-sindio-panel/50 transition-colors">
              <div className={`mt-0.5 ${levelColor}`}>
                <Icon className="w-4 h-4" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="text-xs text-sindio-muted">{alert.timestamp}</span>
                  <span className={`text-[10px] uppercase font-bold ${levelColor}`}>{alert.level}</span>
                </div>
                <h4 className="text-sm font-medium mb-1">{alert.title}</h4>
                <p className="text-xs text-sindio-muted">{alert.description}</p>
                {alert.location && (
                  <div className="mt-2 inline-flex items-center px-2 py-0.5 rounded text-[10px] uppercase font-medium bg-sindio-panel border border-sindio-border text-sindio-muted">
                    {alert.category}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
