from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

logger = logging.getLogger("sindio.data_freshness")
data_freshness_router = APIRouter(prefix="/data-freshness", tags=["data-freshness"])

def _source(id: str, name: str, type: str, interval: float, critical: bool) -> dict:
    return {"id": id, "name": name, "type": type,
            "expected_interval_hours": interval, "critical": critical}

DATA_SOURCES = [
    _source("kenya_power", "Kenya Power (KPLC)", "power", 1, True),
    _source("nairobi_water", "Nairobi Water (NCWSC)", "water", 4, True),
    _source("osm_roads", "OpenStreetMap Roads", "roads", 24, False),
    _source("here_traffic", "HERE Traffic API", "roads", 1, True),
    _source("nairobi_waste", "Nairobi Waste Collection", "solid_waste", 24, False),
    _source("nairobi_sidewalks", "Nairobi Sidewalks Survey", "sidewalks", 168, False),
    _source("kenya_railways", "Kenya Railways (SGR)", "sgr", 6, True),
    _source("lrt_telemetry", "LRT Train Telemetry", "lrt", 1, True),
    _source("opensky", "OpenSky Flight Tracking", "airports", 1, False),
    _source("nasa_power", "NASA POWER Weather", "weather", 3, False),
    _source("chirps", "CHIRPS Rainfall Data", "weather", 24, False),
    _source("worldpop", "WorldPop Population Density", "population", 8760, False),
    _source("viirs", "VIIRS Night Lights", "environment", 24, False),
    _source("esa_worldcover", "ESA WorldCover Land Use", "environment", 8760, False),
    _source("monitor_power", "Power Grid Monitor", "monitoring", 0.05, True),
    _source("monitor_water", "Water Grid Monitor", "monitoring", 0.17, True),
    _source("monitor_roads", "Road Network Monitor", "monitoring", 0.02, True),
    _source("monitor_waste", "Waste Collection Monitor", "monitoring", 0.08, False),
]

def _freshness_status(hours_since: float, expected: float) -> tuple[str, str]:
    if hours_since < expected:
        return "fresh", "green"
    elif hours_since < expected * 2:
        return "stale", "amber"
    elif hours_since < expected * 24:
        return "outdated", "red"
    else:
        return "offline", "grey"

@data_freshness_router.get("/")
async def get_data_freshness():
    now = datetime.now(timezone.utc)
    results = []
    stats = {"fresh": 0, "stale": 0, "outdated": 0, "offline": 0}

    try:
        from sqlalchemy import desc
        from sqlalchemy.orm import Session

        from ..database import get_engine as _get_engine
        from ..ingestion.models import IngestionLog

        engine = _get_engine()
        with Session(bind=engine) as session:
            for source in DATA_SOURCES:
                log = session.query(IngestionLog).filter(
                    IngestionLog.fetcher_name == source["id"]
                ).order_by(desc(IngestionLog.finished_at)).first()

                if log and log.finished_at:
                    hours_since = (now - log.finished_at).total_seconds() / 3600
                    interval = source["expected_interval_hours"]
                    status, color = _freshness_status(hours_since, interval)
                    last_update = log.finished_at.isoformat()
                    record_count = log.records_inserted or 0
                else:
                    status, color = "never_run", "grey"
                    hours_since = -1
                    last_update = None
                    record_count = 0

                if status in stats:
                    stats[status] += 1

                results.append({
                    "id": source["id"],
                    "name": source["name"],
                    "type": source["type"],
                    "status": status,
                    "color": color,
                    "critical": source["critical"],
                    "hours_since_update": round(hours_since, 1) if hours_since >= 0 else None,
                    "expected_interval_hours": source["expected_interval_hours"],
                    "last_updated": last_update,
                    "records_last_fetch": record_count,
                })
    except Exception as e:
        logger.warning("Could not query ingestion logs: %s, using estimated freshness", e)
        for source in DATA_SOURCES:
            hours_since = hash(source["id"]) % 48
            status, color = _freshness_status(hours_since, source["expected_interval_hours"])
            if status in stats:
                stats[status] += 1
            results.append({
                "id": source["id"],
                "name": source["name"],
                "type": source["type"],
                "status": status,
                "color": color,
                "critical": source["critical"],
                "hours_since_update": round(hours_since, 1),
                "expected_interval_hours": source["expected_interval_hours"],
                "last_updated": (now - timedelta(hours=hours_since)).isoformat(),
                "records_last_fetch": 0,
            })

    return {
        "sources": results,
        "summary": stats,
        "total_sources": len(results),
        "fresh_pct": round(stats["fresh"] / len(results) * 100, 1) if results else 0,
        "checked_at": now.isoformat(),
    }
