"""
Sindio — Cascade Failure Analysis Router
=========================================

Endpoints for cascade failure analysis across infrastructure types.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict, Optional

from ..services.cascade_analyzer import CascadeAnalyzer
from ..services.cascade_analyzer import get_cascade_history

cascade_router = APIRouter(prefix="/cascade", tags=["cascade"])

_analyzers: Dict[str, CascadeAnalyzer] = {}


def _get_analyzer(city_slug: str) -> CascadeAnalyzer:
    if city_slug not in _analyzers:
        _analyzers[city_slug] = CascadeAnalyzer(city_slug=city_slug)
    return _analyzers[city_slug]


@cascade_router.post("/analyze")
async def analyze_cascade_post(body: Dict[str, Any]) -> Dict[str, Any]:
    """Run a cascade failure analysis.

    Accepts a JSON body with:
      - asset_type: str (power_substation, water_pump)
      - asset_id: str (e.g. ngong, kabete)
      - city_slug: str (default "nairobi")

    Returns cascade chain, affected wards, critical facilities, and summary.
    """
    asset_type = body.get("asset_type")
    asset_id = body.get("asset_id")
    city_slug = body.get("city_slug", "nairobi")

    if not asset_type or not asset_id:
        raise HTTPException(
            status_code=400,
            detail="Both 'asset_type' and 'asset_id' are required",
        )

    analyzer = _get_analyzer(city_slug)
    result = analyzer.analyze_cascade(
        asset_type=str(asset_type),
        asset_id=str(asset_id),
        city_slug=str(city_slug),
    )

    if "error" in result:
        status_code = 400 if "supported" in result["error"] or "Unsupported" in result["error"] else 404
        raise HTTPException(status_code=status_code, detail=result["error"])

    return result


@cascade_router.get("/analyze")
async def analyze_cascade_get(
    asset_type: str = Query(..., description="Asset type (power_substation, water_pump)"),
    asset_id: str = Query(..., description="Asset ID (e.g. ngong, embakasi, kabete)"),
    city_slug: str = Query("nairobi", description="City slug"),
) -> Dict[str, Any]:
    """Run cascade failure analysis via GET query parameters.

    Returns cascade chain, affected wards, critical facilities, and summary.
    """
    analyzer = _get_analyzer(city_slug)
    result = analyzer.analyze_cascade(
        asset_type=asset_type,
        asset_id=asset_id,
        city_slug=city_slug,
    )

    if "error" in result:
        status_code = 400 if "supported" in result["error"] or "Unsupported" in result["error"] else 404
        raise HTTPException(status_code=status_code, detail=result["error"])

    return result


@cascade_router.get("/assets")
async def list_assets(
    city_slug: str = Query("nairobi", description="City slug"),
) -> Dict[str, Any]:
    """List all analyzable assets by type (power substations, water pumps, etc.).

    Returns assets grouped by type, along with critical facilities and wards.
    """
    analyzer = _get_analyzer(city_slug)
    return analyzer.list_assets(city_slug=city_slug)


@cascade_router.get("/dependencies/{asset_id}")
async def get_dependencies(
    asset_id: str,
    city_slug: str = Query("nairobi", description="City slug"),
) -> Dict[str, Any]:
    """Return the dependency graph for a specific asset.

    Shows what this asset depends on and what depends on it.
    """
    analyzer = _get_analyzer(city_slug)
    result = analyzer.get_dependencies(asset_id=asset_id, city_slug=city_slug)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@cascade_router.get("/history")
async def get_analysis_history(
    city_slug: str = Query("nairobi"),
    limit: int = Query(20, ge=1, le=100),
):
    """Get past cascade analysis history."""
    return get_cascade_history(city_slug=city_slug, limit=limit)
