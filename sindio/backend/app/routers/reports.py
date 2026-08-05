"""Sindio — CSV / PDF Export Endpoints
=======================================
Allows users to download infrastructure reports in multiple formats.

Endpoints:
  POST /api/v1/reports/export — Export filtered data to CSV or PDF
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.rbac import require_county

logger = logging.getLogger("sindio.reports")

WARD_COORDS = {
    "Westlands": (-1.27, 36.80), "Central": (-1.28, 36.82),
    "Embakasi East": (-1.31, 36.93), "Embakasi South": (-1.33, 36.88),
    "Embakasi West": (-1.31, 36.86), "Embakasi Central": (-1.30, 36.89),
    "Embakasi North": (-1.28, 36.91), "Kasarani": (-1.23, 36.90),
    "Langata": (-1.36, 36.78), "Dagoretti North": (-1.29, 36.75),
    "Dagoretti South": (-1.32, 36.74), "Starehe": (-1.27, 36.84),
    "Mathare": (-1.26, 36.86), "Kamukunji": (-1.27, 36.85),
    "Makadara": (-1.30, 36.85), "Roysambu": (-1.22, 36.89),
    "Ruaraka": (-1.25, 36.88),
}

router = APIRouter(prefix="/api/v1/reports")


class ExportRequest(BaseModel):
    format: Literal["csv", "json", "geojson"]
    infrastructure_type: Optional[str] = None
    ward: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    limit: int = 1000


def _generate_csv(data: List[Dict[str, Any]]) -> str:
    if not data:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)
    return output.getvalue()


@router.post("/export")
async def export_data(
    request: ExportRequest,
    user: Dict = Depends(require_county),
) -> StreamingResponse:
    """Export infrastructure data in CSV or JSON format.

    Access: county, admin roles only.
    """
    # In production: query database with filters
    # For now, generate from mock data
    # Import dependencies within function scope
    from app.routers.api import _INFRA_TYPES, _WARDS
    import random

    data: List[Dict[str, Any]] = []
    types = [request.infrastructure_type] if request.infrastructure_type else [t["name"] for t in _INFRA_TYPES]

    for infra_type in types:
        for _ in range(min(request.limit // len(types), 10)):
            ward = request.ward or random.choice(_WARDS)
            data.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "infrastructure_type": infra_type,
                "ward": ward,
                "asset_id": f"{infra_type[:3].upper()}-{random.randint(1000, 9999):04d}",
                "stress_value": round(random.uniform(0.1, 0.95), 3),
                "capacity": random.randint(50, 500),
                "unit": "index",
                "status": random.choice(["normal", "warning", "critical"]),
                "source": "sindio_export",
            })

    if request.format == "csv":
        csv_data = _generate_csv(data)
        return StreamingResponse(
            io.StringIO(csv_data),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=sindio_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
            },
        )
    elif request.format == "geojson":
        import json
        features = []
        for d in data:
            ward_coords = WARD_COORDS.get(d.get("ward", "Central"), (-1.2833, 36.8219))
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [ward_coords[1], ward_coords[0]]},
                "properties": {k: v for k, v in d.items() if k != "ward"},
            })
        geojson_data = {"type": "FeatureCollection", "features": features}
        return StreamingResponse(
            io.StringIO(json.dumps(geojson_data, indent=2)),
            media_type="application/geo+json",
            headers={
                "Content-Disposition": f"attachment; filename=sindio_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.geojson"
            },
        )
    else:
        import json
        return StreamingResponse(
            io.StringIO(json.dumps(data, indent=2)),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=sindio_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
            },
        )
