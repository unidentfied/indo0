const API_BASE = (() => {
  try {
    const base = (import.meta as any).env?.VITE_API_BASE_URL
    if (base && typeof base === 'string') return base
  } catch { /* vitest/jsdom may lack import.meta.env */ }
  if (typeof window !== 'undefined' && window.location.hostname !== 'localhost') {
    console.error('[Sindio] VITE_API_BASE_URL is not set. All API calls will fail with 404.')
  }
  return ''
})()

const REQUEST_TIMEOUT = 8000

const pending = new Map<string, Promise<unknown>>()

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { headers: optHeaders, signal: optSignal, ...rest } = options || {}
  const method = rest.method || 'GET'
  const key = `${method}:${path}`

  // Only deduplicate GET requests to avoid POST body collisions
  if (method === 'GET' && pending.has(key)) {
    return pending.get(key) as Promise<T>
  }

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT)

  const headers = new Headers(optHeaders)
  headers.set('Content-Type', 'application/json')
  const token = localStorage.getItem('sindio_token')
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const promise = fetch(`${API_BASE}${path}`, {
    ...rest,
    headers,
    signal: controller.signal,
  })
    .then(async (res) => {
      let body: unknown
      try {
        body = await res.json()
      } catch {
        const text = await res.clone().text().catch(() => '')
        if (!res.ok) {
          throw new Error(`API ${res.status} on ${path}`)
        }
        throw new Error(`Invalid JSON response on ${path}${text ? `: ${text.slice(0, 100)}` : ''}`)
      }
      if (!res.ok) {
        const detail = (body as { detail?: string })?.detail || `API ${res.status} on ${path}`
        console.error(`[Sindio API] ${res.status} on ${path}:`, detail)
        throw new Error(detail)
      }
      return body as T
    })
    .finally(() => {
      clearTimeout(timeoutId)
      if (method === 'GET') {
        pending.delete(key)
      }
    })

  if (method === 'GET') {
    pending.set(key, promise)
  }
  return promise
}

export type InfraType = 'power' | 'water' | 'roads' | 'solid_waste' | 'sidewalks' | 'lrt' | 'sgr' | 'airports'

import type {
  Metric,
  AlertsV1Response,
  NextUpdatesResponse,
  SimulateTaskStatus,
  InfrastructureStatus,
  ClassificationResponse,
  Alert as TypesAlert,
} from '../types'

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}



export interface DashboardMetrics {
  power: { load_mw: number; redundancy: number; stress_index: number }
  water: { pressure_psi: number; flow_m3h: number; quality_ph: number }
  roads: { congestion_pct: number; avg_speed_kmh: number }
}

export interface Alert {
  id: string
  level: 'critical' | 'warning' | 'advisory'
  category: string
  title: string
  description: string
  location?: { lat: number; lng: number }
  node_id?: string
  created_at: string
}

export interface SimulationResult {
  task_id: string
  network_type: string
  stress_factor: string
  failure_risk: 'low' | 'medium' | 'high'
  recommendation: string
  status: string
}

export interface MonitorStressResponse {
  stressed_assets?: {
    infrastructure_type: string
    display_name?: string
    stressed_assets?: unknown[]
    baseline_deviation?: number
    time_to_breach_hours?: number
    recommendation?: string
  }[]
  degraded_count?: number
  total_assets_monitored?: number
  total_stressed_assets?: number
  total_critical_assets?: number
  total_warning_assets?: number
  overall_mock_ratio?: number
  per_type_summary?: {
    infrastructure_type: string
    display_name: string
    total_assets: number
    stressed_assets: number
    critical_assets: number
    warning_assets: number
    avg_stress: number
    mock_data_ratio: number
    report_alignment_pct: number
  }[]
}

export interface GeoJsonFeatureCollection {
  type: 'FeatureCollection'
  features: GeoJsonFeature[]
}

export interface GeoJsonFeature {
  type: 'Feature'
  geometry: { type: string; coordinates: number[] | number[][] | number[][][] }
  properties: Record<string, unknown>
}

export const api = {
  health: () => request<{ status: string }>('/api/health'),
  auth: {
    signup: (name: string, email: string, password: string) =>
      request<TokenResponse>('/auth/signup', {
        method: 'POST',
        body: JSON.stringify({ name, email, password }),
      }),
    login: (email: string, password: string) =>
      request<TokenResponse>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      }),
    deleteAccount: () =>
      request<{ detail: string }>('/auth/account', {
        method: 'DELETE',
      }),
  },

  dashboard: {
    metrics: (system?: string) =>
      request<Metric[]>('/api/dashboard/metrics' + (system ? `?system=${system}` : '')),
    alerts: () => request<TypesAlert[]>('/api/dashboard/alerts'),
  },

  infrastructure: {
    status: (system: string) => request<InfrastructureStatus | null>(`/api/infrastructure/${system}`),
  },

  monitor: {
    stress: () => request<MonitorStressResponse>('/api/v1/monitor/stress'),
    types: () => request<string[]>('/api/v1/monitor/types'),
    classification: () => request<ClassificationResponse>('/api/v1/monitor/classification'),
    classificationExamples: (infraType: string, classType: string, limit = 5) =>
      request<{ examples: { asset_id: string; class_type: string; confidence: number; ward: string; stress_ml: number; failure_mode: string; recommendation: string; spearman_rho: number | null; recurrence_pct: number | null; density_pct: number | null; dominant_period_hours: number | null; updated_at: string }[] }>(
        `/api/v1/monitor/classification/examples?infra_type=${infraType}&classification_type=${classType}&limit=${limit}`,
      ),
  },

  spatial: {
    stressPoints: (infraType: string, limit = 60) =>
      request<GeoJsonFeatureCollection>(
        `/api/v1/spatial/stress-points?infrastructure_type=${infraType}&limit=${limit}`,
      ),
    stressHeatmap: (infraType: string, bbox: string) =>
      request<GeoJsonFeatureCollection>(
        `/api/v1/spatial/stress-heatmap?bbox=${bbox}&infrastructure_type=${infraType}`,
      ),
  },

  v1: {
    alerts: () => request<AlertsV1Response>('/api/v1/alerts'),
    nextUpdates: () => request<NextUpdatesResponse>('/api/v1/next_updates'),
    simulateRun: (payload: Record<string, unknown>) =>
      request<SimulationResult>('/api/v1/simulate/run', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    simulateStatus: (taskId: string) => request<SimulateTaskStatus>(`/api/v1/simulate/status/${taskId}`),
    scenarioGenerate: (prompt: string, infraTypes?: string[]) =>
      request<Record<string, unknown>>('/api/v1/scenario/generate', {
        method: 'POST',
        body: JSON.stringify({ prompt, infrastructure_types: infraTypes }),
      }),
  },

  population: {
    dashboard: (citySlug: string) => request<Record<string, unknown>>(`/api/v1/population/dashboard?city_slug=${citySlug}`),
    generate: (citySlug: string, force?: boolean) => request<Record<string, unknown>>(`/api/v1/population/generate?city_slug=${citySlug}${force ? '&force=true' : ''}`, { method: 'POST' }),
  },

  carbon: {
    dashboard: (citySlug: string) => request<Record<string, unknown>>(`/api/v1/carbon/dashboard?city_slug=${citySlug}`),
    baseline: (citySlug: string, infraType: string, assetId: string) => request<Record<string, unknown>>(`/api/v1/carbon/baseline?city_slug=${citySlug}&infra_type=${infraType}&asset_id=${assetId}`),
    calculateSavings: (payload: Record<string, unknown>) => request<Record<string, unknown>>('/api/v1/carbon/calculate-savings', { method: 'POST', body: JSON.stringify(payload) }),
    registerCredit: (payload: Record<string, unknown>) => request<Record<string, unknown>>('/api/v1/carbon/register-credit', { method: 'POST', body: JSON.stringify(payload) }),
  },

  insurance: {
    dashboard: (citySlug: string) => request<Record<string, unknown>>(`/api/v1/insurance/dashboard?city_slug=${citySlug}`),
    assessRisk: (citySlug: string, assetId: string, infraType: string, stress: number) => request<Record<string, unknown>>(`/api/v1/insurance/assess-risk?city_slug=${citySlug}&asset_id=${assetId}&infra_type=${infraType}&current_stress=${stress}`),
    createPolicy: (payload: Record<string, unknown>) => request<Record<string, unknown>>('/api/v1/insurance/create-policy', { method: 'POST', body: JSON.stringify(payload) }),
  },

  cascade: {
    analyze: (assetType: string, assetId: string, citySlug = 'nairobi') =>
      request<Record<string, unknown>>(`/api/v1/cascade/analyze?asset_type=${assetType}&asset_id=${assetId}&city_slug=${citySlug}`),
    analyzePost: (payload: { asset_type: string; asset_id: string; city_slug?: string }) =>
      request<Record<string, unknown>>('/api/v1/cascade/analyze', { method: 'POST', body: JSON.stringify(payload) }),
    assets: () => request<{ asset_id: string; asset_type: string; name: string; ward: string }[]>('/api/v1/cascade/assets'),
    dependencies: (assetId: string) => request<Record<string, unknown>>(`/api/v1/cascade/dependencies/${assetId}`),
  },

  dataFreshness: () => request<Record<string, unknown>>('/api/v1/data-freshness/'),

  nlMap: {
    query: (text: string) =>
      request<Record<string, unknown>>('/api/v1/nl-map/query', {
        method: 'POST',
        body: JSON.stringify({ query: text }),
      }),
  },

  roi: {
    calculate: (payload: Record<string, unknown>) =>
      request<Record<string, unknown>>('/api/v1/roi/calculate', { method: 'POST', body: JSON.stringify(payload) }),
    upgradeOptions: (infraType: string) =>
      request<{ asset_id: string; name: string; typical_cost_kes: number; typical_annual_savings_kes: number; description: string; payback_years: number }[]>(`/api/v1/roi/upgrade-options?infra_type=${infraType}`),
  },

  datasets: {
    list: (category?: string) =>
      request<Record<string, unknown>[]>(`/api/v1/datasets${category ? `?category=${category}` : ''}`),
    get: (datasetId: string) =>
      request<Record<string, unknown>>(`/api/v1/datasets/${datasetId}`),
    download: (datasetId: string) =>
      request<Record<string, unknown>>(`/api/v1/datasets/${datasetId}/download`),
  },

  citizenReports: {
    create: (payload: Record<string, unknown>) =>
      request<Record<string, unknown>>('/api/v1/citizen-reports/', { method: 'POST', body: JSON.stringify(payload) }),
    list: (params?: Record<string, string>) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : ''
      return request<Record<string, unknown>>(`/api/v1/citizen-reports/${qs}`)
    },
    geojson: (params?: Record<string, string>) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : ''
      return request<Record<string, unknown>>(`/api/v1/citizen-reports/geojson${qs}`)
    },
    update: (reportId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(`/api/v1/citizen-reports/${reportId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    upvote: (reportId: string) =>
      request<Record<string, unknown>>(`/api/v1/citizen-reports/${reportId}/upvote`, { method: 'POST' }),
    stats: () => request<Record<string, unknown>>('/api/v1/citizen-reports/stats'),
  },
}
