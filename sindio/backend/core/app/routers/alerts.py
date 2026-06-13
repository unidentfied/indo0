from typing import Optional

from fastapi import APIRouter, Query

from app.services.monitor import InfrastructureMonitor, get_all_configs, get_config

router = APIRouter()


@router.get("/dashboard")
def get_alerts(
    infra_type: Optional[str] = Query(None, description="Filter by infrastructure type"),
    limit: int = Query(10, ge=1, le=100),
):
    configs = [get_config(infra_type)] if infra_type else get_all_configs()
    alerts = []
    for cfg in configs:
        monitor = InfrastructureMonitor(cfg.name)
        result = monitor.run(force_mock=False)
        for asset in result.assets[: max(2, limit // len(configs))]:
            level = "critical" if asset.stress >= 0.8 else "warning" if asset.stress >= 0.5 else "advisory"
            alerts.append({
                "id": f"ALT-{asset.asset_id}",
                "timestamp": result.timestamp,
                "level": level,
                "category": cfg.name,
                "title": f"{cfg.display_name}: {asset.failure_mode or 'stress detected'} on {asset.asset_id}",
                "description": asset.recommendation or f"Stress: {asset.stress:.1%} at {asset.ward}",
                "location": asset.ward,
                "confidence": asset.confidence,
                "data_sources_used": [asset.data_source] if asset.data_source else ["simulation"],
            })

    if not alerts:
        return [
            {"id": "ALT-001", "timestamp": "", "level": "advisory", "category": "system",
             "title": "No active alerts", "description": "All systems operating within normal parameters.",
             "location": "", "confidence": 1.0, "data_sources_used": []},
        ]

    alerts.sort(key=lambda a: a["level"] == "critical", reverse=True)
    return alerts[:limit]
