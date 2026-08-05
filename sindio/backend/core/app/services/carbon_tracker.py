from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from ..models.carbon import CarbonBase, CarbonBaseline, CarbonCredit

_KES_PER_USD = 145.0


_EMISSION_FACTORS: dict[str, dict[str, float]] = {
    "power": {"fossil_tco2_per_mwh": 0.60, "renewable_tco2_per_mwh": 0.02, "grid_loss_factor": 0.15},
    "water": {"pumping_tco2_per_ml": 0.45, "treatment_tco2_per_ml": 0.25, "leak_factor": 0.30},
    "roads": {"congestion_tco2_per_km_h": 0.18, "idling_tco2_per_h": 0.005, "mode_shift_saving": 0.35},
    "solid_waste": {"landfill_tco2_per_ton": 1.10, "recycling_saving_tco2_per_ton": 0.90, "collection_tco2_per_km": 0.003},
    "lrt": {"tco2_per_passenger_km": 0.035, "car_displacement_saving": 0.12},
    "sgr": {"tco2_per_ton_km": 0.015, "road_displacement_saving": 0.06},
    "airports": {"tco2_per_flight": 5.0, "taxi_saving_per_electric_shuttle": 0.15},
    "sidewalks": {"pedestrian_tco2_per_km": 0.0, "car_displacement_saving_per_km": 0.12},
}


def compute_baseline(city_slug: str, infra_type: str, asset_id: str, asset_count: int = 1) -> float:
    factors = _EMISSION_FACTORS.get(infra_type, {})
    if infra_type == "power":
        return factors.get("fossil_tco2_per_mwh", 0.6) * 1000 * asset_count * (1 + factors.get("grid_loss_factor", 0))
    elif infra_type == "water":
        return (factors.get("pumping_tco2_per_ml", 0.45) + factors.get("treatment_tco2_per_ml", 0.25)) * 365 * asset_count * (1 + factors.get("leak_factor", 0))
    elif infra_type == "roads":
        return factors.get("congestion_tco2_per_km_h", 0.18) * 8760 * asset_count
    elif infra_type == "solid_waste":
        return factors.get("landfill_tco2_per_ton", 1.1) * 365 * asset_count
    elif infra_type == "lrt":
        return factors.get("tco2_per_passenger_km", 0.035) * 100000 * asset_count
    elif infra_type == "sgr":
        return factors.get("tco2_per_ton_km", 0.015) * 500000 * asset_count
    elif infra_type == "airports":
        return factors.get("tco2_per_flight", 5.0) * 100 * asset_count
    elif infra_type == "sidewalks":
        return 0.0
    return 10.0 * asset_count


def compute_carbon_savings(
    city_slug: str,
    infra_type: str,
    asset_id: str,
    upgrade_description: str,
    stress_reduction_pct: float = 20.0,
) -> dict:
    old_baseline = compute_baseline(city_slug, infra_type, asset_id)
    efficiency_gain = stress_reduction_pct / 100.0
    new_baseline = old_baseline * (1 - efficiency_gain * 0.7)
    tco2e_saved = old_baseline - new_baseline

    market_price = 15.0 * _KES_PER_USD
    total_value = tco2e_saved * market_price

    return {
        "asset_id": asset_id,
        "infra_type": infra_type,
        "city": city_slug,
        "upgrade_description": upgrade_description,
        "stress_reduction_pct": stress_reduction_pct,
        "baseline_tco2e_per_year_before": round(old_baseline, 2),
        "baseline_tco2e_per_year_after": round(new_baseline, 2),
        "tco2e_saved_per_year": round(tco2e_saved, 2),
        "market_price_per_tco2e": market_price,
        "estimated_annual_value_kes": round(total_value, 2),
    }


def register_credit(
    engine,
    city_slug: str,
    infra_type: str,
    asset_id: str,
    upgrade_description: str,
    tco2e_saved: float,
) -> dict:
    from sqlalchemy.orm import Session

    credit_id = f"SINDIO-CR-{uuid.uuid4().hex[:12].upper()}"
    cert_seed = f"{credit_id}:{city_slug}:{asset_id}:{tco2e_saved:.2f}"
    certificate_hash = hashlib.sha256(cert_seed.encode()).hexdigest()[:32]

    market_price = 15.0 * _KES_PER_USD
    total_value = tco2e_saved * market_price
    upgrade_date = datetime.now(timezone.utc)
    expires_at = upgrade_date + timedelta(days=365 * 5)

    with Session(bind=engine) as session:
        credit = CarbonCredit(
            city_slug=city_slug,
            infra_type=infra_type,
            asset_id=asset_id,
            credit_id=credit_id,
            tco2e_saved=tco2e_saved,
            upgrade_description=upgrade_description,
            upgrade_date=upgrade_date,
            verification_status="pending",
            certificate_hash=certificate_hash,
            market_price_per_tco2e=market_price,
            total_value_usd=total_value,
            expires_at=expires_at,
            metadata_json={
                "certificate_hash": certificate_hash,
                "standard": "iso_14064",
                "vintage_year": upgrade_date.year,
            },
        )
        session.add(credit)

        baseline = CarbonBaseline(
            city_slug=city_slug,
            infra_type=infra_type,
            asset_id=asset_id,
            baseline_tco2e_per_year=compute_baseline(city_slug, infra_type, asset_id),
            energy_consumption_mwh=0.0,
            emission_factor=_EMISSION_FACTORS.get(infra_type, {}).get("fossil_tco2_per_mwh", 0.0),
            calculation_method="iso_14064",
            data_sources=[_EMISSION_FACTORS.get(infra_type, {})],
        )
        session.add(baseline)
        session.commit()

        return {
            "credit_id": credit_id,
            "certificate_hash": certificate_hash,
            "tco2e_saved": round(tco2e_saved, 2),
            "total_value_kes": round(total_value, 2),
            "verification_status": "pending",
            "expires_at": expires_at.isoformat(),
        }


def get_carbon_dashboard(city_slug: str, engine) -> dict:
    from sqlalchemy.orm import Session
    from sqlalchemy import func

    with Session(bind=engine) as session:
        credits = session.query(CarbonCredit).filter(
            CarbonCredit.city_slug == city_slug
        ).all()

        total_saved = sum(c.tco2e_saved for c in credits)
        total_value = sum(c.total_value_usd for c in credits)
        verified = sum(c.tco2e_saved for c in credits if c.verification_status == "verified")

        by_type = {}
        for c in credits:
            by_type[c.infra_type] = by_type.get(c.infra_type, 0.0) + c.tco2e_saved

        baselines = session.query(CarbonBaseline).filter(
            CarbonBaseline.city_slug == city_slug
        ).all()

        total_baseline = sum(b.baseline_tco2e_per_year for b in baselines)

        return {
            "city": city_slug,
            "total_credits_issued": len(credits),
            "total_tco2e_saved": round(total_saved, 2),
            "total_value_kes": round(total_value, 2),
            "verified_tco2e": round(verified, 2),
            "total_baseline_tco2e_per_year": round(total_baseline, 2),
            "savings_by_infra_type": {k: round(v, 2) for k, v in by_type.items()},
            "credits": [
                {
                    "credit_id": c.credit_id,
                    "infra_type": c.infra_type,
                    "asset_id": c.asset_id,
                    "tco2e_saved": round(c.tco2e_saved, 2),
                    "total_value_kes": round(c.total_value_usd, 2),
                    "verification_status": c.verification_status,
                    "upgrade_description": c.upgrade_description,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in sorted(credits, key=lambda x: x.created_at or datetime.min, reverse=True)[:50]
            ],
        }
