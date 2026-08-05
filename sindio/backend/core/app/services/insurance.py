from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from ..models.insurance import InsuranceBase, InsurancePolicy, RiskAssessment, ClaimEvent

_KES_PER_USD = 145.0


_BASE_PREMIUM_RATES: dict[str, float] = {
    "power": 0.025, "water": 0.020, "roads": 0.018, "solid_waste": 0.012,
    "sidewalks": 0.008, "lrt": 0.022, "sgr": 0.015, "airports": 0.010,
}


def assess_risk(
    city_slug: str, asset_id: str, infra_type: str, current_stress: float = 0.5
) -> dict:
    base_rate = _BASE_PREMIUM_RATES.get(infra_type, 0.02)

    hazard_weight = 0.4
    vulnerability_weight = 0.3
    exposure_weight = 0.3

    hazard_score = min(current_stress * 1.2, 1.0)

    infra_vulnerability = {
        "power": 0.75, "water": 0.70, "roads": 0.55, "solid_waste": 0.40,
        "sidewalks": 0.30, "lrt": 0.65, "sgr": 0.50, "airports": 0.60,
    }
    vulnerability_score = infra_vulnerability.get(infra_type, 0.5)

    exposure_score = min(current_stress, 0.9)

    risk_score = (
        hazard_weight * hazard_score
        + vulnerability_weight * vulnerability_score
        + exposure_weight * exposure_score
    )

    failure_prob_1yr = risk_score * 0.15
    annual_loss_multiplier = 50000 * _KES_PER_USD * base_rate * 100
    expected_annual_loss = risk_score * annual_loss_multiplier
    max_foreseeable_loss = expected_annual_loss * 3.5

    return {
        "asset_id": asset_id,
        "infra_type": infra_type,
        "city": city_slug,
        "risk_score": round(risk_score, 4),
        "failure_probability_1yr": round(failure_prob_1yr, 4),
        "expected_annual_loss_kes": round(expected_annual_loss, 2),
        "max_foreseeable_loss_kes": round(max_foreseeable_loss, 2),
        "recommended_coverage_kes": round(max_foreseeable_loss * 0.8, 2),
        "annual_premium_kes": round(max_foreseeable_loss * base_rate, 2),
        "hazard_factors": [
            {"factor": "stress_level", "value": round(hazard_score, 2), "weight": hazard_weight},
        ],
        "vulnerability_factors": [
            {"factor": "infra_type_vulnerability", "value": round(vulnerability_score, 2), "weight": vulnerability_weight},
        ],
        "exposure_factors": [
            {"factor": "downtime_exposure", "value": round(exposure_score, 2), "weight": exposure_weight},
        ],
    }


def create_policy(
    engine,
    city_slug: str,
    infra_type: str,
    asset_id: str,
    coverage_amount_kes: float,
    trigger_stress_threshold: float = 0.80,
    trigger_window_hours: int = 24,
    duration_days: int = 365,
) -> dict:
    from sqlalchemy.orm import Session

    base_rate = _BASE_PREMIUM_RATES.get(infra_type, 0.02)
    premium = coverage_amount_kes * base_rate
    stress_adj = max(trigger_stress_threshold / 0.85, 0.5)
    premium = premium * stress_adj

    policy_id = f"POL-{uuid.uuid4().hex[:12].upper()}"
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=duration_days)

    risk = assess_risk(city_slug, asset_id, infra_type)

    with Session(bind=engine) as session:
        policy = InsurancePolicy(
            city_slug=city_slug,
            policy_id=policy_id,
            provider_name="Sindio Parametric",
            policy_type="parametric",
            infra_type=infra_type,
            insured_asset_id=asset_id,
            coverage_amount_usd=coverage_amount_kes,
            premium_usd=round(premium, 2),
            trigger_stress_threshold=trigger_stress_threshold,
            trigger_window_hours=trigger_window_hours,
            payout_percent=1.0,
            status="active",
            start_date=start,
            end_date=end,
            metadata_json={"risk_assessment": risk},
        )
        session.add(policy)

        assessment = RiskAssessment(
            city_slug=city_slug,
            asset_id=asset_id,
            infra_type=infra_type,
            risk_score=risk["risk_score"],
            failure_probability_1yr=risk["failure_probability_1yr"],
            expected_annual_loss_usd=risk["expected_annual_loss_kes"],
            max_foreseeable_loss_usd=risk["max_foreseeable_loss_kes"],
            hazard_factors=risk["hazard_factors"],
            vulnerability_factors=risk["vulnerability_factors"],
            exposure_factors=risk["exposure_factors"],
        )
        session.add(assessment)
        session.commit()

        return {
            "policy_id": policy_id,
            "asset_id": asset_id,
            "infra_type": infra_type,
            "coverage_amount_kes": coverage_amount_kes,
            "annual_premium_kes": round(premium, 2),
            "trigger_stress_threshold": trigger_stress_threshold,
            "trigger_window_hours": trigger_window_hours,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "status": "active",
            "risk_assessment": risk,
        }


def check_trigger_and_claim(
    engine,
    city_slug: str,
    infra_type: str,
    asset_id: str,
    current_stress: float,
) -> dict:
    from sqlalchemy.orm import Session

    with Session(bind=engine) as session:
        policy = session.query(InsurancePolicy).filter(
            InsurancePolicy.city_slug == city_slug,
            InsurancePolicy.infra_type == infra_type,
            InsurancePolicy.insured_asset_id == asset_id,
            InsurancePolicy.status == "active",
        ).order_by(InsurancePolicy.created_at.desc()).first()

        if not policy:
            return {"triggered": False, "reason": "no_active_policy"}

        if policy.trigger_window_hours and policy.trigger_window_hours > 0:
            window_start = datetime.now(timezone.utc) - timedelta(hours=policy.trigger_window_hours)
            recent_claim = session.query(ClaimEvent).filter(
                ClaimEvent.policy_id == policy.policy_id,
                ClaimEvent.created_at >= window_start,
            ).first()
            if recent_claim:
                return {
                    "triggered": False,
                    "reason": "claim_already_filed_in_window",
                    "existing_claim": recent_claim.claim_id,
                }

        if current_stress >= policy.trigger_stress_threshold:
            payout = policy.coverage_amount_usd * policy.payout_percent
            claim_id = f"CLM-{uuid.uuid4().hex[:12].upper()}"

            claim = ClaimEvent(
                city_slug=city_slug,
                policy_id=policy.policy_id,
                claim_id=claim_id,
                trigger_stress_value=current_stress,
                trigger_timestamp=datetime.now(timezone.utc),
                payout_amount_usd=round(payout, 2),
                status="pending",
                metadata_json={
                    "policy_id": policy.policy_id,
                    "trigger_threshold": policy.trigger_stress_threshold,
                    "actual_stress": current_stress,
                },
            )
            session.add(claim)
            session.commit()

            return {
                "triggered": True,
                "claim_id": claim_id,
                "policy_id": policy.policy_id,
                "trigger_stress": current_stress,
                "threshold": policy.trigger_stress_threshold,
                "payout_amount_kes": round(payout, 2),
                "status": "pending",
            }

        return {"triggered": False, "reason": "below_threshold", "current_stress": current_stress, "threshold": policy.trigger_stress_threshold}


def get_insurance_dashboard(city_slug: str, engine) -> dict:
    from sqlalchemy.orm import Session
    from sqlalchemy import func

    with Session(bind=engine) as session:
        policies = session.query(InsurancePolicy).filter(
            InsurancePolicy.city_slug == city_slug
        ).all()

        active = [p for p in policies if p.status == "active"]
        total_coverage = sum(p.coverage_amount_usd for p in active)
        total_premium = sum(p.premium_usd for p in active)

        claims = session.query(ClaimEvent).filter(
            ClaimEvent.city_slug == city_slug
        ).all()

        paid = sum(c.payout_amount_usd for c in claims if c.status == "paid")
        pending = sum(c.payout_amount_usd for c in claims if c.status == "pending")

        by_type = {}
        for p in active:
            by_type[p.infra_type] = by_type.get(p.infra_type, 0) + p.coverage_amount_usd

        assessments = session.query(RiskAssessment).filter(
            RiskAssessment.city_slug == city_slug
        ).order_by(RiskAssessment.risk_score.desc()).limit(10).all()

        return {
            "city": city_slug,
            "total_policies": len(policies),
            "active_policies": len(active),
            "total_coverage_kes": round(total_coverage, 2),
            "total_premium_kes": round(total_premium, 2),
            "total_claims": len(claims),
            "total_paid_kes": round(paid, 2),
            "total_pending_kes": round(pending, 2),
            "coverage_by_infra_type": {k: round(v, 2) for k, v in by_type.items()},
            "top_risks": [
                {
                    "asset_id": a.asset_id,
                    "infra_type": a.infra_type,
                    "risk_score": round(a.risk_score, 4),
                    "expected_annual_loss_kes": round(a.expected_annual_loss_usd, 2),
                }
                for a in assessments
            ],
            "recent_claims": [
                {
                    "claim_id": c.claim_id,
                    "policy_id": c.policy_id,
                    "trigger_stress": round(c.trigger_stress_value, 4),
                    "payout_kes": round(c.payout_amount_usd, 2),
                    "status": c.status,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in sorted(claims, key=lambda x: x.created_at or datetime.min, reverse=True)[:20]
            ],
        }
