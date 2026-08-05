from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import optional_auth
from ..database import get_engine
from ..services.insurance import (
    assess_risk,
    create_policy,
    check_trigger_and_claim,
    get_insurance_dashboard,
)
from ..services.city_config import get_city

insurance_router = APIRouter(prefix="/insurance", tags=["insurance"])


class PolicyCreateRequest(BaseModel):
    city_slug: str = "nairobi"
    infra_type: str
    asset_id: str
    coverage_amount_kes: float
    trigger_stress_threshold: float = 0.80
    trigger_window_hours: int = 24
    duration_days: int = 365


class ClaimCheckRequest(BaseModel):
    city_slug: str = "nairobi"
    infra_type: str
    asset_id: str
    current_stress: float


@insurance_router.get("/assess-risk", dependencies=[Depends(optional_auth)])
async def api_assess_risk(
    city_slug: str = Query(default="nairobi"),
    asset_id: str = Query(default="asset-001"),
    infra_type: str = Query(default="power"),
    current_stress: float = Query(default=0.5),
):
    city = get_city(city_slug)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{city_slug}' not found")

    return assess_risk(city_slug, asset_id, infra_type, current_stress)


@insurance_router.post("/create-policy", dependencies=[Depends(optional_auth)])
async def api_create_policy(req: PolicyCreateRequest):
    city = get_city(req.city_slug)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{req.city_slug}' not found")

    return create_policy(
        get_engine(),
        req.city_slug,
        req.infra_type,
        req.asset_id,
        req.coverage_amount_kes,
        req.trigger_stress_threshold,
        req.trigger_window_hours,
        req.duration_days,
    )


@insurance_router.post("/check-claim", dependencies=[Depends(optional_auth)])
async def api_check_claim(req: ClaimCheckRequest):
    city = get_city(req.city_slug)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{req.city_slug}' not found")

    return check_trigger_and_claim(
        get_engine(),
        req.city_slug,
        req.infra_type,
        req.asset_id,
        req.current_stress,
    )


@insurance_router.get("/dashboard", dependencies=[Depends(optional_auth)])
async def api_insurance_dashboard(
    city_slug: str = Query(default="nairobi"),
):
    city = get_city(city_slug)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{city_slug}' not found")

    return get_insurance_dashboard(city_slug, get_engine())
