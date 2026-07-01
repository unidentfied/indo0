import { useState, useEffect } from 'react'
import { CalendarClock } from 'lucide-react'
import { api } from '../services/api'
import infraIcons from './InfraIcons'

interface UpdateEntry {
  update_type: string
  next_at: string
  interval_sec: number
  description: string
}

const CRITICAL_INTERVALS: Record<string, number> = {
  power: 30, water: 120, roads: 15, solid_waste: 60,
  sidewalks: 90, lrt: 20, sgr: 45, airports: 60,
}

function fmtSec(s: number): string {
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 86400) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

function countdownStr(target: string): string {
  const diff = new Date(target).getTime() - Date.now()
  if (diff <= 0) return 'now'
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

export default function ScheduleStatus() {
  const [entries, setEntries] = useState<UpdateEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [, setTick] = useState(0)

  useEffect(() => {
    api.v1.nextUpdates()
      .then(d => {
        setEntries(d?.updates || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  if (loading) {
    return (
      <div className="panel p-6">
        <div className="flex items-center gap-2 mb-4">
          <CalendarClock className="w-4 h-4 text-sindio-accent" />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Schedule Status</h3>
        </div>
        <div className="text-xs text-sindio-muted text-center py-8">Loading schedule...</div>
      </div>
    )
  }

  const displayOrder = ['power', 'water', 'roads', 'solid_waste', 'sidewalks', 'lrt', 'sgr', 'airports']
  const sorted = displayOrder.filter(t => entries.some(e => e.update_type === t))

  return (
    <div className="panel">
      <div className="p-4 border-b border-sindio-border">
        <div className="flex items-center gap-2">
          <CalendarClock className="w-4 h-4 text-sindio-accent" />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-sindio-accent">Schedule Status</h3>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-sindio-border">
              <th className="text-left p-3 text-sindio-muted font-medium uppercase tracking-wider text-[10px]">Type</th>
              <th className="text-left p-3 text-sindio-muted font-medium uppercase tracking-wider text-[10px]">Interval</th>
              <th className="text-left p-3 text-sindio-muted font-medium uppercase tracking-wider text-[10px]">Critical At</th>
              <th className="text-left p-3 text-sindio-muted font-medium uppercase tracking-wider text-[10px]">Next In</th>
              <th className="text-right p-3 text-sindio-muted font-medium uppercase tracking-wider text-[10px]">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-sindio-border">
            {sorted.map(t => {
              const e = entries.find(x => x.update_type === t)
              if (!e) return null
              const critInt = CRITICAL_INTERVALS[t] || 60
              const nextIn = countdownStr(e.next_at)
              const isNear = new Date(e.next_at).getTime() - Date.now() < critInt * 1000
              return (
                <tr key={t} className="hover:bg-sindio-panel/50 transition-colors">
                  <td className="p-3">
                    <div className="flex items-center gap-2.5">
                      <span className="flex items-center justify-center w-7 h-7 rounded-lg bg-sindio-panel border border-sindio-border">
                        {infraIcons[t]}
                      </span>
                      <span className="font-medium text-sindio-text">{e.update_type}</span>
                    </div>
                  </td>
                  <td className="p-3 text-sindio-muted font-mono">{fmtSec(e.interval_sec)}</td>
                  <td className="p-3 text-sindio-muted font-mono">{fmtSec(critInt)}</td>
                  <td className={`p-3 font-mono ${isNear ? 'text-sindio-warning font-semibold' : 'text-sindio-muted'}`}>
                    {nextIn}
                  </td>
                  <td className="p-3 text-right">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] uppercase font-bold tracking-wide ${
                      isNear ? 'bg-sindio-warning/10 text-sindio-warning' : 'bg-emerald-400/10 text-emerald-400'
                    }`}>
                      {isNear ? 'critical' : 'standard'}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
