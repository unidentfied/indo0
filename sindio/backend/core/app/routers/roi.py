from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.roi_calculator import calculate_roi, list_upgrade_options
from ..services.roi_calculator import get_roi_history

roi_router = APIRouter()


class RoiCalculateRequest(BaseModel):
    infra_type: str = "power"
    asset_id: str = "asset-001"
    upgrade_cost_kes: float = 36250000
    upgrade_description: str = ""
    asset_lifespan_years: int = 20


@roi_router.post("/roi/calculate")
async def api_calculate_roi(body: RoiCalculateRequest):
    params = body.model_dump()
    if not params["upgrade_description"]:
        params["upgrade_description"] = f"{params['infra_type']} infrastructure upgrade — {params['asset_id']}"
    try:
        result = calculate_roi(params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@roi_router.get("/roi/upgrade-options")
async def api_list_upgrade_options(
    infra_type: str = Query(default="power", description="Infrastructure type"),
):
    try:
        options = list_upgrade_options(infra_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "infra_type": infra_type,
        "options": options,
        "count": len(options),
    }


@roi_router.get("/roi/history")
async def get_calculation_history(
    city_slug: str = Query("nairobi"),
    limit: int = Query(20, ge=1, le=100),
):
    """Get past ROI calculation history."""
    return get_roi_history(city_slug=city_slug, limit=limit)
