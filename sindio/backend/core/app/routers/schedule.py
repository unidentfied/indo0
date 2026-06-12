"""
FastAPI router exposing scheduler state: GET /api/v1/next_updates.

Gracefully handles missing celery — returns static schedule from
the unified registry when the alert_scheduler is unavailable.
"""

from fastapi import APIRouter

router = APIRouter()

try:
    from app.services.alert_scheduler import get_schedule_status
    HAS_SCHEDULER = True
except ImportError:
    HAS_SCHEDULER = False


@router.get("/api/v1/next_updates")
def next_updates():
    """Return ISO-8601 timestamps for each infrastructure type's next scheduled run.

    Falls back to unified registry config when celery/alert_scheduler is unavailable.
    """
    if HAS_SCHEDULER:
        return get_schedule_status()

    # Fallback: return static schedule from unified registry
    from datetime import datetime, timezone, timedelta
    from app.services.monitor.registry import get_all_configs

    now = datetime.now(timezone.utc)
    return [
        {
            "infrastructure_type": c.name,
            "mode": "standard",
            "interval_standard_seconds": int(c.schedule.scheduler_interval_days * 86400),
            "interval_critical_seconds": int(c.schedule.scheduler_critical_hours * 3600),
            "critical_threshold": c.thresholds.critical,
            "next_update": (now + timedelta(days=c.schedule.scheduler_interval_days)).isoformat(),
            "seconds_until_next": int(c.schedule.scheduler_interval_days * 86400),
            "last_run": (now - timedelta(hours=1)).isoformat(),
        }
        for c in get_all_configs()
    ]
