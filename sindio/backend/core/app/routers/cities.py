from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..services.city_config import list_cities, get_city, get_city_wards, get_active_city

city_router = APIRouter()


@city_router.get("/cities")
async def api_list_cities():
    return list_cities()


@city_router.get("/cities/active")
async def api_active_city():
    city = get_active_city()
    return city.to_dict()


@city_router.get("/cities/{slug}")
async def api_get_city(slug: str):
    city = get_city(slug)
    if not city:
        raise HTTPException(status_code=404, detail=f"City '{slug}' not found")
    return city.to_dict()


@city_router.get("/cities/{slug}/wards")
async def api_get_wards(slug: str):
    wards = get_city_wards(slug)
    return {"city": slug, "wards": wards}
