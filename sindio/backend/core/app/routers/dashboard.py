from fastapi import APIRouter, Query

from app.services.monitor import InfrastructureMonitor, get_all_configs, get_config

router = APIRouter()


def _metric(value, delta_str, status="good"):
    return {"value": value, "delta": delta_str, "status": status}


@router.get("/dashboard/metrics")
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

    return [
        {"label": "System Status", "value": "Nominal" if avg_stress < 0.5 else "Degraded", "delta": "stable", "status": "good" if avg_stress < 0.5 else "warning"},
        {"label": "Avg Stress", "value": f"{round(avg_stress * 100, 1)}%", "delta": f"{round(avg_stress * 100 - 50, 1)}% from baseline", "status": "good" if avg_stress < 0.6 else "warning"},
        {"label": "Active Assets", "value": f"{config.default_asset_count:,}", "delta": "stationary", "status": "good"},
        {"label": "Stressed Assets", "value": str(stressed_count), "delta": f"+{critical_count} critical", "status": "good" if stressed_count < config.default_asset_count * 0.1 else "warning"},
    ]


@router.get("/dashboard/alerts")
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
