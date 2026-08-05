from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..database import get_engine
from ..services.carbon_tracker import (
    compute_carbon_savings,
    register_credit,
    get_carbon_dashboard,
    compute_baseline,
)
from ..services.city_config import get_city

carbon_router = APIRouter()


class CarbonRegistrationRequest(BaseModel):
    city_slug: str = "nairobi"
    infra_type: str
    asset_id: str
    upgrade_description: str
    stress_reduction_pct: float = 20.0


@carbon_router.get("/carbon/baseline")
async def api_compute_baseline(
    city_slug: str = Query(default="nairobi"),
    infra_type: str = Query(default="power"),
    asset_id: str = Query(default="asset-001"),
    asset_count: int = Query(default=1),
):
    city = get_city(city_slug)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{city_slug}' not found")

    tco2e = compute_baseline(city_slug, infra_type, asset_id, asset_count)
    return {
        "city": city_slug,
        "infra_type": infra_type,
        "asset_id": asset_id,
        "baseline_tco2e_per_year": round(tco2e, 2),
    }


@carbon_router.post("/carbon/calculate-savings")
async def api_calculate_savings(req: CarbonRegistrationRequest):
    city = get_city(req.city_slug)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{req.city_slug}' not found")

    return compute_carbon_savings(
        req.city_slug,
        req.infra_type,
        req.asset_id,
        req.upgrade_description,
        req.stress_reduction_pct,
    )


@carbon_router.post("/carbon/register-credit")
async def api_register_credit(req: CarbonRegistrationRequest):
    city = get_city(req.city_slug)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{req.city_slug}' not found")

    savings = compute_carbon_savings(
        req.city_slug,
        req.infra_type,
        req.asset_id,
        req.upgrade_description,
        req.stress_reduction_pct,
    )

    return register_credit(
        get_engine(),
        req.city_slug,
        req.infra_type,
        req.asset_id,
        req.upgrade_description,
        savings["tco2e_saved_per_year"],
    )


@carbon_router.get("/carbon/dashboard")
async def api_carbon_dashboard(
    city_slug: str = Query(default="nairobi"),
):
    city = get_city(city_slug)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{city_slug}' not found")

    return get_carbon_dashboard(city_slug, get_engine())
