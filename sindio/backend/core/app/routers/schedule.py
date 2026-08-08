"""
FastAPI router exposing scheduler state: GET /api/v1/next_updates.

Returns current schedule state for each infrastructure type, sourced
from the unified registry and (when available) the Celery-backed
alert_scheduler.

Response shape:
  {
    "updates": [
      {
        "update_type": "power",
        "display_name": "Power Grid",
        "next_at": "2026-08-08T12:00:00+00:00",
        "interval_sec": 86400,
        "critical_interval_sec": 1800,
        "description": "Power Grid monitoring — polls every 2m, deep scan every 1d",
        "mode": "standard",
        "critical_threshold": 0.8,
        "last_run": "2026-08-08T11:00:00+00:00",
        "seconds_until_next": 3600.0
      },
      ...
    ]
  }
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

router = APIRouter()

try:
    from ..services.alert_scheduler import get_schedule_status
    HAS_SCHEDULER = True
except ImportError:
    HAS_SCHEDULER = False


def _fmt_interval(seconds: float) -> str:
    """Human-readable interval string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        h = seconds / 3600
        return f"{h:.1f}h" if h != int(h) else f"{int(h)}h"
    d = seconds / 86400
    return f"{d:.0f}d" if d == int(d) else f"{d:.1f}d"


@router.get("/api/v1/next_updates")
async def next_updates():
    """Return ISO-8601 timestamps for each infrastructure type's next scheduled run.

    Merges live state from alert_scheduler (Redis/Celery) with the
    unified registry config.  Falls back to registry-only estimates
    when Celery is not available.
    """
    from ..services.monitor.registry import get_all_configs

    now = datetime.now(timezone.utc)

    # If the alert_scheduler is running, use its live Redis state
    live_state: dict[str, dict] = {}
    if HAS_SCHEDULER:
        try:
            for entry in get_schedule_status():
                live_state[entry["infrastructure_type"]] = entry
        except Exception:
            pass  # fall through to registry-only

    updates = []
    for cfg in get_all_configs():
        live = live_state.get(cfg.name, {})

        # Intervals
        standard_sec = int(cfg.schedule.scheduler_interval_days * 86400)
        critical_sec = int(cfg.schedule.scheduler_critical_hours * 3600)
        poll_sec = cfg.schedule.poll_interval_sec

        # Mode
        mode = live.get("mode", "standard")

        # Next run
        next_at_iso = live.get("next_update")
        seconds_until = live.get("seconds_until_next")
        last_run_iso = live.get("last_run")

        if not next_at_iso:
            # Estimate from registry intervals
            active_interval_sec = critical_sec if mode == "critical" else standard_sec
            next_at_dt = now + timedelta(seconds=active_interval_sec)
            next_at_iso = next_at_dt.isoformat()
            seconds_until = float(active_interval_sec)

        if not last_run_iso:
            # Estimate: last run was one interval ago
            active_interval_sec = critical_sec if mode == "critical" else standard_sec
            last_run_iso = (now - timedelta(seconds=active_interval_sec)).isoformat()

        # Active interval for display
        active_interval_sec = critical_sec if mode == "critical" else standard_sec

        # Description from registry
        poll_str = _fmt_interval(poll_sec)
        scan_str = _fmt_interval(active_interval_sec)
        description = f"{cfg.display_name} monitoring — polls every {poll_str}, deep scan every {scan_str}"

        updates.append({
            "update_type": cfg.name,
            "display_name": cfg.display_name,
            "next_at": next_at_iso,
            "interval_sec": active_interval_sec,
            "critical_interval_sec": critical_sec,
            "standard_interval_sec": standard_sec,
            "poll_interval_sec": poll_sec,
            "description": description,
            "mode": mode,
            "critical_threshold": cfg.thresholds.critical,
            "last_run": last_run_iso,
            "seconds_until_next": seconds_until,
            "region": cfg.region,
        })

    return {"updates": updates}

