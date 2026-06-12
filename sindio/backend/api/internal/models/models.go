package models

// --- v0 types (legacy dashboard) ---

type Metric struct {
	Label  string `json:"label"`
	Value  string `json:"value"`
	Delta  string `json:"delta,omitempty"`
	Status string `json:"status"`
}

type Alert struct {
	ID                  string   `json:"id"`
	Timestamp           string   `json:"timestamp"`
	Level               string   `json:"level"`
	Category            string   `json:"category"`
	Title               string   `json:"title"`
	Description         string   `json:"description"`
	Location            string   `json:"location,omitempty"`
	Confidence          float64  `json:"confidence"`
	DataSourcesUsed     []string `json:"data_sources_used"`
	MissingDataWarning  *string  `json:"missing_data_warning"`
}

type InfrastructureStatus struct {
	GridStability    float64 `json:"grid_stability"`
	CurrentLoad      string  `json:"current_load"`
	ActiveNodes      int     `json:"active_nodes"`
	LatencyMs        int     `json:"latency_ms"`
	Region           string  `json:"region"`
	CapacityPercent  float64 `json:"capacity_percent"`
	RedundancyActive bool    `json:"redundancy_active"`
	// DB-populated fields (used by handlers.go real queries)
	CurrentLoadStr   string  `json:"-"`
	Capacity         float64 `json:"-"`
	CurrentLoadRaw   float64 `json:"-"`
	DegradedNodes    int     `json:"-"`
}

type Impact struct {
	Time string `json:"time"`
	Load int    `json:"load"`
}

type SimulationResult struct {
	ID               string   `json:"id"`
	Network          string   `json:"network"`
	StressFactor     string   `json:"stress_factor"`
	ProjectedImpacts []Impact `json:"projected_impacts"`
	FailureRisk      string   `json:"failure_risk"`
	Recommendation   string   `json:"recommendation"`
	CreatedAt        string   `json:"created_at"`
}

// --- v1 types (API gateway) ---

// AlertV1 is the enriched alert model with geolocation and severity scoring.
type AlertV1 struct {
	ID                 string   `json:"id"`
	Timestamp          string   `json:"timestamp"`
	Level              string   `json:"level"`
	Category           string   `json:"category"`
	InfrastructureType string   `json:"infrastructure_type"`
	Ward               string   `json:"ward"`
	Title              string   `json:"title"`
	Description        string   `json:"description"`
	Location           string   `json:"location,omitempty"`
	Lat                float64  `json:"lat"`
	Lng                float64  `json:"lng"`
	SeverityScore      float64  `json:"severity_score"`
	Confidence         float64  `json:"confidence"`
	DataSourcesUsed    []string `json:"data_sources_used"`
	MissingDataWarning *string  `json:"missing_data_warning"`
}

// AlertExplanation is a RAG-generated explanation for a specific alert.
type AlertExplanation struct {
	AlertID        string  `json:"alert_id"`
	Summary        string  `json:"summary"`
	RootCause      string  `json:"root_cause"`
	Impact         string  `json:"impact"`
	Recommendation string  `json:"recommendation"`
	Confidence     float64 `json:"confidence"`
}

// SimulateRequest is the payload for triggering an async simulation.
type SimulateRequest struct {
	InfrastructureType string                 `json:"infrastructure_type" binding:"required"`
	StressFactor       string                 `json:"stress_factor"`
	Parameters         map[string]interface{} `json:"parameters"`
}

// SimulateResponse is returned after a simulation is queued.
type SimulateResponse struct {
	TaskID  string `json:"task_id"`
	Status  string `json:"status"`
	Message string `json:"message"`
}

// SimulateStatus is the polling response for an async simulation task.
type SimulateStatus struct {
	TaskID    string            `json:"task_id"`
	Status    string            `json:"status"`
	Progress  float64           `json:"progress"`
	Result    *SimulationResult `json:"result,omitempty"`
	CreatedAt string            `json:"created_at"`
	UpdatedAt string            `json:"updated_at"`
}

// NextUpdate describes the next scheduled update for a feed type.
type NextUpdate struct {
	UpdateType  string `json:"update_type"`
	NextAt      string `json:"next_at"`
	IntervalSec int    `json:"interval_sec"`
	Description string `json:"description"`
}

// ExplainSpacingResponse is the data-driven temporal spacing explanation.
type ExplainSpacingResponse struct {
	AssetID               string                 `json:"asset_id"`
	InfrastructureType    string                 `json:"infrastructure_type"`
	ExplanationText       string                 `json:"explanation_text"`
	RecommendedInterval   int                    `json:"recommended_interval_days"`
	ConfidenceIntervalDays int                   `json:"confidence_interval_days"`
	DataSourcesUsed       []string              `json:"data_sources_used"`
	Metrics               ExplainSpacingMetrics  `json:"metrics"`
	Cached                bool                   `json:"cached"`
}

// ExplainSpacingMetrics holds the quantitative inputs for the explanation.
type ExplainSpacingMetrics struct {
	HistoricalFailuresCount     int      `json:"historical_failures_count"`
	MeanTimeBetweenFailuresDays float64  `json:"mean_time_between_failures_days"`
	StressVelocityPerMonth      float64  `json:"stress_velocity_per_month"`
	DensitySpearmanRho          float64  `json:"density_spearman_rho"`
	AssetAgeYears               float64  `json:"asset_age_years"`
	LastMaintenanceDaysAgo      int      `json:"last_maintenance_days_ago"`
	IsRecurring                 bool     `json:"is_recurring"`
	RecurringPattern            *string  `json:"recurring_pattern,omitempty"`
}
