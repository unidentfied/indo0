from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from sqlalchemy.orm import declarative_base

InsuranceBase = declarative_base()


class InsurancePolicy(InsuranceBase):
    __tablename__ = "insurance_policies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    city_slug = Column(String(64), nullable=False, index=True)
    policy_id = Column(String(64), nullable=False, unique=True)
    provider_name = Column(String(128), default="Sindio Parametric")
    policy_type = Column(String(32), nullable=False, default="parametric")
    infra_type = Column(String(64), nullable=False, index=True)
    insured_asset_id = Column(String(128), nullable=False, index=True)
    coverage_amount_usd = Column(Float, default=0.0)
    premium_usd = Column(Float, default=0.0)
    trigger_stress_threshold = Column(Float, default=0.80)
    trigger_window_hours = Column(Integer, default=24)
    payout_percent = Column(Float, default=1.0)
    status = Column(String(32), default="active")
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    metadata_json = Column(JSON, default=dict)


class RiskAssessment(InsuranceBase):
    __tablename__ = "risk_assessments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    city_slug = Column(String(64), nullable=False, index=True)
    asset_id = Column(String(128), nullable=False, index=True)
    infra_type = Column(String(64), nullable=False, index=True)
    risk_score = Column(Float, nullable=False)
    failure_probability_1yr = Column(Float, default=0.0)
    expected_annual_loss_usd = Column(Float, default=0.0)
    max_foreseeable_loss_usd = Column(Float, default=0.0)
    hazard_factors = Column(JSON, default=list)
    vulnerability_factors = Column(JSON, default=list)
    exposure_factors = Column(JSON, default=list)
    assessed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ClaimEvent(InsuranceBase):
    __tablename__ = "claim_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    city_slug = Column(String(64), nullable=False, index=True)
    policy_id = Column(String(64), nullable=False, index=True)
    claim_id = Column(String(64), nullable=False, unique=True)
    trigger_stress_value = Column(Float, nullable=False)
    trigger_timestamp = Column(DateTime, nullable=False)
    payout_amount_usd = Column(Float, default=0.0)
    status = Column(String(32), default="pending")
    verified_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    metadata_json = Column(JSON, default=dict)
