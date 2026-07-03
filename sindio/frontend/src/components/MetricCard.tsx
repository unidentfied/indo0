import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import type { Metric } from '../types'

function formatTimeAgo(isoString?: string): string {
  if (!isoString) return ''
  const date = new Date(isoString)
  const now = new Date()
  const diffSec = Math.floor((now.getTime() - date.getTime()) / 1000)
  if (diffSec < 60) return 'just now'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  return `${Math.floor(diffSec / 86400)}d ago`
}

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

  const timeAgo = formatTimeAgo(metric.last_updated)
  const isReal = metric.data_source && metric.data_source !== 'sindio-mock' && metric.data_source !== 'heuristic'

  return (
    <div className={`panel p-5 border-l-2 ${borderAccent}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${statusDot}`} />
          <span className="text-xs uppercase tracking-wider text-sindio-muted">{metric.label}</span>
        </div>
        {timeAgo && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${isReal ? 'bg-emerald-500/10 text-emerald-400' : 'bg-sindio-warning/10 text-sindio-warning'}`}>
            {metric.data_source} · {timeAgo}
          </span>
        )}
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
