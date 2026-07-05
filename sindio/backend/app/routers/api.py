from fastapi import APIRouter, HTTPException, Request
from typing import Any, List, Literal
from datetime import datetime, timezone, timedelta
import random
import time as _time_module
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.models import (
    Metric, Alert, SimulationResult, InfrastructureStatus, PredictiveParams,
    SimulateRequest, SimulateResponse, SimulationTaskResult, SimulateTaskStatus,
    AlertV1, AlertsV1Response, NextUpdate, NextUpdatesResponse,
    ScenarioGenerateRequest, ScenarioGenerateResponse, SimilarScenario,
    TaskResponse, TaskStateResponse,
)
from app.mock_simulation import (
    start_simulation, get_simulation_state, get_simulation_result,
    generate_alerts, generate_stress_heatmap, generate_stress_points,
    generate_infrastructure_status,
)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

_METRIC_LABELS: dict[str, list[str]] = {
    "power":       ["Grid Stability", "Current Load", "Active Nodes", "Latency"],
    "water":       ["Pressure Stability", "Flow Rate", "Sensor Nodes", "Leak Detection"],
    "roads":       ["Traffic Flow", "Vehicle Volume", "Monitored Junctions", "Avg Latency"],
    "solid_waste": ["Collection Rate", "Daily Volume", "Active Bins", "Overflow Risk"],
    "sidewalks":   ["Path Availability", "Pedestrian Flow", "Monitored Segments", "Obstructions"],
    "lrt":         ["On-Time Rate", "Active Trains", "Stations Online", "Signal Latency"],
    "sgr":         ["Track Integrity", "Active Trains", "Track Sensors", "Avg Delay"],
    "airports":    ["Operations Rate", "Flight Throughput", "Active Systems", "Runway Status"],
}

def _get_freshness() -> dict[str, str]:
    """Return last_updated and data_source for mock API responses."""
    return {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "data_source": "sindio-mock",
    }

_COUNT_LABELS: dict[str, str] = {
    "power": "Active Nodes", "water": "Sensor Nodes", "roads": "Monitored Junctions",
    "solid_waste": "Active Bins", "sidewalks": "Monitored Segments",
    "lrt": "Stations Online", "sgr": "Track Sensors", "airports": "Active Systems",
}


def _derive_metrics(infra_type: str, status: dict) -> list[dict]:
    labels = _METRIC_LABELS.get(infra_type, _METRIC_LABELS["power"])
    st = status["grid_stability"]
    cap = status["capacity_percent"]
    lat = status["latency_ms"]
    total = status["active_nodes"]
    load_display = status["current_load"]

    m1_status = "good" if st > 85 else ("warning" if st > 70 else "critical")
    m2_status = "good" if cap < 70 else ("warning" if cap < 85 else "critical")
    m3_status = "good"
    m4_status = "good" if lat < 20 else "warning"
    m4_val = "critical" if lat >= 40 else ("warning" if lat >= 20 else "good")

    return [
        {
            "label": labels[0],
            "value": f"{st}%",
            "status": m1_status,
        },
        {
            "label": labels[1],
            "value": load_display,
            "status": m2_status,
        },
        {
            "label": labels[2] if labels[2] == _COUNT_LABELS.get(infra_type, labels[2]) else _COUNT_LABELS.get(infra_type, labels[2]),
            "value": f"{total:,}",
            "status": m3_status,
        },
        {
            "label": labels[3],
            "value": f"{lat}ms",
            "status": m4_status,
        },
    ]


_CATEGORY_MAP: dict[str, str] = {
    "power": "electricity", "water": "water", "roads": "roads",
    "solid_waste": "waste", "sidewalks": "pedestrian",
    "lrt": "rail", "sgr": "rail", "airports": "aviation",
}


@router.get("/dashboard/metrics", response_model=List[Metric])
def get_metrics(system: str = "power"):
    status = generate_infrastructure_status(infra_type=system)
    freshness = _get_freshness()
    metrics = _derive_metrics(system, status)
    for m in metrics:
        m.update(freshness)
    return [Metric(**m) for m in metrics]


@router.get("/dashboard/alerts", response_model=List[Alert])
def get_alerts(limit: int = 5):
    raw_alerts = generate_alerts(
        count=limit,
        random_seed=int(_time_module.time() * 1000) % 4294967295,
    )
    return [
        Alert(
            id=a["id"],
            timestamp=a["timestamp"],
            level=a["level"],
            category=_CATEGORY_MAP.get(a["infrastructure_type"], "utilities"),
            title=a["title"],
            description=a["description"],
            location=a.get("ward", ""),
            confidence=a.get("confidence", 0.87),
            data_sources_used=a.get("data_sources_used", []),
            missing_data_warning=a.get("missing_data_warning"),
        )
        for a in raw_alerts
    ]


@router.get("/infrastructure/{system}", response_model=InfrastructureStatus)
def get_infrastructure(system: str):
    if system not in _METRIC_LABELS:
        raise HTTPException(404, f"Infrastructure type '{system}' not found")
    status = generate_infrastructure_status(infra_type=system)
    return InfrastructureStatus(**status)


# ── v1 aliases (frontend backward-compatibility for Core proxy fallback) ──

@router.get("/v1/dashboard/metrics", response_model=List[Metric])
def get_metrics_v1(system: str = "power"):
    """v1 alias for GET /api/dashboard/metrics."""
    return get_metrics(system)


@router.get("/v1/dashboard/alerts", response_model=List[Alert])
def get_alerts_v1(limit: int = 5):
    """v1 alias for GET /api/dashboard/alerts."""
    return get_alerts(limit)


@router.get("/v1/infrastructure/{system}", response_model=InfrastructureStatus)
def get_infrastructure_v1(system: str):
    """v1 alias for GET /api/infrastructure/{system}."""
    return get_infrastructure(system)


@router.get("/simulations/status")
def get_simulation_status():
    status = generate_infrastructure_status(infra_type="power")
    nodes = status["active_nodes"]
    stability = status["grid_stability"]
    return {
        "active": True,
        "nodes_scanned": nodes,
        "latency_ms": status["latency_ms"],
        "simulation_time": "T+04:15:00",
        "progress": round(max(0.3, stability / 100), 2),
    }


@router.post("/simulations/run", response_model=SimulationResult)
@limiter.limit("10/minute")
def run_simulation(request: Request, network: str = "power", stress_factor: str = "Population Increase (+15%)"):
    status = generate_infrastructure_status(infra_type=network)
    seed = hash(f"{network}:{stress_factor}:{_time_module.time()}") % 4294967295
    rng = random.Random(seed)
    stability = status["grid_stability"]
    base_stress = max(20, min(95, (100 - stability) * rng.uniform(1.5, 3.0)))

    impacts = [
        {"time": "00:00", "load": round(base_stress * rng.uniform(0.3, 0.5), 1)},
        {"time": "06:00", "load": round(base_stress * rng.uniform(0.5, 0.8), 1)},
        {"time": "12:00", "load": round(base_stress * rng.uniform(0.85, 1.0), 1)},
        {"time": "18:00", "load": round(base_stress * rng.uniform(0.5, 0.75), 1)},
        {"time": "23:59", "load": round(base_stress * rng.uniform(0.25, 0.45), 1)},
    ]
    failure_risk = (
        "high" if stability < 70 else ("medium" if stability < 85 else "low")
    )
    recommendations = {
        "power": "Reroute load to auxiliary substations within 2 hours.",
        "water": "Activate secondary pumping stations.",
        "roads": "Divert traffic to parallel corridors.",
        "solid_waste": "Dispatch mobile collection units.",
        "sidewalks": "Clear identified obstructions and redirect pedestrian flow.",
        "lrt": "Adjust headway to absorb passenger surge.",
        "sgr": "Reschedule freight to off-peak windows.",
        "airports": "Activate contingency runway and terminal capacity.",
    }
    return SimulationResult(
        id=f"SIM-{rng.randint(1000, 9999)}",
        network=network,
        stress_factor=stress_factor,
        projected_impacts=impacts,
        failure_risk=failure_risk,
        recommendation=recommendations.get(network, "Activate standby infrastructure capacity."),
        created_at=datetime.now().isoformat(),
    )


@router.get("/predictive-params", response_model=PredictiveParams)
def get_predictive_params():
    status = generate_infrastructure_status(infra_type="power")
    stability = status["grid_stability"]
    return PredictiveParams(
        thermal_stress=round(random.uniform(28.0, 48.0), 1),
        population_density="peak" if stability < 75 else ("med" if stability < 88 else "low"),
        grid_redundancy=status["redundancy_active"],
        automated_failover=status["redundancy_active"],
    )


# ──────────────────────────────────────────────────────────────
# Async simulation endpoints (Redis-backed, Celery-style states)
# ──────────────────────────────────────────────────────────────

@router.post("/simulate/run", response_model=TaskResponse)
def simulate_run(request: SimulateRequest):
    """Start an async mock simulation. Returns a task_id immediately."""
    result = start_simulation(
        infrastructure_type=request.infrastructure_type,
        stress_factor=request.stress_factor,
        parameters=request.parameters,
    )
    return TaskResponse(**result)


@router.get("/simulate/status/{task_id}", response_model=TaskStateResponse)
def simulate_status(task_id: str):
    """Return the current task state: PENDING | STARTED | SUCCESS | FAILURE."""
    return TaskStateResponse(**get_simulation_state(task_id))


@router.get("/simulate/result/{task_id}")
def simulate_result(task_id: str):
    """
    Return the full simulation result (GeoJSON, alerts, etc.) when SUCCESS.
    Returns 404 if the task is not yet complete.
    """
    result = get_simulation_result(task_id)
    if result is None:
        raise HTTPException(404, f"Task {task_id} is not in SUCCESS state")
    return result


# ── v1 aliases (frontend backward-compatibility) ─────────────────

@router.post("/v1/simulate/run", response_model=SimulateResponse)
def simulate_run_v1(request: SimulateRequest):
    """v1 alias for POST /api/simulate/run."""
    result = start_simulation(
        infrastructure_type=request.infrastructure_type,
        stress_factor=request.stress_factor,
        parameters=request.parameters,
    )
    return SimulateResponse(
        task_id=result["task_id"],
        status="queued",
        message=f"Simulation {result['task_id']} queued",
    )


@router.post("/v1/simulations/run", response_model=SimulateResponse)
def simulate_run_core_alias(
    network: str = "power",
    stress_factor: str = "Population Increase (+15%)",
):
    """Core-compatible alias (plural 'simulations') so the proxy and frontend can use one path.
    Accepts query parameters (not body) to match the original /simulations/run endpoint."""
    result = start_simulation(
        infrastructure_type=network,
        stress_factor=stress_factor,
        parameters=None,
    )
    return SimulateResponse(
        task_id=result["task_id"],
        status="queued",
        message=f"Simulation {result['task_id']} queued",
    )


@router.get("/v1/simulate/status/{task_id}", response_model=SimulateTaskStatus)
def simulate_status_v1(task_id: str):
    """v1 alias for GET /api/simulate/status/{task_id}, wrapped for frontend."""
    state = get_simulation_state(task_id)["state"]
    result = get_simulation_result(task_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    _state_map = {
        "PENDING": "queued",
        "STARTED": "running",
        "SUCCESS": "completed",
        "FAILURE": "failed",
    }

    _progress_map = {
        "PENDING": 0.05,
        "STARTED": 0.45,
        "SUCCESS": 1.0,
        "FAILURE": 0.0,
    }

    return SimulateTaskStatus(
        task_id=task_id,
        status=_state_map.get(state, "failed"),
        progress=_progress_map.get(state, 0.0),
        result=SimulationTaskResult(**result) if result else None,
        created_at=now_iso,
        updated_at=now_iso,
    )


# ══════════════════════════════════════════════════════════════
# v1 alert / spatial endpoints
# ══════════════════════════════════════════════════════════════

@router.get("/v1/alerts", response_model=AlertsV1Response)
def get_alerts_v1():
    alerts = generate_alerts(count=12)
    return AlertsV1Response(alerts=alerts, count=len(alerts))


@router.get("/v1/next_updates", response_model=NextUpdatesResponse)
def get_next_updates_v1():
    now = datetime.now(timezone.utc)
    updates = [
        NextUpdate(
            update_type="power",
            next_at=(now + timedelta(seconds=120)).isoformat(),
            interval_sec=120,
            description="Power grid stress monitoring",
        ),
        NextUpdate(
            update_type="water",
            next_at=(now + timedelta(seconds=600)).isoformat(),
            interval_sec=600,
            description="Water distribution pressure sweep",
        ),
        NextUpdate(
            update_type="roads",
            next_at=(now + timedelta(seconds=60)).isoformat(),
            interval_sec=60,
            description="Road congestion density scan",
        ),
        NextUpdate(
            update_type="solid_waste",
            next_at=(now + timedelta(seconds=300)).isoformat(),
            interval_sec=300,
            description="Waste collection status monitoring",
        ),
        NextUpdate(
            update_type="sidewalks",
            next_at=(now + timedelta(seconds=600)).isoformat(),
            interval_sec=600,
            description="Pedestrian path monitoring",
        ),
        NextUpdate(
            update_type="lrt",
            next_at=(now + timedelta(seconds=90)).isoformat(),
            interval_sec=90,
            description="LRT signal and train status",
        ),
        NextUpdate(
            update_type="sgr",
            next_at=(now + timedelta(seconds=180)).isoformat(),
            interval_sec=180,
            description="SGR track sensor updates",
        ),
        NextUpdate(
            update_type="airports",
            next_at=(now + timedelta(seconds=600)).isoformat(),
            interval_sec=600,
            description="Airport operations status",
        ),
    ]
    return NextUpdatesResponse(updates=updates)


@router.get("/v1/spatial/stress-heatmap")
def spatial_stress_heatmap(
    bbox: str = "36.65,-1.43,37.10,-0.98",
    infrastructure_type: str = "power",
):
    parts = [float(x.strip()) for x in bbox.split(",") if x.strip()]
    if len(parts) != 4:
        raise HTTPException(400, "bbox must be minLng,minLat,maxLng,maxLat")
    result = generate_stress_heatmap(
        infrastructure_type=infrastructure_type,
        bbox=(parts[0], parts[1], parts[2], parts[3]),
        grid_size=20,
        random_seed=hash(bbox + infrastructure_type) % 4294967295,
    )
    return result


@router.get("/v1/spatial/stress-points")
def spatial_stress_points(
    infrastructure_type: str = "power",
    limit: int = 60,
):
    """Return stress point features for scatterplot/heatmap visualization."""
    types = [infrastructure_type] if infrastructure_type != "all" else None
    features = generate_stress_points(
        infrastructure_types=types,
        random_seed=hash(infrastructure_type + str(limit)) % 4294967295,
    )
    return {
        "type": "FeatureCollection",
        "features": features[:limit],
    }


@router.get("/v1/spatial/nearest-asset")
def spatial_nearest_asset(
    lat: float = -1.2833,
    lng: float = 36.8219,
    radius_meters: float = 5000,
):
    features = generate_stress_points(
        infrastructure_types=["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"],
        random_seed=hash(f"{lat},{lng}") % 4294967295,
    )
    nearest = []
    for f in features[:5]:
        nearest.append({
            "type": "Feature",
            "geometry": f["geometry"],
            "properties": {
                "id": f["properties"]["asset_id"],
                "system_type": f["properties"]["infrastructure_type"],
                "node_name": f"Node-{f['properties']['asset_id']}",
                "distance_m": round(random.uniform(50, float(radius_meters)), 1),
                "current_load": f"{random.randint(40, 95)}%",
                "capacity": f"{random.randint(200, 2000)} kW",
                "status": f["properties"]["severity"],
            },
        })
    return {"type": "FeatureCollection", "features": nearest}


@router.post("/v1/spatial/alerts-in-polygon")
def spatial_alerts_in_polygon(payload: dict):
    """Accept a GeoJSON Feature with a Polygon geometry; return alerts within."""
    try:
        feature_type = payload.get("type", "")
        geom = payload.get("geometry", {})
        properties = payload.get("properties", {})
        severity_min = str(properties.get("severity_min", "advisory"))
    except Exception:
        raise HTTPException(400, "Invalid GeoJSON feature body")

    severity_order = {"advisory": 0, "warning": 1, "critical": 2}
    min_level = severity_order.get(severity_min, 0)

    all_alerts = generate_alerts(count=20)
    if isinstance(geom.get("coordinates"), list) and len(geom.get("coordinates", [])) > 0:
        bbox_coords = _polygon_bbox(geom["coordinates"])
        filtered = [
            a for a in all_alerts
            if _point_in_bbox((a["lng"], a["lat"]), bbox_coords)
            and severity_order.get(a["level"], 0) >= min_level
        ]
    else:
        filtered = all_alerts

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [a["lng"], a["lat"]]},
            "properties": {
                "id": a["id"],
                "title": a["title"],
                "level": a["level"],
                "category": a["category"],
                "description": a["description"],
                "created_at": a["timestamp"],
            },
        }
        for a in filtered
    ]
    return {"type": "FeatureCollection", "features": features}


@router.post("/v1/scenario/generate", response_model=ScenarioGenerateResponse)
def generate_scenario_v1(request: ScenarioGenerateRequest):
    prompt = (request.prompt or "").lower()
    year = 2032
    growth = 14

    # Extract time horizon from prompt if present
    import re
    year_match = re.search(r'(\d{4})', prompt)
    if year_match:
        year = max(2026, min(2050, int(year_match.group(1))))

    # Extract growth rate from prompt if present
    growth_match = re.search(r'(\d+)\s*%', prompt)
    if growth_match:
        growth = int(growth_match.group(1))

    # Determine which infrastructure types are relevant from the prompt
    all_types = ["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"]
    infra_types = [t for t in all_types if t.replace("_", " ") in prompt or t in prompt]
    if not infra_types:
        infra_types = ["power", "water", "roads", "solid_waste"]

    return ScenarioGenerateResponse(
        year=year,
        density_growth_rate=growth,
        infrastructure_types=infra_types,
        explanation=(
            f"RAG analysis of similar urban expansion scenarios suggests elevated "
            f"stress on {', '.join(infra_types[:3])} infrastructure at {growth}% "
            f"annual density growth projected through {year}. Based on patterns "
            f"observed in comparable rapidly-growing African metros."
        ),
        similar_scenarios=[
            SimilarScenario(
                name="Lagos Lekki Corridor 2023", year=2023,
                density_growth=12, similarity=0.87,
            ),
            SimilarScenario(
                name="Addis Ababa Bole District 2025", year=2025,
                density_growth=15, similarity=0.82,
            ),
            SimilarScenario(
                name="Nairobi Upper Hill 2024", year=2024,
                density_growth=10, similarity=0.91,
            ),
        ],
    )


# ══════════════════════════════════════════════════════════════
# v1 monitor endpoints (unified stress, classification, examples)
# ══════════════════════════════════════════════════════════════

_INFRA_TYPES = [
    {"name": "power", "display_name": "Power Grid", "unit": "MW", "total_assets": 14204},
    {"name": "water", "display_name": "Water Network", "unit": "PSI", "total_assets": 8400},
    {"name": "roads", "display_name": "Road Network", "unit": "veh/hr", "total_assets": 3200},
    {"name": "solid_waste", "display_name": "Solid Waste Collection", "unit": "tons/day", "total_assets": 156},
    {"name": "sidewalks", "display_name": "Pedestrian Infrastructure", "unit": "ped/hr", "total_assets": 2840},
    {"name": "lrt", "display_name": "Light Rail Transit", "unit": "trains", "total_assets": 24},
    {"name": "sgr", "display_name": "Standard Gauge Railway", "unit": "sections", "total_assets": 48},
    {"name": "airports", "display_name": "Airport Operations", "unit": "flights/hr", "total_assets": 186},
]

_WARDS = [
    "Kilimani", "Upper Hill", "CBD", "Westlands", "Industrial Area",
    "Eastleigh", "Karen", "Parklands", "Langata", "Ngong Road",
    "Kibera", "South B", "South C", "Donholm", "Embakasi",
]
_FAILURE_MODES = {
    "power": ["overload", "voltage_drop", "thermal_degradation", "capacity_exhaustion"],
    "water": ["pressure_loss", "pipe_burst", "contamination_risk", "flow_reduction"],
    "roads": ["surface_degradation", "congestion_overflow", "structural_fatigue", "drainage_failure"],
    "solid_waste": ["collection_overflow", "route_inefficiency", "capacity_breach", "contamination"],
    "sidewalks": ["encroachment", "surface_damage", "accessibility_loss", "pedestrian_overflow"],
    "lrt": ["schedule_drift", "capacity_overflow", "signal_degradation", "maintenance_overdue"],
    "sgr": ["track_stress", "schedule_delay", "signal_failure", "capacity_bottleneck"],
    "airports": ["runway_congestion", "terminal_overflow", "navigation_drift", "maintenance_gap"],
}
_RECOMMENDATIONS = [
    "Adjust maintenance schedule to match seasonal peak",
    "Deploy mobile units to high-stress corridors",
    "Initiate infrastructure upgrade in affected wards",
    "Increase monitoring frequency until pattern stabilizes",
    "Coordinate with urban planning for capacity expansion",
    "Implement predictive maintenance window before stress period",
]


@router.get("/v1/monitor/stress")
def monitor_stress():
    """Return stressed assets across all infrastructure types."""
    rng = random.Random(42)
    total_assets = 0
    total_stressed = 0
    total_critical = 0
    total_warning = 0
    per_type = []
    all_stressed = []

    for t in _INFRA_TYPES:
        name = t["name"]
        total = t["total_assets"]
        total_assets += total
        stressed_count = int(total * rng.uniform(0.02, 0.08))
        critical_count = int(stressed_count * rng.uniform(0.1, 0.3))
        warning_count = stressed_count - critical_count
        total_stressed += stressed_count
        total_critical += critical_count
        total_warning += warning_count
        avg_stress = round(rng.uniform(0.15, 0.45), 3)
        mock_ratio = round(rng.uniform(0.0, 0.15), 2)
        report_alignment = round(rng.uniform(0.7, 0.95), 2)

        per_type.append({
            "infrastructure_type": name,
            "display_name": t["display_name"],
            "total_assets": total,
            "stressed_assets": stressed_count,
            "critical_assets": critical_count,
            "warning_assets": warning_count,
            "avg_stress": avg_stress,
            "mock_data_ratio": mock_ratio,
            "report_alignment_pct": report_alignment,
        })

        for _ in range(min(stressed_count, 15)):
            stress = round(rng.uniform(0.4, 0.95), 3)
            all_stressed.append({
                "asset_id": f"{name[:3].upper()}-{rng.randint(1000, 9999):04d}",
                "infrastructure_type": name,
                "ward": rng.choice(_WARDS),
                "lat": round(rng.uniform(-1.38, -1.25), 6),
                "lon": round(rng.uniform(36.7, 36.93), 6),
                "current_value": round(rng.uniform(40, 95), 1),
                "capacity": round(rng.uniform(100, 200), 1),
                "stress": stress,
                "baseline_stress": round(rng.uniform(0.1, 0.3), 3),
                "baseline_deviation": round(rng.uniform(0.1, 0.6), 3),
                "failure_mode": rng.choice(_FAILURE_MODES[name]),
                "time_to_breach_hours": round(rng.uniform(1, 72), 1),
                "recommendation": rng.choice(_RECOMMENDATIONS),
                "confidence": round(rng.uniform(0.5, 0.95), 3),
                "data_source": rng.choice(["scada", "iot_sensor", "manual_report", "api_feed"]),
                "is_mock": rng.random() < mock_ratio,
                "report_aligned": rng.random() < report_alignment,
                "report_notes": "",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    all_stressed.sort(key=lambda a: a["stress"], reverse=True)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_assets_monitored": total_assets,
        "total_stressed_assets": total_stressed,
        "total_critical_assets": total_critical,
        "total_warning_assets": total_warning,
        "overall_mock_ratio": round(rng.uniform(0.05, 0.12), 2),
        "per_type_summary": per_type,
        "stressed_assets": all_stressed[:50],
    }


@router.get("/v1/monitor/classification")
def monitor_classification():
    """Return per-type stress classification summaries."""
    from datetime import timedelta
    rng = random.Random(42)

    min_windows = {
        "power": 12, "water": 12, "roads": 8, "solid_waste": 6,
        "sidewalks": 8, "lrt": 12, "sgr": 12, "airports": 6,
    }
    rho_thresholds = {
        "power": 0.6, "water": 0.55, "roads": 0.65, "solid_waste": 0.5,
        "sidewalks": 0.6, "lrt": 0.5, "sgr": 0.5, "airports": 0.55,
    }
    seasonal_mins = {
        "power": 0.25, "water": 0.3, "roads": 0.2, "solid_waste": 0.35,
        "sidewalks": 0.25, "lrt": 0.2, "sgr": 0.2, "airports": 0.3,
    }
    cv_maxs = {
        "power": 0.15, "water": 0.2, "roads": 0.1, "solid_waste": 0.25,
        "sidewalks": 0.15, "lrt": 0.1, "sgr": 0.1, "airports": 0.2,
    }

    summaries = []
    for t in _INFRA_TYPES:
        name = t["name"]
        total = t["total_assets"]
        min_window = min_windows.get(name, 6)
        rho_threshold = rho_thresholds.get(name, 0.6)
        seasonal_min = seasonal_mins.get(name, 0.25)
        cv_max = cv_maxs.get(name, 0.15)

        if name in ("lrt", "sgr"):
            recurring_pct = rng.uniform(0.45, 0.60)
            density_pct = rng.uniform(0.05, 0.15)
            mixed_pct = rng.uniform(0.10, 0.20)
        elif name in ("sidewalks", "roads"):
            recurring_pct = rng.uniform(0.15, 0.30)
            density_pct = rng.uniform(0.30, 0.45)
            mixed_pct = rng.uniform(0.15, 0.25)
        elif name in ("power", "water"):
            recurring_pct = rng.uniform(0.25, 0.40)
            density_pct = rng.uniform(0.20, 0.35)
            mixed_pct = rng.uniform(0.15, 0.25)
        else:
            recurring_pct = rng.uniform(0.20, 0.35)
            density_pct = rng.uniform(0.20, 0.35)
            mixed_pct = rng.uniform(0.10, 0.20)

        unstable_pct = max(0.0, 1.0 - recurring_pct - density_pct - mixed_pct)
        data_window = max(min_window, rng.randint(min_window, min_window + 24))

        summaries.append({
            "infrastructure_type": name,
            "display_name": t["display_name"],
            "total_assets_classified": total,
            "classification_distribution": {
                "recurring_only": {
                    "count": int(total * recurring_pct),
                    "percentage": round(recurring_pct * 100, 1),
                    "description": "Seasonal/temporal pattern detected, no population density correlation",
                },
                "density_driven_only": {
                    "count": int(total * density_pct),
                    "percentage": round(density_pct * 100, 1),
                    "description": "Strong correlation with population growth, no clear temporal pattern",
                },
                "mixed": {
                    "count": int(total * mixed_pct),
                    "percentage": round(mixed_pct * 100, 1),
                    "description": "Both recurring pattern AND population density correlation present",
                },
                "unstable": {
                    "count": int(total * unstable_pct),
                    "percentage": round(unstable_pct * 100, 1),
                    "description": "Insufficient data or no clear pattern detected",
                },
            },
            "data_window": {
                "minimum_required_months": min_window,
                "actual_available_months": data_window,
                "stl_recurring_requires_months": 36,
                "density_requires_months": min_window,
            },
            "thresholds": {
                "spearman_rho_for_density": rho_threshold,
                "stl_seasonal_strength_min": seasonal_min,
                "recurring_peak_cv_max": cv_max,
            },
            "avg_confidence": round(rng.uniform(0.55, 0.85), 3),
            "avg_spearman_rho": round(rng.uniform(0.30, 0.70), 3),
        })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "classification_types": ["recurring_only", "density_driven_only", "mixed", "unstable"],
        "summaries": summaries,
    }


@router.get("/v1/monitor/classification/examples")
def monitor_classification_examples(
    infra_type: str = "power",
    classification_type: str = "recurring_only",
    limit: int = 5,
):
    """Return example assets for a specific infrastructure type and classification."""
    rng = random.Random(hash(f"{infra_type}:{classification_type}") % (2**31))
    prefix = infra_type[:3].upper()

    examples = []
    for _ in range(min(limit, 5)):
        stress = round(rng.uniform(0.3, 0.95), 3)
        confidence = round(rng.uniform(0.5, 0.95), 3)
        examples.append({
            "asset_id": f"{prefix}-{rng.randint(1000, 9999):04d}",
            "ward": rng.choice(_WARDS),
            "stress_ml": stress,
            "confidence": confidence,
            "failure_mode": rng.choice(_FAILURE_MODES.get(infra_type, ["unknown"])),
            "recommendation": rng.choice(_RECOMMENDATIONS),
            "spearman_rho": round(rng.uniform(0.1, 0.9), 3) if classification_type in ("density_driven_only", "mixed") else None,
            "recurrence_pct": round(rng.uniform(0.5, 0.95), 3) if classification_type in ("recurring_only", "mixed") else None,
            "density_pct": round(rng.uniform(0.5, 0.95), 3) if classification_type in ("density_driven_only", "mixed") else None,
            "dominant_period_hours": round(rng.choice([12, 24, 168, 720, 8760]), 1) if classification_type in ("recurring_only", "mixed") else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    return {
        "infrastructure_type": infra_type,
        "classification_type": classification_type,
        "examples": examples,
        "source": "simulated",
    }


@router.get("/v1/monitor/types")
def monitor_types():
    """List all registered infrastructure types with their configs."""
    thresholds = {
        "power": {"warning": 0.6, "critical": 0.8, "breach": 0.95},
        "water": {"warning": 0.55, "critical": 0.75, "breach": 0.9},
        "roads": {"warning": 0.5, "critical": 0.7, "breach": 0.85},
        "solid_waste": {"warning": 0.65, "critical": 0.8, "breach": 0.95},
        "sidewalks": {"warning": 0.5, "critical": 0.7, "breach": 0.85},
        "lrt": {"warning": 0.4, "critical": 0.65, "breach": 0.8},
        "sgr": {"warning": 0.35, "critical": 0.6, "breach": 0.75},
        "airports": {"warning": 0.45, "critical": 0.7, "breach": 0.85},
    }
    return {
        "types": [
            {
                "name": t["name"],
                "display_name": t["display_name"],
                "unit": t["unit"],
                "physics_engine": "heuristic",
                "thresholds": thresholds.get(t["name"], {"warning": 0.5, "critical": 0.7, "breach": 0.85}),
                "schedule": {
                    "poll_interval_sec": 120,
                    "critical_poll_interval_sec": 30,
                    "scheduler_interval_days": 7,
                },
                "data_sources": [{"name": "scada", "type": "realtime"}],
                "report_source": "monthly",
                "report_frequency": "monthly",
            }
            for t in _INFRA_TYPES
        ]
    }


# ── spatial helpers ─────────────────────────────────────────────

def _polygon_bbox(rings: list) -> tuple[float, float, float, float]:
    """Compute minLng, minLat, maxLng, maxLat from a Polygon ring."""
    outer = rings[0] if isinstance(rings[0][0], (int, float)) else rings[0][0] if isinstance(rings[0][0], list) else rings[0] if rings else []
    if not outer:
        return (-180, -90, 180, 90)
    if isinstance(outer[0], list):
        outer = outer[0]
    lngs = [pt[0] for pt in outer]
    lats = [pt[1] for pt in outer]
    return (min(lngs), min(lats), max(lngs), max(lats))


def _point_in_bbox(point: tuple[float, float], bbox: tuple[float, float, float, float]) -> bool:
    lng, lat = point
    min_lng, min_lat, max_lng, max_lat = bbox
    return min_lng <= lng <= max_lng and min_lat <= lat <= max_lat
