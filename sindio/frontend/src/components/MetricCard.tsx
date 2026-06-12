import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import type { Metric } from '../types'

export default function MetricCard({ metric }: { metric: Metric }) {
  const statusColor =
    metric.status === 'critical'
      ? 'text-sindio-critical'
      : metric.status === 'warning'
        ? 'text-sindio-warning'
        : 'text-emerald-400'

  const statusDot =
    metric.status === 'critical'
      ? 'bg-sindio-critical'
      : metric.status === 'warning'
        ? 'bg-sindio-warning'
        : 'bg-emerald-400'

  const borderAccent =
    metric.status === 'critical'
      ? 'border-l-sindio-critical'
      : metric.status === 'warning'
        ? 'border-l-sindio-warning'
        : 'border-l-emerald-400'

  const Trend = metric.delta?.startsWith('+')
    ? TrendingUp
    : metric.delta?.startsWith('-')
      ? TrendingDown
      : Minus

  return (
    <div className={`panel p-5 border-l-2 ${borderAccent}`}>
      <div className="flex items-center gap-1.5 mb-2">
        <span className={`w-1.5 h-1.5 rounded-full ${statusDot}`} />
        <span className="text-xs uppercase tracking-wider text-sindio-muted">{metric.label}</span>
      </div>
      <div className="flex items-end justify-between">
        <div className={`text-2xl font-semibold ${statusColor}`}>{metric.value}</div>
        {metric.delta && (
          <div className={`flex items-center gap-1 text-xs ${metric.delta.startsWith('+') ? 'text-emerald-400' : 'text-sindio-muted'}`}>
            <Trend className="w-3 h-3" />
            {metric.delta}
          </div>
        )}
      </div>
    </div>
  )
}
