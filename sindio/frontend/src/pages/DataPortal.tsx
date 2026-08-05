import { useState, useEffect } from 'react'
import { api } from '../services/api'
import {
  Database, Download, Search, ChevronDown, FileJson, Map,
  Table, Clock, Layers, Code, Globe
} from 'lucide-react'

interface Dataset {
  id: string
  name: string
  description: string
  format: string
  category: string
  update_frequency: string
  record_count: number
  size_estimate: string
  license: string
  download_url: string
  api_endpoint: string
  fields: Array<{ name: string; type: string; description: string }>
  last_updated: string
}

const categoryIcons: Record<string, React.ReactNode> = {
  infrastructure: <Map className="w-4 h-4" />,
  population: <UsersIcon className="w-4 h-4" />,
  environment: <Globe className="w-4 h-4" />,
  finance: <DollarIcon className="w-4 h-4" />,
}

const categoryColors: Record<string, string> = {
  infrastructure: 'border-blue-500/30 bg-blue-500/5 text-blue-400',
  population: 'border-green-500/30 bg-green-500/5 text-green-400',
  environment: 'border-emerald-500/30 bg-emerald-500/5 text-emerald-400',
  finance: 'border-yellow-500/30 bg-yellow-500/5 text-yellow-400',
}

const formatIcons: Record<string, React.ReactNode> = {
  geojson: <Map className="w-3.5 h-3.5" />,
  csv: <Table className="w-3.5 h-3.5" />,
  json: <FileJson className="w-3.5 h-3.5" />,
}

function UsersIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  )
}

function DollarIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
    </svg>
  )
}

export default function DataPortal() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    api.datasets.list(category || undefined)
      .then(data => setDatasets(data as unknown as Dataset[]))
      .catch(err => setError(err instanceof Error ? err.message : 'Failed to load datasets'))
      .finally(() => setLoading(false))
  }, [category])

  const filtered = datasets.filter(d =>
    d.name.toLowerCase().includes(search.toLowerCase()) ||
    d.description.toLowerCase().includes(search.toLowerCase())
  )

  const categories = [...new Set(datasets.map(d => d.category))]

  return (
    <div className="min-h-screen bg-sindio-dark">
      <div className="max-w-6xl mx-auto px-4 py-12">
        <div className="mb-12">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-xl bg-sindio-accent/10 border border-sindio-accent/30 flex items-center justify-center">
              <Database className="w-5 h-5 text-sindio-accent" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-white">Nairobi Public Data Portal</h1>
              <p className="text-sindio-muted text-sm">open.nairobi.sindio.ke</p>
            </div>
          </div>
          <p className="text-sindio-muted max-w-2xl">
            Browse and download infrastructure, population, and environmental datasets for Nairobi.
            All data is licensed under CC-BY-4.0 with open API access. Transparency builds adoption.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3 mb-6">
          <div className="relative flex-1 min-w-[250px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-sindio-muted" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search datasets..."
              className="w-full bg-sindio-panel border border-sindio-border rounded-lg pl-10 pr-4 py-2.5 text-sm text-white placeholder-sindio-muted"
            />
          </div>
          {categories.map(cat => (
            <button
              key={cat}
              type="button"
              onClick={() => setCategory(category === cat ? '' : cat)}
              className={`text-xs px-3 py-2 rounded-lg border transition-colors capitalize ${
                category === cat
                  ? 'border-sindio-accent bg-sindio-accent/10 text-sindio-accent'
                  : 'border-sindio-border text-sindio-muted hover:border-sindio-muted'
              }`}
            >
              <span className="flex items-center gap-1.5">
                {categoryIcons[cat]}
                {cat}
              </span>
            </button>
          ))}
        </div>

        {loading && (
          <div className="flex items-center justify-center p-16 text-sindio-muted">
            <Clock className="w-5 h-5 animate-spin mr-2" /> Loading datasets...
          </div>
        )}

        {error && <div className="text-red-400 p-4 text-sm">{error}</div>}

        {!loading && !error && (
          <div className="space-y-3">
            {filtered.map(ds => (
              <div
                key={ds.id}
                className={`panel rounded-xl overflow-hidden transition-all ${
                  expanded === ds.id ? 'ring-1 ring-sindio-accent/30' : ''
                }`}
              >
                <button
                  type="button"
                  onClick={() => setExpanded(expanded === ds.id ? null : ds.id)}
                  className="w-full text-left p-4"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3">
                      <div className={`w-8 h-8 rounded-lg border flex items-center justify-center ${categoryColors[ds.category] || 'bg-sindio-dark border-sindio-border text-sindio-muted'}`}>
                        {formatIcons[ds.format] || <FileJson className="w-4 h-4" />}
                      </div>
                      <div>
                        <h3 className="text-sm font-semibold text-white">{ds.name}</h3>
                        <p className="text-xs text-sindio-muted mt-0.5">{ds.description}</p>
                        <div className="flex items-center gap-3 mt-1.5 text-[10px] text-sindio-muted">
                          <span className="capitalize flex items-center gap-1">{categoryIcons[ds.category]}{ds.category}</span>
                          <span>{ds.format.toUpperCase()}</span>
                          <span>{(ds.record_count || 0).toLocaleString()} records</span>
                          <span>{ds.size_estimate}</span>
                          <span className="text-green-400">{ds.license}</span>
                        </div>
                      </div>
                    </div>
                    <ChevronDown className={`w-4 h-4 text-sindio-muted flex-shrink-0 transition-transform ${expanded === ds.id ? 'rotate-180' : ''}`} />
                  </div>
                </button>

                {expanded === ds.id && (
                  <div className="px-4 pb-4 border-t border-sindio-border pt-3 space-y-3">
                    <div>
                      <h4 className="text-xs font-medium text-sindio-muted mb-1.5">Fields</h4>
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1">
                        {ds.fields.map(f => (
                          <div key={f.name} className="flex items-center gap-2 text-xs bg-sindio-dark rounded px-2 py-1 border border-sindio-border">
                            <code className="text-sindio-accent font-mono">{f.name}</code>
                            <span className="text-sindio-muted text-[10px]">{f.type}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2 text-[10px]">
                      <span className="text-sindio-muted bg-sindio-dark px-2 py-1 rounded border border-sindio-border">
                        <Clock className="w-3 h-3 inline mr-1" />Updated: {ds.update_frequency}
                      </span>
                      <span className="text-sindio-muted bg-sindio-dark px-2 py-1 rounded border border-sindio-border">
                        Last: {ds.last_updated}
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <a
                        href={ds.download_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="btn-secondary text-xs py-1.5 px-3"
                      >
                        <Download className="w-3.5 h-3.5" /> Download {ds.format.toUpperCase()}
                      </a>
                      <code className="text-[10px] text-sindio-muted bg-sindio-dark px-2 py-1 rounded border border-sindio-border">
                        {ds.api_endpoint}
                      </code>
                    </div>
                  </div>
                )}
              </div>
            ))}

            {filtered.length === 0 && (
              <div className="text-center p-16 text-sindio-muted">
                <Database className="w-8 h-8 mx-auto mb-3 opacity-40" />
                <p className="text-sm">No datasets found matching your search.</p>
              </div>
            )}
          </div>
        )}

        <div className="mt-16 p-8 panel rounded-xl">
          <div className="flex items-center gap-3 mb-4">
            <Code className="w-5 h-5 text-sindio-accent" />
            <h3 className="text-lg font-semibold text-white">API Access</h3>
          </div>
          <p className="text-sindio-muted text-sm mb-4">
            All datasets are accessible via REST API. Use the Sindio API to query, filter, and integrate
            infrastructure data directly into your applications, dashboards, or AI tools.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="bg-sindio-dark rounded-lg p-4 border border-sindio-border">
              <div className="text-xs text-sindio-muted mb-1">Base URL</div>
              <code className="text-sm text-sindio-accent font-mono">https://api.sindio.ke/api/v1</code>
            </div>
            <div className="bg-sindio-dark rounded-lg p-4 border border-sindio-border">
              <div className="text-xs text-sindio-muted mb-1">Authentication</div>
              <code className="text-sm text-sindio-accent font-mono">Bearer token</code>
            </div>
            <div className="bg-sindio-dark rounded-lg p-4 border border-sindio-border">
              <div className="text-xs text-sindio-muted mb-1">Rate Limit</div>
              <code className="text-sm text-sindio-accent font-mono">100 req/min</code>
            </div>
          </div>
        </div>

        <div className="mt-8 p-6 panel rounded-xl bg-sindio-accent/5 border-sindio-accent/20">
          <div className="flex items-center gap-2 mb-2">
            <Layers className="w-4 h-4 text-sindio-accent" />
            <h4 className="text-sm font-semibold text-sindio-accent">MCP Server Available</h4>
          </div>
          <p className="text-xs text-sindio-muted">
            Query Sindio data directly from Claude or ChatGPT using our MCP server.
            Ask questions like &ldquo;If Ngong substation fails, which neighborhoods lose power and water?&rdquo;
            and get answers backed by our infrastructure models.
          </p>
        </div>
      </div>
    </div>
  )
}
