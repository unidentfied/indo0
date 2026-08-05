import { useState } from 'react'
import { api } from '../services/api'
import { Search } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

interface NlMapResult {
  query: string
  parsed: { infra_type: string; wards: string[]; action: string }
  geojson: { type: string; features: Array<{ geometry: { coordinates: number[] }; properties: Record<string, unknown> }> }
  viewport: { center: { lat: number; lng: number }; zoom: number }
  result_count: number
  explanation: string
}

export default function NlMapSearch({ onResult }: { onResult?: (result: NlMapResult) => void }) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<NlMapResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [, setSearchParams] = useSearchParams()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setError(null)
    try {
      const r = await api.nlMap.query(query.trim()) as unknown as NlMapResult
      setResult(r)
      setSearchParams({ system: r.parsed.infra_type }, { replace: true })
      onResult?.(r)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-3">
      <form onSubmit={handleSubmit} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-sindio-muted" />
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search assets, wards, or infrastructure types..."
            className="w-full bg-sindio-panel border border-sindio-border rounded-lg pl-10 pr-4 py-2.5 text-sm text-white placeholder-sindio-muted focus:border-sindio-accent focus:outline-none"
          />
        </div>
        <button type="submit" disabled={loading || !query.trim()} className="btn-primary text-sm py-2">
          {loading ? '...' : 'Query'}
        </button>
      </form>
      {error && <div className="text-red-400 text-xs">{error}</div>}
      {result && (
        <div className="bg-sindio-panel border border-sindio-border rounded px-3 py-2">
          <div className="text-xs text-sindio-muted">{result.explanation}</div>
          <div className="flex items-center gap-3 mt-1 text-[10px] text-sindio-muted">
            <span>{result.result_count} assets</span>
            <span className="capitalize">{result.parsed.infra_type.replace('_', ' ')}</span>
            <span>{result.parsed.wards.length} wards</span>
          </div>
        </div>
      )}
    </div>
  )
}
