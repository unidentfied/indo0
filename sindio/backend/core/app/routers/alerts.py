from typing import Optional

from fastapi import APIRouter, Query, Depends
from ..dependencies.auth import get_current_user

from app.services.monitor import get_all_configs, get_config
from app.database import get_engine
from sqlalchemy import text

router = APIRouter()


@router.get("/dashboard", dependencies=[Depends(get_current_user)])
def get_alerts(
    infra_type: Optional[str] = Query(None, description="Filter by infrastructure type"),
    limit: int = Query(10, ge=1, le=100),
):
    engine = get_engine()
    query = """
        SELECT id, created_at as timestamp, category, infrastructure_type, asset_id,
               severity, recommended_action, location
        FROM alerts
    """
    params = {}
    if infra_type:
        query += " WHERE infrastructure_type = :infra"
        params["infra"] = infra_type
        
    query += " ORDER BY severity DESC, created_at DESC LIMIT :limit"
    params["limit"] = limit

    alerts = []
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), params)
            for row in result:
                level = "critical" if row.severity >= 0.8 else "warning" if row.severity >= 0.5 else "advisory"
                alerts.append({
                    "id": f"ALT-{row.id}",
                    "timestamp": row.timestamp.isoformat() if row.timestamp else "",
                    "level": level,
                    "category": row.infrastructure_type or row.category,
                    "title": f"{row.category}: Stress detected on {row.asset_id}",
                    "description": row.recommended_action or f"Severity: {row.severity}",
                    "location": row.location or "",
                    "confidence": 1.0,
                    "data_sources_used": ["database"],
                })
    except Exception as e:
        # Fallback if DB is empty or table doesn't exist yet
        return [
            {"id": "ALT-ERR", "timestamp": "", "level": "advisory", "category": "system",
             "title": "Database connection or query failed", "description": str(e),
             "location": "", "confidence": 1.0, "data_sources_used": []},
        ]

    if not alerts:
        return [
            {"id": "ALT-001", "timestamp": "", "level": "advisory", "category": "system",
             "title": "No active alerts", "description": "All systems operating within normal parameters.",
             "location": "", "confidence": 1.0, "data_sources_used": []},
        ]

    return alerts
