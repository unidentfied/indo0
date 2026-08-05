from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..database import get_engine
from ..services.population_model import (
    generate_synthetic_population,
    generate_movement_patterns,
    get_population_dashboard,
)
from ..services.city_config import get_city, get_active_city

population_router = APIRouter()


@population_router.post("/population/generate")
async def api_generate_population(
    city_slug: str = Query(default="nairobi"),
    force: bool = Query(default=False),
):
    city = get_city(city_slug)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{city_slug}' not found")

    result = generate_synthetic_population(
        get_engine(), city_slug, city.wards, city.center_lat, city.center_lng, force=force
    )
    return result


@population_router.post("/population/movements/generate")
async def api_generate_movements(
    city_slug: str = Query(default="nairobi"),
    force: bool = Query(default=False),
):
    city = get_city(city_slug)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{city_slug}' not found")

    result = generate_movement_patterns(get_engine(), city_slug, city.wards, force=force)
    return result


@population_router.get("/population/dashboard")
async def api_population_dashboard(
    city_slug: str = Query(default="nairobi"),
):
    city = get_city(city_slug)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{city_slug}' not found")

    return get_population_dashboard(city_slug, get_engine())
