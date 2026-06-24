const API_BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`API ${res.status} on ${path}: ${body}`)
  }
  return res.json()
}

export type InfraType = 'power' | 'water' | 'roads' | 'solid_waste' | 'sidewalks' | 'lrt' | 'sgr' | 'airports'

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

export interface SimulateTaskStatus {
  task_id: string
  status: string
  progress: number
  result?: {
    total_alerts_generated?: number
    alerts_by_type?: Record<string, number>
    stress_geojson?: Record<string, unknown>
    summary_text?: string
    recommendation?: string
  }
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

export interface AlertsEnvelope {
  alerts: Alert[]
}

export interface UpdatesEnvelope {
  updates: {
    infrastructure_type: string
    next_update_seconds: number
    data_freshness_seconds: number
    source: string
  }[]
}

export interface ClassificationEnvelope {
  summaries: {
    class_type: string
    count: number
    infra_type: string
  }[]
}

export interface ExamplesEnvelope {
  examples: {
    asset_id: string
    class_type: string
    confidence: number
  }[]
}

export const api = {
  health: () => request<{ status: string }>('/health'),

  dashboard: {
    metrics: (system?: string) =>
      request<DashboardMetrics>(`/v1/dashboard/metrics${system ? `?system=${system}` : ''}`),
    alerts: () => request<Alert[]>('/v1/dashboard/alerts'),
  },

  infrastructure: {
    status: (system: string) => request<Record<string, unknown>>(`/v1/infrastructure/${system}`),
  },

  simulations: {
    run: (network: string) =>
      request<SimulationResult>(`/simulations/run?network=${network}`, { method: 'POST' }),
    status: () => request<{ active: number }>('/simulations/status'),
  },

  monitor: {
    stress: () => request<MonitorStressResponse>('/v1/monitor/stress'),
    types: () => request<string[]>('/v1/monitor/types'),
    classification: () => request<ClassificationEnvelope>('/v1/monitor/classification'),
    classificationExamples: (infraType: string, classType: string, limit = 5) =>
      request<ExamplesEnvelope>(
        `/v1/monitor/classification/examples?infra_type=${infraType}&classification_type=${classType}&limit=${limit}`,
      ),
  },

  spatial: {
    stressPoints: (infraType: string, limit = 60) =>
      request<GeoJsonFeatureCollection>(
        `/v1/spatial/stress-points?infrastructure_type=${infraType}&limit=${limit}`,
      ),
    stressHeatmap: (infraType: string, bbox: string) =>
      request<GeoJsonFeatureCollection>(
        `/v1/spatial/stress-heatmap?bbox=${bbox}&infrastructure_type=${infraType}`,
      ),
  },

  v1: {
    alerts: () => request<AlertsEnvelope>('/v1/alerts'),
    nextUpdates: () => request<UpdatesEnvelope>('/v1/next_updates'),
    simulateRun: (payload: Record<string, unknown>) =>
      request<SimulationResult>('/v1/simulate/run', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    simulateStatus: (taskId: string) => request<SimulateTaskStatus>(`/v1/simulate/status/${taskId}`),
    scenarioGenerate: (prompt: string, infraTypes?: string[]) =>
      request<Record<string, unknown>>('/v1/scenario/generate', {
        method: 'POST',
        body: JSON.stringify({ prompt, infrastructure_types: infraTypes }),
      }),
  },
}
