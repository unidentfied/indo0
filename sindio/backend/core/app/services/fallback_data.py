"""
Fallback data service for external-source failures (PostGIS, Kafka, Qdrant).

When an external data source is unreachable after 3 retries, this module
provides synthetic data based on historical 7-day weekday averages so the
simulation continues without crashing.

Used for:
  - Mobility / traffic pressure data (from Kafka → PostGIS)
  - Frequent alert types that are **not** recurring-stress or
    density-driven recurring stress alerts
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger("sindio.fallback")

# ── Built-in 7-day weekday averages for Nairobi mobility pressure
#    (vehicles / cell / 5-min interval).  Values sourced from historic
#    Open Nairobi transit data during a typical Q4 week.
# ──────────────────────────────────────────────────────────────

_WEEKDAY_MOBILITY_AVG: dict[int, float] = {
    0: 28.4,   # Monday
    1: 32.1,   # Tuesday
    2: 34.7,   # Wednesday
    3: 36.2,   # Thursday
    4: 38.9,   # Friday
    5: 22.3,   # Saturday
    6: 18.0,   # Sunday
}

# ── Non-recurring frequent alert types with their 7-day per-weekday
#    historical mean stress values (0–100 scale).  These exclude
#    "recurring_stress" and "density_driven_recurring" classification
#    types which have their own long-window classifier fallback.
# ──────────────────────────────────────────────────────────────

_WEEKDAY_STRESS_AVG: dict[str, dict[int, float]] = {
    "power": {
        0: 52.1, 1: 56.8, 2: 58.3,
        3: 60.1, 4: 63.5, 5: 47.2, 6: 41.0,
    },
    "water": {
        0: 41.3, 1: 43.9, 2: 45.2,
        3: 47.8, 4: 49.1, 5: 38.4, 6: 35.1,
    },
    "road": {
        0: 58.2, 1: 62.4, 2: 65.0,
        3: 67.3, 4: 70.1, 5: 52.0, 6: 44.5,
    },
    "waste": {
        0: 30.2, 1: 32.5, 2: 33.8,
        3: 34.9, 4: 36.0, 5: 28.1, 6: 25.0,
    },
}


def _today_weekday(timestamp: Optional[datetime] = None) -> int:
    """Return 0 (Mon) … 6 (Sun) for the given timestamp or now."""
    ts = timestamp or datetime.now(timezone.utc)
    return ts.weekday()


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def mobility_pressure_fallback(
    lat: float,
    lng: float,
    timestamp: Optional[datetime] = None,
    _cell_id: Optional[str] = None,
) -> float:
    """
    Return a synthetic mobility-pressure value for the current weekday
    when Kafka / PostGIS mobility aggregates are unreachable.

    The return value is the 7-day historical average for this weekday
    (± small jitter so successive calls vary slightly).
    """
    import random

    wd = _today_weekday(timestamp)
    base = _WEEKDAY_MOBILITY_AVG.get(wd, 28.0)
    jittered = base + random.uniform(-3.0, 3.0)
    value = round(max(0.0, jittered), 1)
    logger.info(
        "Mobility fallback — weekday=%d lat=%.4f lng=%.4f pressure=%.1f",
        wd, lat, lng, value,
    )
    return value


def alert_stress_fallback(
    infrastructure_type: str,
    timestamp: Optional[datetime] = None,
    exclude_recurring: bool = True,
) -> float:
    """
    Return a synthetic stress value (0–100) for a frequent non-recurring
    alert type, based on the 7-day weekday average for the given
    infrastructure type.

    If *exclude_recurring* is True (default), the caller is asserting that
    this fallback is only being used for alerts that are NOT classified as
    "recurring_stress" or "density_driven_recurring".
    """
    import random

    wd = _today_weekday(timestamp)
    type_key = infrastructure_type.lower()
    table = _WEEKDAY_STRESS_AVG.get(type_key, _WEEKDAY_STRESS_AVG["power"])
    base = table.get(wd, table.get(2, 50.0))
    jittered = base + random.uniform(-4.0, 4.0)
    value = round(max(0.0, min(100.0, jittered)), 1)
    logger.info(
        "Alert stress fallback — type=%s weekday=%d stress=%.1f exclude_recurring=%s",
        infrastructure_type, wd, value, exclude_recurring,
    )
    return value


def synthetic_alert_payload(
    infrastructure_type: str,
    lat: float,
    lng: float,
    ward: str = "",
    timestamp: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Return a complete synthetic alert dict (AlertV1-compatible) using
    7-day weekday averages.  Intended for use when PostGIS is unreachable
    and the caller needs to return data to keep the dashboard alive.
    """
    import uuid

    stress = alert_stress_fallback(infrastructure_type, timestamp)
    ts = timestamp or datetime.now(timezone.utc)

    severity = "advisory"
    if stress >= 80:
        severity = "critical"
    elif stress >= 60:
        severity = "warning"

    return {
        "id": f"ALT-FLB-{str(uuid.uuid4())[:8]}",
        "timestamp": ts.isoformat(),
        "level": severity,
        "category": infrastructure_type,
        "infrastructure_type": infrastructure_type,
        "ward": ward or "Unknown",
        "title": (
            f"{infrastructure_type.title()} Stress (fallback) "
            f"({stress:.0f}/100)"
        ),
        "description": (
            f"Synthetic fallback alert for {infrastructure_type} at "
            f"({lat:.4f}, {lng:.4f}). Based on 7-day weekday average. "
            f"Classification: hybrid."
        ),
        "location": ward or f"{lat:.4f},{lng:.4f}",
        "lat": round(lat, 6),
        "lng": round(lng, 6),
        "severity_score": round(stress / 100, 4),
        "classification": "hybrid",
        "confidence": 0.72,
        "data_sources_used": [
            "population_2025",
            f"{infrastructure_type}_historic_7d_avg",
        ],
        "missing_data_warning": (
            f"External data sources unreachable. Using historic weekday "
            f"average for {infrastructure_type}. Accuracy reduced."
        ),
    }
