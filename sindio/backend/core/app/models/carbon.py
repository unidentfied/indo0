from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from sqlalchemy.orm import declarative_base

CarbonBase = declarative_base()


class CarbonBaseline(CarbonBase):
    __tablename__ = "carbon_baselines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    city_slug = Column(String(64), nullable=False, index=True)
    infra_type = Column(String(64), nullable=False, index=True)
    asset_id = Column(String(128), nullable=False)
    baseline_tco2e_per_year = Column(Float, nullable=False)
    energy_consumption_mwh = Column(Float, default=0.0)
    emission_factor = Column(Float, default=0.0)
    calculation_method = Column(String(64), default="iso_14064")
    data_sources = Column(JSON, default=list)
    calculated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CarbonCredit(CarbonBase):
    __tablename__ = "carbon_credits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    city_slug = Column(String(64), nullable=False, index=True)
    infra_type = Column(String(64), nullable=False, index=True)
    asset_id = Column(String(128), nullable=False)
    credit_id = Column(String(64), nullable=False, unique=True)
    tco2e_saved = Column(Float, nullable=False)
    upgrade_description = Column(String(512), default="")
    upgrade_date = Column(DateTime, nullable=False)
    verification_status = Column(String(32), default="pending")
    verification_body = Column(String(128), default="")
    certificate_hash = Column(String(128), default="")
    market_price_per_tco2e = Column(Float, default=0.0)
    total_value_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    verified_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    metadata_json = Column(JSON, default=dict)
