"""
Mock simulation generator that produces realistic GeoJSON alerts without ML.

Places stress points on high-density zones from the Nairobi population raster,
adds random jitter, and assigns timestamps within the last 24 hours.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np

try:
    from .population_raster import sample_high_density_points
except ImportError:
    from population_raster import sample_high_density_points

logger = logging.getLogger("sindio.mock_simulation")

NAIROBI_WARDS = [
    "Kilimani", "Upper Hill", "CBD", "Westlands", "Industrial Area",
    "Eastleigh", "Karen", "Parklands", "Langata", "Ngong Road",
    "Kibera", "South B", "South C", "Donholm", "Embakasi",
]
CATEGORIES = ["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"]
LEVELS = ["critical", "warning", "advisory"]

_DATA_SOURCES = {
    "power":        ["population_2025", "power_load_last_7d", "grid_redundancy_status"],
    "water":        ["population_2025", "water_pressure_last_7d", "osm_water_mains"],
    "roads":        ["population_2025", "mobility_aggregates_last_7d", "osm_road_width"],
    "solid_waste":  ["population_2025", "waste_collection_last_7d", "osm_service_routes"],
    "sidewalks":    ["population_2025", "pedestrian_flow_last_7d", "osm_sidewalks"],
    "lrt":          ["population_2025", "lrt_schedule_last_7d", "lrt_sensor_telemetry"],
    "sgr":          ["population_2025", "sgr_freight_last_7d", "sgr_track_sensors"],
    "airports":     ["population_2025", "flight_schedule_last_7d", "airport_operations"],
}

_MISSING_WARNINGS = [
    "No real-time power data for last 6 hours, used historic average",
    "Water pressure sensor offline in this ward, interpolated from adjacent zones",
    "Mobility stream delayed by 15 minutes, using last available aggregate",
    "Grid redundancy status not updated today, using cached value",
    None,
]


def _threshold_to_level(stress: float) -> str:
    if stress >= 80:
        return "critical"
    if stress >= 60:
        return "warning"
    if stress >= 40:
        return "advisory"
    return "advisory"


def _classification(stress: float, recurring: bool) -> str:
    if recurring:
        return "recurring"
    if stress >= 70:
        return "density_driven"
    return "hybrid"


def _random_timestamp(rng: np.random.RandomState) -> str:
    seconds_ago = rng.uniform(0, 86400)
    ts = datetime.now(timezone.utc) - timedelta(seconds=float(seconds_ago))
    return ts.isoformat()


# ---------------------------------------------------------------------------
# GeoJSON stress-point features (individual Point geometries)
# ---------------------------------------------------------------------------

WARD_SHAPES: dict[str, tuple[float, float, float, float, float, float]] = {
    "Kilimani":        (36.775, -1.296, 36.795, -1.282, 28.0, 7.5),
    "Upper Hill":      (36.802, -1.308, 36.820, -1.290, 24.0, 6.0),
    "CBD":             (36.815, -1.295, 36.832, -1.275, 45.0, 9.0),
    "Westlands":       (36.796, -1.278, 36.820, -1.258, 22.0, 5.5),
    "Industrial Area": (36.838, -1.330, 36.862, -1.310, 28.0, 7.0),
    "Eastleigh":       (36.846, -1.282, 36.866, -1.262, 40.0, 8.5),
    "Karen":           (36.710, -1.395, 36.735, -1.370, 12.0, 3.0),
    "Parklands":       (36.792, -1.270, 36.810, -1.250, 18.0, 5.0),
    "Langata":         (36.775, -1.385, 36.800, -1.365, 14.0, 4.0),
    "Ngong Road":      (36.775, -1.310, 36.795, -1.295, 20.0, 5.5),
    "Kibera":          (36.770, -1.318, 36.790, -1.305, 35.0, 8.0),
    "South B":         (36.835, -1.322, 36.850, -1.312, 22.0, 6.0),
    "South C":         (36.845, -1.330, 36.860, -1.318, 24.0, 6.0),
    "Donholm":         (36.875, -1.298, 36.895, -1.282, 26.0, 7.0),
    "Embakasi":        (36.890, -1.340, 36.930, -1.300, 30.0, 7.5),
}


def _assign_ward(lat: float, lng: float, rng: np.random.RandomState) -> str:
    for name, (w, s, e, n, *_rest) in WARD_SHAPES.items():
        if w <= lng <= e and s <= lat <= n:
            return name
    return rng.choice(NAIROBI_WARDS[:8])


def generate_stress_points(
    infrastructure_types: Optional[list[str]] = None,
    random_seed: Optional[int] = None,
) -> list[dict]:
    """
    Generate stress-point GeoJSON Feature dicts placed on high-density
    locations from the WorldPop raster, with random jitter and timestamps.
    """
    if infrastructure_types is None:
        infrastructure_types = ["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"]

    rng = np.random.RandomState(random_seed)
    seed = random_seed if random_seed is not None else 42

    density_points = sample_high_density_points(max_points=100, random_seed=seed)
    features: list[dict] = []
    asset_counter = rng.randint(1, 9000)

    for pt in density_points:
        lat = pt["lat"] + rng.uniform(-0.004, 0.004)
        lng = pt["lng"] + rng.uniform(-0.004, 0.004)
        density = pt["density"]

        base_stress = min(95, (density / 5000.0) * rng.uniform(30, 70))
        stress = round(float(base_stress + rng.uniform(-8, 8)), 1)
        stress = max(5.0, min(98.0, stress))

        recurring = rng.random() < 0.3
        infra_type = rng.choice(infrastructure_types)
        ward = _assign_ward(lat, lng, rng)
        classification = _classification(stress, recurring)

        asset_counter += 1
        timestamp = _random_timestamp(rng)

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [round(lng, 6), round(lat, 6)],
            },
            "properties": {
                "asset_id": f"AST-{asset_counter:04d}",
                "stress": stress,
                "density": round(density, 1),
                "severity": _threshold_to_level(stress),
                "infrastructure_type": infra_type,
                "ward": ward,
                "classification": classification,
                "recurring": recurring,
                "node_count": int(rng.randint(2, 18)),
                "timestamp": timestamp,
                "confidence": round(rng.uniform(0.78, 0.96), 2),
                "data_sources_used": _DATA_SOURCES.get(infra_type, _DATA_SOURCES["power"]),
                "missing_data_warning": rng.choice(_MISSING_WARNINGS),
            },
        })

    logger.info("Generated %d stress-point features", len(features))
    return features


# ---------------------------------------------------------------------------
# Stress-heatmap grid cells (Polygon geometries tiling Nairobi)
# ---------------------------------------------------------------------------

def generate_stress_heatmap(
    infrastructure_type: str = "power",
    bbox: Optional[tuple[float, float, float, float]] = None,
    grid_size: int = 20,
    random_seed: Optional[int] = None,
) -> dict:
    """
    Return a GeoJSON FeatureCollection of polygon grid cells with stress (0-100)
    covering the requested bounding box or greater Nairobi.
    """
    if bbox is None:
        bbox = (36.65, -1.43, 37.10, -0.98)

    min_lng, min_lat, max_lng, max_lat = bbox
    rng = np.random.RandomState(random_seed)

    lng_step = (max_lng - min_lng) / grid_size
    lat_step = (max_lat - min_lat) / grid_size

    density_points = sample_high_density_points(max_points=100, random_seed=random_seed or 42)

    def _stress_at(lng_c: float, lat_c: float) -> float:
        total_w = 0.0
        total_s = 0.0
        for pt in density_points:
            dist = np.sqrt((pt["lng"] - lng_c) ** 2 + (pt["lat"] - lat_c) ** 2)
            if dist < 0.03:
                w = 1.0 - (dist / 0.03)
                total_w += w
                total_s += w * min(95, (pt["density"] / 5000.0) * 50 + rng.uniform(5, 30))
        if total_w > 0:
            return round(float(total_s / total_w), 1)
        return round(float(rng.uniform(5, 25)), 1)

    features: list[dict] = []
    for i in range(grid_size):
        for j in range(grid_size):
            w = min_lng + i * lng_step
            s = min_lat + j * lat_step
            e = w + lng_step
            n = s + lat_step
            stress = _stress_at((w + e) / 2, (s + n) / 2)
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [w, s], [e, s], [e, n], [w, n], [w, s],
                    ]],
                },
                "properties": {
                    "stress": stress,
                    "node_count": int(max(1, stress // 10)),
                },
            })

    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# Simulation orchestrator (Redis-backed; synchronous background via thread)
# ---------------------------------------------------------------------------

import threading
from . import redis_store as store


def _build_simulation_result(
    task_id: str,
    infra_types: list[str],
    stress_factor: str,
    created_at: str,
) -> dict:
    """Compute stress points and assemble the full result payload."""
    seed = hash(task_id) % 4294967295

    stress_features = generate_stress_points(
        infrastructure_types=infra_types,
        random_seed=seed,
    )

    alerts_by_type: dict[str, int] = {}
    for f in stress_features:
        t = f["properties"]["infrastructure_type"]
        alerts_by_type[t] = alerts_by_type.get(t, 0) + 1

    total = len(stress_features)
    avg_stress = (
        sum(f["properties"]["stress"] for f in stress_features) / total
        if total else 0
    )

    rec_text = (
        f"{total} stress points identified across {', '.join(infra_types)}. "
        f"Mean stress: {avg_stress:.0f}/100. "
        f"Density-driven failures concentrated in high-population wards. "
        f"Recommend staged mitigation across primary corridors."
    )

    return {
        "id": f"SIM-{task_id}",
        "network": infra_types[0] if infra_types else "power",
        "stress_factor": stress_factor,
        "projected_impacts": [
            {"time": "00:00", "load": 40},
            {"time": "06:00", "load": 65},
            {"time": "12:00", "load": 92},
            {"time": "18:00", "load": 55},
            {"time": "23:59", "load": 30},
        ],
        "failure_risk": "high" if avg_stress > 60 else "medium",
        "recommendation": rec_text,
        "created_at": created_at,
        "total_alerts_generated": total,
        "alerts_by_type": alerts_by_type,
        "stress_geojson": {
            "type": "FeatureCollection",
            "features": stress_features,
        },
        "summary_text": rec_text,
    }


def _run_in_background(task_id: str, created_at: str, infra_types: list[str], stress_factor: str) -> None:
    """Run the simulation (in a background thread) and update Redis state."""
    try:
        store.set_started(task_id)

        # Simulate processing time (~8 s)
        import time as _time
        _time.sleep(8)

        result = _build_simulation_result(task_id, infra_types, stress_factor, created_at)
        store.set_success(task_id, result)
        logger.info("Simulation %s completed — %d points", task_id, len(result["stress_geojson"]["features"]))
    except Exception as exc:
        logger.exception("Simulation %s failed", task_id)
        store.set_failure(task_id, str(exc))


def start_simulation(
    infrastructure_type: str,
    stress_factor: str,
    parameters: Optional[dict] = None,
) -> dict:
    """Begin a mock simulation in a background thread. Returns the task_id."""
    task_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()
    infra_types = [infrastructure_type]
    if parameters and "infrastructure_types" in parameters:
        infra_types = parameters["infrastructure_types"]

    store.create_task(task_id, {
        "created_at": now,
        "infrastructure_type": infrastructure_type,
        "stress_factor": stress_factor,
        "parameters": parameters,
    })

    thread = threading.Thread(
        target=_run_in_background,
        args=(task_id, now, infra_types, stress_factor),
        daemon=True,
    )
    thread.start()

    return {"task_id": task_id}


def get_simulation_state(task_id: str) -> dict:
    """Return ``{"state": "PENDING"|"STARTED"|...|"UNKNOWN"}``."""
    state = store.get_state(task_id)
    return {"state": state}


def get_simulation_result(task_id: str) -> Optional[dict]:
    """Return the full result dict if state is SUCCESS, otherwise None."""
    state = store.get_state(task_id)
    if state != "SUCCESS":
        return None
    return store.get_result(task_id)


# ---------------------------------------------------------------------------
# Infrastructure status generator (per-type metrics derived from raster data)
# ---------------------------------------------------------------------------

_TOTAL_ASSETS: dict[str, int] = {
    "power": 14204, "water": 8400, "roads": 3200,
    "solid_waste": 156, "sidewalks": 2840, "lrt": 24,
    "sgr": 48, "airports": 186,
}

_REGIONS: dict[str, str] = {
    "power": "Central District", "water": "Nairobi Water Zone A",
    "roads": "Greater Nairobi Road Net", "solid_waste": "Citywide Collection Network",
    "sidewalks": "CBD Pedestrian Zone", "lrt": "LRT Lines 1 & 2",
    "sgr": "Nairobi-Mombasa Corridor", "airports": "JKIA Operations",
}

_LOAD_TEMPLATES: dict[str, str] = {
    "power": "{val:.1f} GW",
    "water": "{val:.1f} ML/day",
    "roads": "{val:,} veh/hr",
    "solid_waste": "{val:.0f} tons/day",
    "sidewalks": "{val:,} ped/hr",
    "lrt": "{val:.0f} trains active",
    "sgr": "{val:.0f} freight / {val2:.0f} passenger",
    "airports": "{val:.0f} flights/hr",
}


def generate_infrastructure_status(
    infra_type: str,
    random_seed: Optional[int] = None,
) -> dict:
    """
    Generate InfrastructureStatus-like dict for one infrastructure type,
    driven entirely by population-density raster data (WorldPop).  Every call
    re-samples the raster so metrics reflect the underlying geography.
    """
    rng = np.random.RandomState(random_seed)
    total = _TOTAL_ASSETS.get(infra_type, 1000)
    region = _REGIONS.get(infra_type, "Nairobi Metropolitan Region")

    density_points = sample_high_density_points(
        max_points=min(100, total // 10 + 10),
        random_seed=random_seed or hash(infra_type) % 4294967295,
    )

    stressed_count = int(len(density_points) * rng.uniform(0.3, 0.8))
    avg_stress = round(rng.uniform(25.0, 45.0), 1)

    stressed_ratio = stressed_count / total
    grid_stability = round(100.0 * (1.0 - stressed_ratio * rng.uniform(0.6, 1.4)), 1)
    grid_stability = max(50.0, min(99.9, grid_stability))

    capacity_pct = round(40.0 + stressed_ratio * 100 * rng.uniform(0.4, 0.9), 1)
    capacity_pct = max(25.0, min(95.0, capacity_pct))

    load_base = total * max(0.05, stressed_ratio) * rng.uniform(0.5, 1.2)

    if infra_type == "power":
        current_load = _LOAD_TEMPLATES["power"].format(val=max(0.5, round(load_base / 3000, 1)))
    elif infra_type == "water":
        current_load = _LOAD_TEMPLATES["water"].format(val=max(0.5, round(load_base / 200, 1)))
    elif infra_type == "roads":
        current_load = _LOAD_TEMPLATES["roads"].format(val=int(max(100, load_base)))
    elif infra_type == "solid_waste":
        current_load = _LOAD_TEMPLATES["solid_waste"].format(val=max(10, float(load_base)))
    elif infra_type == "sidewalks":
        current_load = _LOAD_TEMPLATES["sidewalks"].format(val=int(max(100, load_base)))
    elif infra_type == "sgr":
        v1 = max(1, int(load_base // 2))
        v2 = max(1, int(load_base // 4))
        current_load = _LOAD_TEMPLATES["sgr"].format(val=v1, val2=v2)
    elif infra_type == "lrt":
        current_load = _LOAD_TEMPLATES["lrt"].format(val=max(1, load_base / 500))
    else:
        current_load = _LOAD_TEMPLATES["airports"].format(val=max(1, load_base / 50))

    latency_ms = int(rng.uniform(3, 28))
    redundancy_active = avg_stress < 70.0

    return {
        "grid_stability": grid_stability,
        "current_load": current_load,
        "active_nodes": total,
        "latency_ms": latency_ms,
        "region": region,
        "capacity_percent": capacity_pct,
        "redundancy_active": redundancy_active,
    }


# ---------------------------------------------------------------------------
# Alert list (standalone, non-simulation)
# ---------------------------------------------------------------------------

def generate_alerts(count: int = 8, random_seed: Optional[int] = None) -> list[dict]:
    """Generate a list of AlertV1-compatible dicts from raster density points."""
    rng = np.random.RandomState(random_seed)
    features = generate_stress_points(
        infrastructure_types=["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"],
        random_seed=random_seed,
    )
    alerts = []
    for i, f in enumerate(features[:count]):
        p = f["properties"]
        coords = f["geometry"]["coordinates"]
        alerts.append({
            "id": f"ALT-AL{i + 1:03d}",
            "timestamp": p["timestamp"],
            "level": p["severity"],
            "category": p["infrastructure_type"],
            "infrastructure_type": p["infrastructure_type"],
            "ward": p["ward"],
            "title": (
                f"{p['infrastructure_type'].title()} Stress at {p['ward']} "
                f"({p['stress']:.0f}/100)"
            ),
            "description": (
                f"Asset {p['asset_id']} ({p['infrastructure_type']}) in {p['ward']} "
                f"showing stress {p['stress']:.0f}/100. "
                f"Classification: {p['classification']}. "
                f"Population density: {p['density']:.0f} people/km²."
            ),
            "location": p["ward"],
            "lat": round(coords[1], 6),
            "lng": round(coords[0], 6),
            "severity_score": round(p["stress"] / 100, 4),
            "classification": p["classification"],
            "confidence": p["confidence"],
            "data_sources_used": p["data_sources_used"],
            "missing_data_warning": p["missing_data_warning"],
        })
    return alerts
