"""
Sindio — Unified Infrastructure Config Registry
================================================

Single source of truth for ALL infrastructure type settings.
Previously scattered across alert_generator.py, alert_scheduler.py,
simulation_engine.py, mock_simulation.py, and api.py.

Infrastructure type is just a config key — the same parameterized
InfrastructureMonitor class handles all types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os
from typing import Any, Callable, Dict, List, Optional, Tuple


class PhysicsEngine(str, Enum):
    POWER = "power"
    WATER = "water"
    ROAD = "road"
    HEURISTIC = "heuristic"


@dataclass
class InfraThresholds:
    """Stress thresholds for one infrastructure type."""
    warning: float = 0.60
    critical: float = 0.80
    breach: float = 0.90
    # Type-specific metric that indicates failure
    failure_metric: str = "stress"        # e.g. "pressure_m", "voltage_pu", "density"
    failure_condition: str = "above"      # "above" or "below"
    failure_value: float = 0.85           # threshold for failure_metric


@dataclass
class InfraSchedule:
    """Monitoring schedule for one infrastructure type.

    NOTE: These are real-time polling intervals for the unified monitor.
    They differ from alert_scheduler.py's Celery Beat intervals which
    control how often stress-test simulations are triggered (days/weeks).
    The monitor polls continuously; the scheduler runs periodic deep scans.
    Both systems can coexist — the monitor provides live dashboards,
    the scheduler generates periodic alerts and classifications.
    """
    poll_interval_sec: int = 300          # real-time monitor polling (5 min default)
    critical_poll_interval_sec: int = 60  # polling when critical (1 min)
    scheduler_interval_days: float = 7.0  # matches alert_scheduler.py standard interval
    scheduler_critical_hours: float = 1.0 # matches alert_scheduler.py critical interval
    temporal_spacing_days: float = 7.0    # for alert dedup
    classification_window_days: int = 180  # for long-window classifier


@dataclass
class InfraActions:
    """Recommended actions per severity tier."""
    low: str = "Monitor and log."
    medium: str = "Investigate and prepare mitigation."
    high: str = "Immediate intervention required."


@dataclass
class InfraDataSource:
    """Real-time data source configuration."""
    source_name: str
    query: str = ""                       # SQL query or Kafka topic
    fallback_query: str = ""              # fallback when primary unreachable
    data_type: str = "telemetry"          # telemetry | status | metrics | spatial
    freshness_threshold_sec: int = 300    # data older than this is stale


@dataclass
class InfraConfig:
    """Complete configuration for one infrastructure type.

    This is the ONLY place you need to change to add, remove, or modify
    an infrastructure type. The InfrastructureMonitor class reads from
    this config and behaves identically for all types.
    """
    name: str                             # "power", "water", "roads", etc.
    display_name: str                     # "Power Grid", "Water Network", etc.
    unit: str                             # "MW", "m³/day", "veh/hr", etc.
    physics_engine: PhysicsEngine         # which physics sim to use
    thresholds: InfraThresholds
    schedule: InfraSchedule
    actions: InfraActions
    data_sources: List[InfraDataSource]
    # Heuristic parameters (used when physics_engine == HEURISTIC)
    heuristic_base_stress: float = 0.50
    heuristic_variance: float = 0.15
    # Report integration
    report_source: str = ""               # official report URL or identifier
    report_frequency: str = "monthly"     # daily | weekly | monthly | quarterly
    # Asset defaults for simulation
    default_asset_count: int = 100
    default_capacity: float = 100.0


# ── Unified registry ───────────────────────────────────────────────

INFRA_REGISTRY: Dict[str, InfraConfig] = {}


def _register(cfg: InfraConfig) -> InfraConfig:
    """Register an infrastructure config and return it."""
    INFRA_REGISTRY[cfg.name] = cfg
    return cfg


# ── Power Grid ─────────────────────────────────────────────────────

POWER = _register(InfraConfig(
    name="power",
    display_name="Power Grid",
    unit="MW",
    physics_engine=PhysicsEngine.POWER,
    thresholds=InfraThresholds(
        warning=0.60, critical=0.80, breach=0.90,
        failure_metric="voltage_pu", failure_condition="below", failure_value=0.92,
    ),
    schedule=InfraSchedule(
        poll_interval_sec=120, critical_poll_interval_sec=30,
        scheduler_interval_days=1.0, scheduler_critical_hours=0.5,
        temporal_spacing_days=1.0, classification_window_days=210,
    ),
    actions=InfraActions(
        low="Monitor load distribution across substations.",
        medium="Reroute load to auxiliary substations within 2 hours.",
        high="Shed overloaded buses immediately. Activate emergency generators.",
    ),
    data_sources=[
        InfraDataSource(
            source_name="SCADA power meters",
            query="SELECT bus_id, voltage_pu, load_mw FROM power_scada WHERE updated_at > NOW() - INTERVAL '5 minutes'",
            fallback_query="SELECT bus_id, voltage_pu, load_mw FROM power_scada WHERE updated_at > NOW() - INTERVAL '1 hour'",
            data_type="telemetry", freshness_threshold_sec=300,
        ),
        InfraDataSource(
            source_name="Kenya Power API",
            query=os.environ.get("KENYA_POWER_API_URL", ""),
            fallback_query=os.environ.get("KENYA_POWER_FALLBACK_URL", ""),
            data_type="telemetry", freshness_threshold_sec=900,
        ),
    ],
    report_source="Kenya Power Annual Report",
    report_frequency="monthly",
    default_asset_count=14204,
    default_capacity=4200.0,
))

# ── Water Network ──────────────────────────────────────────────────

WATER = _register(InfraConfig(
    name="water",
    display_name="Water Network",
    unit="m³/day",
    physics_engine=PhysicsEngine.WATER,
    thresholds=InfraThresholds(
        warning=0.55, critical=0.75, breach=0.85,
        failure_metric="pressure_m", failure_condition="below", failure_value=10.0,
    ),
    schedule=InfraSchedule(
        poll_interval_sec=600, critical_poll_interval_sec=120,
        scheduler_interval_days=7.0, scheduler_critical_hours=1.0,
        temporal_spacing_days=7.0, classification_window_days=180,
    ),
    actions=InfraActions(
        low="Monitor pressure trends across distribution zones.",
        medium="Activate booster pumps. Check for pipe leaks.",
        high="Emergency water rationing. Deploy mobile water units.",
    ),
    data_sources=[
        InfraDataSource(
            source_name="Water SCADA sensors",
            query="SELECT node_id, pressure_m, flow_lps FROM water_scada WHERE updated_at > NOW() - INTERVAL '5 minutes'",
            fallback_query="SELECT node_id, pressure_m, flow_lps FROM water_scada WHERE updated_at > NOW() - INTERVAL '1 hour'",
            data_type="telemetry", freshness_threshold_sec=300,
        ),
        InfraDataSource(
            source_name="Nairobi Water API",
            query=os.environ.get("NAIROBI_WATER_API_URL", ""),
            fallback_query=os.environ.get("NAIROBI_WATER_FALLBACK_URL", ""),
            data_type="telemetry", freshness_threshold_sec=900,
        ),
    ],
    report_source="Nairobi Water & Sewerage Company Report",
    report_frequency="monthly",
    default_asset_count=8400,
    default_capacity=82400.0,
))

# ── Roads ──────────────────────────────────────────────────────────

ROADS = _register(InfraConfig(
    name="roads",
    display_name="Road Network",
    unit="veh/hr",
    physics_engine=PhysicsEngine.ROAD,
    thresholds=InfraThresholds(
        warning=0.50, critical=0.70, breach=0.85,
        failure_metric="density_veh_km", failure_condition="above", failure_value=127.5,
    ),
    schedule=InfraSchedule(
        poll_interval_sec=60, critical_poll_interval_sec=15,
        scheduler_interval_days=30.0, scheduler_critical_hours=6.0,
        temporal_spacing_days=30.0, classification_window_days=270,
    ),
    actions=InfraActions(
        low="Monitor traffic flow patterns.",
        medium="Re-route congested cells. Adjust signal timing.",
        high="Deploy traffic officers. Activate emergency lanes.",
    ),
    data_sources=[
        InfraDataSource(
            source_name="Traffic sensors (H3 aggregated)",
            query="SELECT h3_index, vehicle_count FROM mobility_aggregates WHERE time > NOW() - INTERVAL '5 minutes'",
            fallback_query="SELECT h3_index, vehicle_count FROM mobility_aggregates WHERE time > NOW() - INTERVAL '1 hour'",
            data_type="telemetry", freshness_threshold_sec=300,
        ),
        InfraDataSource(
            source_name="GPS Probe / Traffic API",
            query=os.environ.get("TRAFFIC_PROBE_API_URL", ""),
            fallback_query=os.environ.get("TRAFFIC_PROBE_FALLBACK_URL", ""),
            data_type="telemetry", freshness_threshold_sec=120,
        ),
    ],
    report_source="Kenya National Highway Authority Report",
    report_frequency="quarterly",
    default_asset_count=3200,
    default_capacity=12400.0,
))

# ── Solid Waste ────────────────────────────────────────────────────

SOLID_WASTE = _register(InfraConfig(
    name="solid_waste",
    display_name="Solid Waste Collection",
    unit="tons/day",
    physics_engine=PhysicsEngine.HEURISTIC,
    thresholds=InfraThresholds(
        warning=0.60, critical=0.85, breach=0.95,
    ),
    schedule=InfraSchedule(
        poll_interval_sec=300, critical_poll_interval_sec=60,
        scheduler_interval_days=14.0, scheduler_critical_hours=24.0,
        temporal_spacing_days=14.0, classification_window_days=365,
    ),
    actions=InfraActions(
        low="Monitor collection schedule adherence.",
        medium="Add supplementary collection shift.",
        high="Emergency waste disposal. Deploy temporary collection points.",
    ),
    data_sources=[
        InfraDataSource(
            source_name="Waste collection IoT sensors",
            query="SELECT station_id, fill_level FROM waste_sensors WHERE updated_at > NOW() - INTERVAL '15 minutes'",
            data_type="telemetry", freshness_threshold_sec=900,
        ),
    ],
    report_source="Nairobi County Waste Management Report",
    report_frequency="monthly",
    default_asset_count=156,
    default_capacity=820.0,
    heuristic_base_stress=0.35,
    heuristic_variance=0.10,
))

# ── Sidewalks ──────────────────────────────────────────────────────

SIDEWALKS = _register(InfraConfig(
    name="sidewalks",
    display_name="Pedestrian Infrastructure",
    unit="ped/hr",
    physics_engine=PhysicsEngine.HEURISTIC,
    thresholds=InfraThresholds(
        warning=0.55, critical=0.80, breach=0.90,
    ),
    actions=InfraActions(
        low="Monitor pedestrian flow sensors.",
        medium="Schedule pavement inspection within 7 days.",
        high="Close degraded sections. Deploy temporary walkways.",
    ),
    data_sources=[
        InfraDataSource(
            source_name="Pedestrian counters",
            query="SELECT path_id, pedestrian_count FROM sidewalk_counters WHERE updated_at > NOW() - INTERVAL '30 minutes'",
            data_type="telemetry", freshness_threshold_sec=1800,
        ),
    ],
    report_source="Nairobi Urban Design Report",
    report_frequency="quarterly",
    default_asset_count=2840,
    default_capacity=4200.0,
    heuristic_base_stress=0.25,
    heuristic_variance=0.08,
    schedule=InfraSchedule(
        poll_interval_sec=600, critical_poll_interval_sec=120,
        scheduler_interval_days=7.0, scheduler_critical_hours=2.0,
        temporal_spacing_days=7.0, classification_window_days=180,
    ),
))

# ── LRT (Light Rail Transit) ───────────────────────────────────────

LRT = _register(InfraConfig(
    name="lrt",
    display_name="Light Rail Transit",
    unit="trains active",
    physics_engine=PhysicsEngine.HEURISTIC,
    thresholds=InfraThresholds(
        warning=0.55, critical=0.75, breach=0.85,
    ),
    schedule=InfraSchedule(
        poll_interval_sec=90, critical_poll_interval_sec=15,
        scheduler_interval_days=1.0, scheduler_critical_hours=0.25,
        temporal_spacing_days=1.0, classification_window_days=150,
    ),
    actions=InfraActions(
        low="Monitor train frequency sensors.",
        medium="Adjust headway spacing on affected segment.",
        high="Suspend service on affected segment. Deploy bus bridging.",
    ),
    data_sources=[
        InfraDataSource(
            source_name="LRT signaling system",
            query="SELECT segment_id, train_count, headway_sec FROM lrt_telemetry WHERE updated_at > NOW() - INTERVAL '2 minutes'",
            data_type="telemetry", freshness_threshold_sec=120,
        ),
    ],
    report_source="Nairobi Rail Authority Report",
    report_frequency="monthly",
    default_asset_count=24,
    default_capacity=18.0,
    heuristic_base_stress=0.30,
    heuristic_variance=0.12,
))

# ── SGR (Standard Gauge Railway) ──────────────────────────────────

SGR = _register(InfraConfig(
    name="sgr",
    display_name="Standard Gauge Railway",
    unit="trains",
    physics_engine=PhysicsEngine.HEURISTIC,
    thresholds=InfraThresholds(
        warning=0.50, critical=0.70, breach=0.80,
    ),
    schedule=InfraSchedule(
        poll_interval_sec=180, critical_poll_interval_sec=30,
        scheduler_interval_days=1.0, scheduler_critical_hours=0.5,
        temporal_spacing_days=1.0, classification_window_days=150,
    ),
    actions=InfraActions(
        low="Monitor track stress telemetry.",
        medium="Reduce speed limit on affected segment by 20%.",
        high="Suspend service. Deploy track inspection teams.",
    ),
    data_sources=[
        InfraDataSource(
            source_name="SGR track sensors",
            query="SELECT segment_id, stress_level, speed_limit FROM sgr_telemetry WHERE updated_at > NOW() - INTERVAL '5 minutes'",
            data_type="telemetry", freshness_threshold_sec=300,
        ),
    ],
    report_source="Kenya Railways Corporation Report",
    report_frequency="quarterly",
    default_asset_count=48,
    default_capacity=18.0,
    heuristic_base_stress=0.20,
    heuristic_variance=0.08,
))

# ── Airports ───────────────────────────────────────────────────────

AIRPORTS = _register(InfraConfig(
    name="airports",
    display_name="Airport Operations",
    unit="flights/hr",
    physics_engine=PhysicsEngine.HEURISTIC,
    thresholds=InfraThresholds(
        warning=0.50, critical=0.65, breach=0.80,
    ),
    actions=InfraActions(
        low="Monitor runway surface sensors.",
        medium="Schedule runway friction test.",
        high="Divert flights. Activate alternate runway.",
    ),
    data_sources=[
        InfraDataSource(
            source_name="Airport operations system",
            query="SELECT runway_id, flight_rate, surface_condition FROM airport_telemetry WHERE updated_at > NOW() - INTERVAL '10 minutes'",
            data_type="telemetry", freshness_threshold_sec=600,
        ),
    ],
    report_source="Kenya Airports Authority Report",
    report_frequency="monthly",
    default_asset_count=186,
    default_capacity=42.0,
    heuristic_base_stress=0.15,
    heuristic_variance=0.05,
    schedule=InfraSchedule(
        poll_interval_sec=600, critical_poll_interval_sec=120,
        scheduler_interval_days=0.5, scheduler_critical_hours=0.25,
        temporal_spacing_days=0.5, classification_window_days=210,
    ),
))


# ── Convenience helpers ────────────────────────────────────────────

def get_config(name: str) -> InfraConfig:
    """Get config by name. Raises KeyError if not found."""
    return INFRA_REGISTRY[name]


def get_all_configs() -> List[InfraConfig]:
    """Return all registered configs."""
    return list(INFRA_REGISTRY.values())


def get_names() -> List[str]:
    """Return all registered infrastructure type names."""
    return list(INFRA_REGISTRY.keys())


def get_by_physics_engine(engine: PhysicsEngine) -> List[InfraConfig]:
    """Return all configs using a specific physics engine."""
    return [c for c in INFRA_REGISTRY.values() if c.physics_engine == engine]
