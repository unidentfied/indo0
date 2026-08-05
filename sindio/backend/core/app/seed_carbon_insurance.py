"""
Seed carbon credits and parametric insurance data for all 8 infrastructure types.
Uses the actual computation functions — not synthetic stubs.

Usage:
  cd sindio/backend/core
  poetry run python -m app.seed_carbon_insurance
  # or: PYTHONPATH=. python app/seed_carbon_insurance.py
"""
import os
import sys
import logging
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("sindio.seed")

INFRA_TYPES = ["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"]
CITY = "nairobi"

INFRA_ASSETS = {
    "power":       ["substation-main-001", "transmission-line-002", "distribution-tx-003"],
    "water":       ["reservoir-main-001", "treatment-plant-002", "pump-station-003"],
    "roads":       ["uhuru-highway-001", "thika-road-002", "mombasa-road-003"],
    "solid_waste": ["dandora-landfill-001", "transfer-station-002", "collection-depot-003"],
    "sidewalks":   ["cbd-walkway-001", "upphill-promenade-002", "westlands-path-003"],
    "lrt":         ["line-a-station-001", "line-b-depot-002", "line-a-signal-003"],
    "sgr":         ["sgr-nairobi-001", "sgr-yard-002", "sgr-bridge-003"],
    "airports":    ["jkia-terminal-1a", "jkia-runway-06", "jkia-apron-bravo"],
}

UPGRADE_DESCRIPTIONS = {
    "power":       "Substation transformer upgrade with smart-grid integration",
    "water":       "High-efficiency pump system with leak detection sensors",
    "roads":       "Adaptive traffic signal network with congestion pricing",
    "solid_waste": "Methane capture system with waste-to-energy conversion",
    "sidewalks":   "Pedestrian corridor expansion with green canopy",
    "lrt":         "Regenerative braking system and frequency optimization",
    "sgr":         "Electric locomotive conversion and track optimization",
    "airports":    "Electric ground support equipment and gate electrification",
}


def ensure_tables():
    from app.models.carbon import CarbonBase
    from app.models.insurance import InsuranceBase
    from app.database import get_engine

    engine = get_engine()
    CarbonBase.metadata.create_all(bind=engine)
    InsuranceBase.metadata.create_all(bind=engine)
    logger.info("Carbon and insurance tables verified/created")
    return engine


def seed_carbon(engine):
    from app.services.carbon_tracker import compute_baseline, register_credit
    from app.models.carbon import CarbonCredit

    logger.info("Seeding carbon baselines and credits...")

    for infra_type in INFRA_TYPES:
        assets = INFRA_ASSETS[infra_type]
        for asset_id in assets:
            try:
                tco2e_per_yr = compute_baseline(CITY, infra_type, asset_id, asset_count=1)
                if tco2e_per_yr <= 0:
                    continue

                stress_reduction = {"power": 25, "water": 20, "roads": 18, "solid_waste": 22,
                                    "sidewalks": 15, "lrt": 20, "sgr": 18, "airports": 30}[infra_type]

                register_credit(
                    engine, CITY, infra_type, asset_id,
                    UPGRADE_DESCRIPTIONS[infra_type],
                    tco2e_per_yr * (stress_reduction / 100),
                )
            except Exception as exc:
                logger.warning("Skipping %s/%s: %s", infra_type, asset_id, exc)

    from sqlalchemy.orm import Session
    with Session(bind=engine) as session:
        count = session.query(CarbonCredit).filter(
            CarbonCredit.city_slug == CITY
        ).count()
    logger.info("  %d carbon credits seeded for %s", count, CITY)


def seed_insurance(engine):
    from app.services.insurance import assess_risk, create_policy
    from app.models.insurance import InsurancePolicy, ClaimEvent

    logger.info("Seeding insurance policies and risk assessments...")

    policies_created = []
    for infra_type in INFRA_TYPES:
        assets = INFRA_ASSETS[infra_type]
        for asset_id in assets:
            try:
                risk = assess_risk(CITY, asset_id, infra_type, current_stress=0.55)
                coverage = risk["recommended_coverage_kes"] / 145.0

                policy = create_policy(
                    engine, CITY, infra_type, asset_id,
                    coverage, risk["risk_score"] + 0.05, 24, 365,
                )
                policies_created.append({
                    "policy_id": policy["policy_id"],
                    "infra_type": infra_type,
                    "trigger_stress": policy["trigger_stress_threshold"],
                    "coverage": coverage,
                })
            except Exception as exc:
                logger.warning("Skipping %s/%s: %s", infra_type, asset_id, exc)

    from sqlalchemy.orm import Session
    with Session(bind=engine) as session:
        policy_count = session.query(InsurancePolicy).filter(
            InsurancePolicy.city_slug == CITY
        ).count()

    from app.models.insurance import ClaimEvent as CE
    for i, pol in enumerate(policies_created[:8]):
        try:
            trigger_stress = round(pol["trigger_stress"] + 0.02, 4)
            with Session(bind=engine) as session:
                import uuid
                claim = CE(
                    city_slug=CITY,
                    policy_id=pol["policy_id"],
                    claim_id=f"CL-{uuid.uuid4().hex[:12].upper()}",
                    trigger_stress_value=trigger_stress,
                    trigger_timestamp=datetime.now(timezone.utc) - timedelta(days=i * 30),
                    payout_amount_usd=pol["coverage"] * (0.3 + i * 0.05),
                    status="paid" if i < 5 else "pending",
                )
                session.add(claim)
                session.commit()
        except Exception as exc:
            logger.warning("Claim seed failed for %s: %s", pol["infra_type"], exc)

    with Session(bind=engine) as session:
        claim_count = session.query(CE).filter(CE.city_slug == CITY).count()
    logger.info("  %d policies, %d claims seeded for %s", policy_count, claim_count, CITY)


def main():
    import os as _os

    _base = _os.path.dirname(_os.path.abspath(__file__))
    _core = _os.path.dirname(_base)
    if _core not in sys.path:
        sys.path.insert(0, _core)

    try:
        from dotenv import load_dotenv
        load_dotenv(_os.path.join(_core, '..', '..', '.env'))
    except ImportError:
        pass

    logger.info("Seeder: carbon credits + parametric insurance")
    try:
        engine = ensure_tables()
    except Exception as exc:
        logger.error("Cannot create tables: %s. Is the database running?", exc)
        return 1

    seed_carbon(engine)
    seed_insurance(engine)
    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
