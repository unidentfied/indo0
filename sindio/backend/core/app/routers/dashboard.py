from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from app.auth import optional_auth

from app.services.monitor import InfrastructureMonitor, get_all_configs, get_config

router = APIRouter()


def _metric(value, delta_str, status="good", source="monitor"):
    return {
        "value": value,
        "delta": delta_str,
        "status": status,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "data_source": source,
    }


@router.get("/dashboard/metrics", dependencies=[Depends(optional_auth)])
async def dashboard_metrics(system: str = Query("power")):
    system = system.lower().replace(" ", "_").replace("-", "_")
    try:
        config = get_config(system)
    except KeyError:
        config = get_config("power")

    monitor = InfrastructureMonitor(system)
    result = monitor.run(force_mock=False)
    assets = result.assets

    avg_stress = sum(a.stress for a in assets) / max(len(assets), 1)
    stressed_count = sum(1 for a in assets if a.stress >= config.thresholds.warning)
    critical_count = sum(1 for a in assets if a.stress >= config.thresholds.critical)

    # Determine data source quality label
    source_label = "real" if any(not a.is_mock for a in assets) else "heuristic"

    return [
        _metric("Nominal" if avg_stress < 0.5 else "Degraded", "stable", "good" if avg_stress < 0.5 else "warning", source_label),
        _metric(f"{round(avg_stress * 100, 1)}%", f"{round(avg_stress * 100 - 50, 1)}% from baseline", "good" if avg_stress < 0.6 else "warning", source_label),
        _metric(f"{config.default_asset_count:,}", "stationary", "good", source_label),
        _metric(str(stressed_count), f"+{critical_count} critical", "good" if stressed_count < config.default_asset_count * 0.1 else "warning", source_label),
    ]


@router.get("/dashboard/alerts", dependencies=[Depends(optional_auth)])
async def dashboard_alerts(limit: int = Query(10, ge=1, le=50)):
    configs = get_all_configs()
    all_alerts = []
    for cfg in configs:
        monitor = InfrastructureMonitor(cfg.name)
        result = monitor.run(force_mock=False)
        for asset in result.assets:
            if asset.stress >= cfg.thresholds.warning:
                level = "critical" if asset.stress >= cfg.thresholds.breach else "warning" if asset.stress >= cfg.thresholds.critical else "advisory"
                all_alerts.append({
                    "id": f"ALT-{asset.asset_id}",
                    "timestamp": result.timestamp,
                    "level": level,
                    "category": cfg.name,
                    "title": f"{cfg.display_name}: {asset.failure_mode or 'stress anomaly'} at {asset.ward}",
                    "description": asset.recommendation or f"Stress level: {asset.stress:.1%}",
                    "location": asset.ward,
                    "confidence": asset.confidence,
                    "data_sources_used": [asset.data_source] if asset.data_source else ["monitor_fallback"],
                })

    all_alerts.sort(key=lambda a: (a["level"] != "critical", a["confidence"]), reverse=False)
    return all_alerts[:limit]
