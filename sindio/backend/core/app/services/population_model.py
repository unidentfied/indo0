from __future__ import annotations

import random
import math
from datetime import datetime, timezone

from ..models.population import PopulationBase, SyntheticHousehold, MovementPattern


_WARD_POPULATIONS: dict[str, dict[str, int]] = {
    "nairobi": {
        "Central": 32500, "Kilimani": 42000, "Westlands": 55000, "Kibera": 170000,
        "Embakasi": 98000, "Kasarani": 78000, "Dagoretti": 45000, "Kamukunji": 38000,
        "Starehe": 52000, "Mathare": 206000, "Ruaraka": 68000, "Makadara": 56000,
        "Langata": 60000, "Roysambu": 72000, "Kasarani Central": 48000,
    },
    "lagos": {
        "Ikeja": 430000, "Surulere": 595000, "Lagos Island": 209000, "Apapa": 217000,
        "Victoria Island": 83000, "Lekki": 401000, "Yaba": 312000, "Mushin": 633000,
        "Agege": 459000, "Alimosho": 1407000, "Kosofe": 665000, "Oshodi": 470000,
        "Amuwo-Odofin": 318000, "Eti-Osa": 287000, "Ikorodu": 535000,
    },
    "accra": {
        "Osu": 35000, "Jamestown": 16000, "Labone": 28000, "East Legon": 45000,
        "Cantonments": 27000, "Adenta": 78000, "Ashaiman": 208000, "Tema": 161000,
        "Madina": 137000, "Dansoman": 65000, "Achimota": 55000, "Nima": 66000,
        "Kaneshie": 42000, "Dzorwulu": 23000, "Airport Residential": 15000,
    },
    "kigali": {
        "Nyarugenge": 295000, "Gasabo": 585000, "Kicukiro": 350000, "Kimironko": 85000,
        "Remera": 72000, "Kacyiru": 65000, "Gikondo": 55000, "Nyamirambo": 78000,
        "Kimihurura": 42000, "Kiyovu": 35000, "Gisozi": 48000, "Kagarama": 52000,
        "Gatenga": 60000, "Kanombe": 51000, "Rusororo": 38000,
    },
}

_INCOME_DISTRIBUTION = [("low", 0.40), ("medium", 0.40), ("high", 0.15), ("affluent", 0.05)]
_HOUSEHOLD_SIZES = [1, 2, 3, 4, 5, 6, 7, 8]
_HOUSEHOLD_WEIGHTS = [0.10, 0.15, 0.18, 0.22, 0.16, 0.10, 0.06, 0.03]
_PROPERTY_TYPES = ["residential", "residential", "residential", "mixed_use", "commercial", "informal"]
_PRIMARY_MODES = ["walk", "bus", "matatu", "bike", "car", "train", "boda"]
_MODE_WEIGHTS = [0.30, 0.20, 0.25, 0.05, 0.10, 0.03, 0.07]


def generate_synthetic_population(
    engine,
    city_slug: str,
    wards: list[str],
    center_lat: float,
    center_lng: float,
    force: bool = False,
) -> dict:
    from sqlalchemy.orm import Session

    wards_pop = _WARD_POPULATIONS.get(city_slug, {})
    default_pop = 50000

    with Session(bind=engine) as session:
        existing = session.query(SyntheticHousehold.id).filter(
            SyntheticHousehold.city_slug == city_slug
        ).first()

        if existing and not force:
            count = session.query(SyntheticHousehold).filter(
                SyntheticHousehold.city_slug == city_slug
            ).count()
            return {"city": city_slug, "households": count, "status": "already_exists"}

        if force and existing:
            session.query(SyntheticHousehold).filter(
                SyntheticHousehold.city_slug == city_slug
            ).delete()
            session.query(MovementPattern).filter(
                MovementPattern.city_slug == city_slug
            ).delete()
            session.commit()

        total_households = 0
        for ward in wards:
            pop = wards_pop.get(ward, default_pop)
            avg_size = 3.5
            num_households = max(int(pop / avg_size), 50)

            for h in range(num_households):
                size = random.choices(_HOUSEHOLD_SIZES, weights=_HOUSEHOLD_WEIGHTS, k=1)[0]
                income = random.choices(
                    [i[0] for i in _INCOME_DISTRIBUTION],
                    weights=[i[1] for i in _INCOME_DISTRIBUTION],
                    k=1,
                )[0]
                prop_type = random.choice(_PROPERTY_TYPES)
                has_elec = prop_type != "informal" or random.random() < 0.4
                has_water = prop_type != "informal" or random.random() < 0.5

                lat_jitter = random.uniform(-0.04, 0.04)
                lng_jitter = random.uniform(-0.04, 0.04)

                household = SyntheticHousehold(
                    city_slug=city_slug,
                    ward=ward,
                    household_id=f"{city_slug}-{ward}-{h:06d}",
                    size=size,
                    income_level=income,
                    lat=center_lat + lat_jitter,
                    lng=center_lng + lng_jitter,
                    property_type=prop_type,
                    has_electricity=has_elec,
                    has_water=has_water,
                    members=[],
                )
                session.add(household)
                total_households += 1

                if total_households % 1000 == 0:
                    session.flush()

        session.commit()
        return {"city": city_slug, "households": total_households, "status": "generated"}


def generate_movement_patterns(
    engine,
    city_slug: str,
    wards: list[str],
    force: bool = False,
) -> dict:
    from sqlalchemy.orm import Session

    with Session(bind=engine) as session:
        existing = session.query(MovementPattern.id).filter(
            MovementPattern.city_slug == city_slug
        ).first()

        if existing and not force:
            count = session.query(MovementPattern).filter(
                MovementPattern.city_slug == city_slug
            ).count()
            return {"city": city_slug, "patterns": count, "status": "already_exists"}

        if force and existing:
            session.query(MovementPattern).filter(
                MovementPattern.city_slug == city_slug
            ).delete()
            session.commit()

        patterns_created = 0
        for hour in range(24):
            for day in range(7):
                for origin in wards:
                    destinations = [w for w in wards if w != origin][:5]
                    if not destinations:
                        destinations = wards[:1]

                    for dest in destinations:
                        mode = random.choices(_PRIMARY_MODES, weights=_MODE_WEIGHTS, k=1)[0]
                        trip_count = _trip_factor(hour, day) * random.randint(50, 500)
                        duration = random.uniform(5, 120)
                        distance = random.uniform(0.5, 25)

                        pattern = MovementPattern(
                            city_slug=city_slug,
                            hour_of_day=hour,
                            day_of_week=day,
                            origin_ward=origin,
                            destination_ward=dest,
                            trip_count=trip_count,
                            primary_mode=mode,
                            avg_duration_min=round(duration, 1),
                            avg_distance_km=round(distance, 2),
                        )
                        session.add(pattern)
                        patterns_created += 1

                    if patterns_created % 500 == 0:
                        session.flush()

        session.commit()
        return {"city": city_slug, "patterns": patterns_created, "status": "generated"}


def _trip_factor(hour: int, day: int) -> int:
    peak_hours = {7, 8, 9, 17, 18, 19}
    off_peak = {0, 1, 2, 3, 4, 5}
    weekend = {5, 6}

    if hour in off_peak:
        base = 1
    elif hour in peak_hours:
        base = 10
    else:
        base = 4

    if day in weekend:
        base = max(base // 2, 1)

    return base


def get_population_dashboard(city_slug: str, engine) -> dict:
    from sqlalchemy.orm import Session
    from sqlalchemy import func

    with Session(bind=engine) as session:
        total = session.query(func.count(SyntheticHousehold.id)).filter(
            SyntheticHousehold.city_slug == city_slug
        ).scalar() or 0

        by_income = {
            row[0]: row[1]
            for row in session.query(
                SyntheticHousehold.income_level, func.count(SyntheticHousehold.id)
            ).filter(
                SyntheticHousehold.city_slug == city_slug
            ).group_by(SyntheticHousehold.income_level).all()
        }

        by_ward = {}
        for household in session.query(SyntheticHousehold).filter(
            SyntheticHousehold.city_slug == city_slug
        ).all():
            by_ward[household.ward] = by_ward.get(household.ward, 0) + 1

        elec_pct = 0
        water_pct = 0
        if total > 0:
            elec = session.query(func.count(SyntheticHousehold.id)).filter(
                SyntheticHousehold.city_slug == city_slug,
                SyntheticHousehold.has_electricity == True,
            ).scalar() or 0
            water = session.query(func.count(SyntheticHousehold.id)).filter(
                SyntheticHousehold.city_slug == city_slug,
                SyntheticHousehold.has_water == True,
            ).scalar() or 0
            elec_pct = round(elec / total * 100, 1)
            water_pct = round(water / total * 100, 1)

        top_od = session.query(
            MovementPattern.origin_ward,
            MovementPattern.destination_ward,
            func.sum(MovementPattern.trip_count).label("total"),
        ).filter(
            MovementPattern.city_slug == city_slug
        ).group_by(
            MovementPattern.origin_ward,
            MovementPattern.destination_ward,
        ).order_by(func.sum(MovementPattern.trip_count).desc()).limit(10).all()

        return {
            "city": city_slug,
            "total_households": total,
            "estimated_population": total * 4,
            "electricity_access_pct": elec_pct,
            "water_access_pct": water_pct,
            "income_distribution": by_income,
            "wards_by_households": by_ward,
            "top_origin_destination": [
                {"from": r[0], "to": r[1], "trips": r[2]} for r in top_od
            ],
        }
