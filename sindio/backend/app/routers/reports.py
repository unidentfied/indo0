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

router = APIRouter(prefix="/api/v1/reports")


class ExportRequest(BaseModel):
    format: Literal["csv", "json"]
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
    else:
        import json
        return StreamingResponse(
            io.StringIO(json.dumps(data, indent=2)),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=sindio_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
            },
        )
