from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Literal
from datetime import datetime


class Metric(BaseModel):
    label: str
    value: str
    delta: Optional[str] = None
    status: Optional[Literal["good", "warning", "critical"]] = "good"
    last_updated: Optional[str] = None
    data_source: Optional[str] = None


class Alert(BaseModel):
    id: str
    timestamp: str
    level: Literal["critical", "warning", "advisory"]
    category: Literal["electricity", "utilities", "traffic", "water", "roads", "waste", "pedestrian", "rail", "aviation"]
    title: str
    description: str
    location: Optional[str] = None
    confidence: float = 0.87
    data_sources_used: List[str] = Field(default_factory=list)
    missing_data_warning: Optional[str] = None


class SimulationResult(BaseModel):
    id: str
    network: Literal["water", "power", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"]
    stress_factor: str
    projected_impacts: List[dict]
    failure_risk: Literal["low", "medium", "high"]
    recommendation: str
    created_at: str


class InfrastructureStatus(BaseModel):
    grid_stability: float
    current_load: str
    active_nodes: int
    latency_ms: int
    region: str
    capacity_percent: float
    redundancy_active: bool


class PredictiveParams(BaseModel):
    thermal_stress: float
    population_density: Literal["low", "med", "peak"]
    grid_redundancy: bool
    automated_failover: bool


# ── v1 simulation types ──────────────────────────────────────────

class SimulateRequest(BaseModel):
    infrastructure_type: str
    stress_factor: str
    parameters: Optional[Dict[str, Any]] = None


class SimulateResponse(BaseModel):
    task_id: str
    status: str
    message: str


class SimulationTaskResult(BaseModel):
    id: str
    network: str
    stress_factor: str
    projected_impacts: List[dict]
    failure_risk: str
    recommendation: str
    created_at: str
    total_alerts_generated: int = 0
    alerts_by_type: Dict[str, int] = Field(default_factory=dict)
    stress_geojson: Optional[Dict[str, Any]] = None
    summary_text: str = ""


class SimulateTaskStatus(BaseModel):
    task_id: str
    status: str
    progress: float
    result: Optional[SimulationTaskResult] = None
    created_at: str = ""
    updated_at: str = ""


# ── v1 alert types ──────────────────────────────────────────────

class AlertV1(BaseModel):
    id: str
    timestamp: str
    level: str
    category: str
    infrastructure_type: str
    ward: str
    title: str
    description: str
    location: str
    lat: float
    lng: float
    severity_score: float
    classification: Optional[str] = None
    confidence: float = 0.87
    data_sources_used: List[str] = Field(default_factory=list)
    missing_data_warning: Optional[str] = None


class AlertsV1Response(BaseModel):
    alerts: List[AlertV1]
    count: int


class NextUpdate(BaseModel):
    update_type: str
    next_at: str
    interval_sec: int
    description: str


class NextUpdatesResponse(BaseModel):
    updates: List[NextUpdate]


# ── async simulation task types ──────────────────────────────

class TaskResponse(BaseModel):
    task_id: str


class TaskStateResponse(BaseModel):
    state: str  # PENDING | STARTED | SUCCESS | FAILURE | UNKNOWN


# ── scenario types ──────────────────────────────────────────────

class ScenarioGenerateRequest(BaseModel):
    prompt: str


class SimilarScenario(BaseModel):
    name: str
    year: int
    density_growth: int
    similarity: float


class ScenarioGenerateResponse(BaseModel):
    year: int
    density_growth_rate: int
    infrastructure_types: List[str]
    explanation: str
    similar_scenarios: List[SimilarScenario]
