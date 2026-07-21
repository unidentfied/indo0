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
  const method = options?.method || 'GET'
  const key = `${method}:${path}`

  // Only deduplicate GET requests to avoid POST body collisions
  if (method === 'GET' && pending.has(key)) {
    return pending.get(key) as Promise<T>
  }

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT)

  const headers = new Headers(options?.headers)
  headers.set('Content-Type', 'application/json')
  // Auth is handled via HTTP-only cookies or JWT Bearer set by caller; never bake keys into the bundle

  const promise = fetch(`${API_BASE}${path}`, {
    headers,
    signal: controller.signal,
    ...options,
  })
    .then(async (res) => {
      if (!res.ok) {
        const body = await res.text()
        console.error(`[Sindio API] ${res.status} on ${path}:`, body)
        throw new Error(`API ${res.status} on ${path}: ${body}`)
      }
      return res.json() as T
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
}
