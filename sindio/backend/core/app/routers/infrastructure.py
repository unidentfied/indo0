from fastapi import APIRouter, HTTPException, Depends, Path

from app.services.monitor import InfrastructureMonitor, get_all_configs, get_config
from app.auth import optional_auth

router = APIRouter()


@router.get("", dependencies=[Depends(optional_auth)])
def get_all():
    return {
        "systems": [
            {
                "name": c.name,
                "display_name": c.display_name,
                "active_nodes": c.default_asset_count,
                "capacity": c.default_capacity,
                "unit": c.unit,
                "thresholds": {
                    "warning": c.thresholds.warning,
                    "critical": c.thresholds.critical,
                    "breach": c.thresholds.breach,
                },
            }
            for c in get_all_configs()
        ]
    }


@router.get("/{system}", dependencies=[Depends(optional_auth)])
def get_infrastructure(system: str = Path(..., regex="^[a-z0-9_-]+$")):
    try:
        config = get_config(system)
    except KeyError:
        valid = [c.name for c in get_all_configs()]
        raise HTTPException(
            status_code=404,
            detail={"error": f"Unknown system: {system}", "valid_systems": valid},
        )

    monitor = InfrastructureMonitor(system)
    result = monitor.run(force_mock=False)

    stressed_count = sum(1 for a in result.assets if a.stress >= config.thresholds.warning)
    critical_count = sum(1 for a in result.assets if a.stress >= config.thresholds.critical)
    avg_stress = sum(a.stress for a in result.assets) / max(len(result.assets), 1)

    return {
        "system": config.name,
        "display_name": config.display_name,
        "grid_stability": round(100 * (1 - avg_stress), 1),
        "current_load": f"{round(config.default_capacity * avg_stress, 1)} {config.unit}",
        "active_nodes": result.assets[0].current_value if result.assets else config.default_asset_count,
        "latency_ms": 12,  # TODO: replace with real latency metric
        "region": "Central District",  # TODO: move to config per system
        "capacity_percent": round(100 * (1 - avg_stress), 1),
        "stressed_nodes": stressed_count,
        "critical_nodes": critical_count,
        "redundancy_active": avg_stress < config.thresholds.breach,
    }
