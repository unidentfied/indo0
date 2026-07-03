export type InfraTypeId = 'power' | 'water' | 'roads' | 'solid_waste' | 'sidewalks' | 'lrt' | 'sgr' | 'airports'

export interface Metric {
  label: string
  value: string
  delta?: string
  status: 'good' | 'warning' | 'critical'
  last_updated?: string
  data_source?: string
}

export interface Alert {
  id: string
  timestamp: string
  level: 'critical' | 'warning' | 'advisory'
  category: 'electricity' | 'utilities' | 'traffic' | 'water' | 'roads' | 'waste' | 'pedestrian' | 'rail' | 'aviation'
  title: string
  description: string
  location?: string
  confidence?: number
  data_sources_used?: string[]
  missing_data_warning?: string | null
}

export interface SimulationResult {
  id: string
  network: InfraTypeId
  stress_factor: string
  projected_impacts: { time: string; load: number }[]
  failure_risk: 'low' | 'medium' | 'high'
  recommendation: string
  created_at: string
  total_alerts_generated?: number
  alerts_by_type?: Record<string, number>
  stress_geojson?: GeoJSON.FeatureCollection | null
  summary_text?: string
}

export interface InfrastructureStatus {
  grid_stability: number
  current_load: string
  active_nodes: number
  latency_ms: number
  region: string
  capacity_percent: number
  redundancy_active: boolean
}

export interface PredictiveParams {
  thermal_stress: number
  population_density: 'low' | 'med' | 'peak'
  grid_redundancy: boolean
  automated_failover: boolean
}

// --- Map / spatial types ---

export interface StressPoint {
  lng: number
  lat: number
  stress: number
  asset_id: string
  classification: string
  recurring: boolean
}

export interface GridCellFeature {
  type: 'Feature'
  geometry: {
    type: 'Polygon'
    coordinates: number[][][]
  }
  properties: {
    stress: number
    node_count: number
  }
}

export interface StressHeatmapResponse {
  type: 'FeatureCollection'
  features: GridCellFeature[]
}

export interface WaterMainLine {
  id: string
  coordinates: [number, number][]
  stress: number
  name: string
}

export interface AssetDetail {
  id: string
  node_name: string
  system_type: InfraTypeId
  stress: number
  classification: string
  lng: number
  lat: number
  timeseries: { time: string; stress: number }[]
  explanation: string
  recommendation: string
}

// --- Alert feed types ---

export interface AlertV1 {
  id: string
  timestamp: string
  level: 'critical' | 'warning' | 'advisory'
  category: string
  infrastructure_type: string
  ward: string
  title: string
  description: string
  location: string
  lat: number
  lng: number
  severity_score: number
  classification?: 'recurring' | 'density_driven' | 'hybrid'
  confidence?: number
  data_sources_used?: string[]
  missing_data_warning?: string | null
}

export interface AlertsV1Response {
  alerts: AlertV1[]
  count: number
}

export interface NextUpdate {
  update_type: string
  next_at: string
  interval_sec: number
  description: string
}

export interface NextUpdatesResponse {
  updates: NextUpdate[]
}

// --- Simulation / scenario types ---

export interface SimulateRequest {
  infrastructure_type: string
  stress_factor: string
  parameters?: Record<string, unknown>
}

export interface SimulateResponse {
  task_id: string
  status: string
  message: string
}

export interface SimulateTaskStatus {
  task_id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'pending' | 'started' | 'success'
  progress: number
  result: SimulationResult | null
  created_at: string
  updated_at: string
}

export interface ScenarioGenerateRequest {
  prompt: string
}

export interface ScenarioGenerateResponse {
  year: number
  density_growth_rate: number
  infrastructure_types: string[]
  explanation: string
  similar_scenarios: { name: string; year: number; density_growth: number; similarity: number }[]
}

export interface SimulationSummary {
  task_id: string
  total_alerts_generated: number
  alerts_by_type: Record<string, number>
  stress_geojson: GeoJSON.FeatureCollection | null
  summary_text: string
}

// --- Classification types ---

export type ClassificationType = 'recurring_only' | 'density_driven_only' | 'mixed' | 'unstable'

export interface ClassificationDistributionEntry {
  count: number
  percentage: number
  description: string
}

export interface ClassificationDistribution {
  recurring_only: ClassificationDistributionEntry
  density_driven_only: ClassificationDistributionEntry
  mixed: ClassificationDistributionEntry
  unstable: ClassificationDistributionEntry
}

export interface DataWindowInfo {
  minimum_required_months: number
  actual_available_months: number
  stl_recurring_requires_months: number
  density_requires_months: number
}

export interface ClassificationThresholds {
  spearman_rho_for_density: number
  stl_seasonal_strength_min: number
  recurring_peak_cv_max: number
}

export interface ClassificationSummary {
  infrastructure_type: InfraTypeId
  display_name: string
  total_assets_classified: number
  classification_distribution: ClassificationDistribution
  data_window: DataWindowInfo
  thresholds: ClassificationThresholds
  avg_confidence: number
  avg_spearman_rho: number
}

export interface ClassificationResponse {
  timestamp: string
  classification_types: ClassificationType[]
  summaries: ClassificationSummary[]
}
