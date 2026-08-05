from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CITY_DEFS_DIR = Path(__file__).resolve().parent.parent / "city_defs"
CITY_DEFS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class CityDef:
    slug: str
    name: str
    country: str
    timezone: str
    center_lat: float
    center_lng: float
    zoom: int
    bbox_west: float
    bbox_south: float
    bbox_east: float
    bbox_north: float
    wards: list[str] = field(default_factory=list)
    data_sources: dict = field(default_factory=dict)
    infra_overrides: dict = field(default_factory=dict)
    is_active: bool = True

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "country": self.country,
            "timezone": self.timezone,
            "center": {"lat": self.center_lat, "lng": self.center_lng},
            "zoom": self.zoom,
            "bbox": {
                "west": self.bbox_west,
                "south": self.bbox_south,
                "east": self.bbox_east,
                "north": self.bbox_north,
            },
            "wards": self.wards,
            "data_sources": self.data_sources,
            "infra_overrides": self.infra_overrides,
            "is_active": self.is_active,
        }

    @property
    def bbox_str(self) -> str:
        return f"{self.bbox_west},{self.bbox_south},{self.bbox_east},{self.bbox_north}"

    @property
    def osm_bbox_str(self) -> str:
        return f"{self.bbox_south},{self.bbox_west},{self.bbox_north},{self.bbox_east}"


BUILTIN_CITY_DEFS: dict[str, CityDef] = {}


def _register_city(defn: CityDef) -> None:
    BUILTIN_CITY_DEFS[defn.slug] = defn


def _load_json_cities() -> None:
    if not CITY_DEFS_DIR.exists():
        return
    for f in sorted(CITY_DEFS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            _register_city(CityDef(**data))
        except Exception:
            pass


_NAIROBI_WARDS = [
    "Central", "Kilimani", "Westlands", "Kibera", "Embakasi",
    "Kasarani", "Dagoretti", "Kamukunji", "Starehe", "Mathare",
    "Ruaraka", "Makadara", "Langata", "Roysambu", "Kasarani Central",
]

_register_city(CityDef(
    slug="nairobi",
    name="Nairobi",
    country="Kenya",
    timezone="Africa/Nairobi",
    center_lat=-1.2833,
    center_lng=36.8219,
    zoom=13,
    bbox_west=36.65,
    bbox_south=-1.45,
    bbox_east=37.00,
    bbox_north=-1.15,
    wards=_NAIROBI_WARDS,
    data_sources={
        "power": "Kenya Power API",
        "water": "Nairobi Water & Sewerage Company",
        "roads": "Kenya National Highway Authority + OSM Traffic",
        "solid_waste": "Nairobi County Waste Management",
        "airports": "Kenya Airports Authority + OpenSky",
        "lrt": "Nairobi Rail Authority",
        "sgr": "Kenya Railways SGR Operations",
    },
    infra_overrides={
        "power": {"region": "Central District", "default_asset_count": 800},
        "water": {"region": "Westlands", "default_asset_count": 600},
        "roads": {"region": "Industrial Area", "default_asset_count": 1200},
        "solid_waste": {"region": "Eastleigh", "default_asset_count": 300},
        "sidewalks": {"region": "CBD", "default_asset_count": 400},
        "lrt": {"region": "Upper Hill", "default_asset_count": 50},
        "sgr": {"region": "Embakasi", "default_asset_count": 30},
        "airports": {"region": "Embakasi", "default_asset_count": 5},
    },
))

_LAGOS_WARDS = [
    "Ikeja", "Surulere", "Lagos Island", "Apapa", "Victoria Island",
    "Lekki", "Yaba", "Mushin", "Agege", "Alimosho",
    "Kosofe", "Oshodi", "Amuwo-Odofin", "Eti-Osa", "Ikorodu",
]

_register_city(CityDef(
    slug="lagos",
    name="Lagos",
    country="Nigeria",
    timezone="Africa/Lagos",
    center_lat=6.4550,
    center_lng=3.3941,
    zoom=12,
    bbox_west=3.24,
    bbox_south=6.38,
    bbox_east=3.70,
    bbox_north=6.70,
    wards=_LAGOS_WARDS,
    data_sources={
        "power": "Eko Electricity + Ikeja Electric Distribution",
        "water": "Lagos Water Corporation",
        "roads": "Lagos State Ministry of Transport + OSM",
        "solid_waste": "LAWMA (Lagos Waste Management Authority)",
        "airports": "FAAN Murtala Muhammed Airport + OpenSky",
        "lrt": "LAMATA Blue Line Rail",
    },
    infra_overrides={
        "power": {"region": "Ikeja Industrial", "default_asset_count": 900},
        "water": {"region": "Surulere", "default_asset_count": 500},
        "roads": {"region": "Apapa Corridor", "default_asset_count": 1500},
        "solid_waste": {"region": "Olusosun", "default_asset_count": 350},
        "sidewalks": {"region": "Victoria Island", "default_asset_count": 250},
        "lrt": {"region": "Marina", "default_asset_count": 40},
        "sgr": {"region": "Apapa", "default_asset_count": 20},
        "airports": {"region": "Ikeja", "default_asset_count": 3},
    },
))

_ACCRA_WARDS = [
    "Osu", "Jamestown", "Labone", "East Legon", "Cantonments",
    "Adenta", "Ashaiman", "Tema", "Madina", "Dansoman",
    "Achimota", "Nima", "Kaneshie", "Dzorwulu", "Airport Residential",
]

_register_city(CityDef(
    slug="accra",
    name="Accra",
    country="Ghana",
    timezone="Africa/Accra",
    center_lat=5.5600,
    center_lng=-0.2057,
    zoom=12,
    bbox_west=-0.40,
    bbox_south=5.45,
    bbox_east=-0.05,
    bbox_north=5.75,
    wards=_ACCRA_WARDS,
    data_sources={
        "power": "ECG (Electricity Company of Ghana)",
        "water": "Ghana Water Company Limited",
        "roads": "Ghana Highway Authority + OSM",
        "solid_waste": "Accra Metropolitan Assembly Waste",
        "airports": "GACL Kotoka International + OpenSky",
    },
    infra_overrides={
        "power": {"region": "Tema Industrial", "default_asset_count": 600},
        "water": {"region": "Weija Catchment", "default_asset_count": 400},
        "roads": {"region": "Spintex Corridor", "default_asset_count": 1000},
        "solid_waste": {"region": "Kpone Landfill", "default_asset_count": 200},
        "sidewalks": {"region": "Airport Residential", "default_asset_count": 300},
        "lrt": {"region": "Tema Motorway", "default_asset_count": 25},
        "sgr": {"region": "Tema Harbour", "default_asset_count": 15},
        "airports": {"region": "Kotoka", "default_asset_count": 2},
    },
))

_KIGALI_WARDS = [
    "Nyarugenge", "Gasabo", "Kicukiro", "Kimironko", "Remera",
    "Kacyiru", "Gikondo", "Nyamirambo", "Kimihurura", "Kiyovu",
    "Gisozi", "Kagarama", "Gatenga", "Kanombe", "Rusororo",
]

_register_city(CityDef(
    slug="kigali",
    name="Kigali",
    country="Rwanda",
    timezone="Africa/Kigali",
    center_lat=-1.9501,
    center_lng=30.0587,
    zoom=13,
    bbox_west=29.95,
    bbox_south=-2.05,
    bbox_east=30.20,
    bbox_north=-1.85,
    wards=_KIGALI_WARDS,
    data_sources={
        "power": "REG (Rwanda Energy Group)",
        "water": "WASAC (Water & Sanitation Corporation)",
        "roads": "Rwanda Transport Development Agency + OSM",
        "solid_waste": "City of Kigali Waste Management",
        "airports": "RCAA Kigali International + OpenSky",
    },
    infra_overrides={
        "power": {"region": "Gikondo Industrial", "default_asset_count": 400},
        "water": {"region": "Nyarugenge", "default_asset_count": 300},
        "roads": {"region": "CBD Corridor", "default_asset_count": 600},
        "solid_waste": {"region": "Nduba Landfill", "default_asset_count": 150},
        "sidewalks": {"region": "Kiyovu", "default_asset_count": 350},
        "lrt": {"region": "Kacyiru", "default_asset_count": 20},
        "sgr": {"region": "Gatsata", "default_asset_count": 10},
        "airports": {"region": "Kanombe", "default_asset_count": 1},
    },
))

_load_json_cities()


def get_active_city() -> CityDef:
    slug = os.getenv("SINDIO_CITY", "nairobi")
    city = BUILTIN_CITY_DEFS.get(slug)
    if city:
        return city
    return BUILTIN_CITY_DEFS["nairobi"]


def get_city(slug: str) -> Optional[CityDef]:
    return BUILTIN_CITY_DEFS.get(slug)


def list_cities() -> list[dict]:
    return [c.to_dict() for c in BUILTIN_CITY_DEFS.values() if c.is_active]


def get_city_wards(city_slug: str) -> list[str]:
    city = get_city(city_slug)
    if city:
        return city.wards
    return _NAIROBI_WARDS
