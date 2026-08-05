from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, JSON, DateTime
from sqlalchemy.orm import declarative_base

RoiBase = declarative_base()


class RoiCalculation(RoiBase):
    __tablename__ = "roi_calculations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    calculation_id = Column(String(64), unique=True, index=True, nullable=False)
    city_slug = Column(String(64), index=True, nullable=False)
    infra_type = Column(String(32), index=True, nullable=False)
    asset_id = Column(String(128), nullable=False)
    upgrade_description = Column(String(512), default="")
    upgrade_cost_usd = Column(Float, nullable=False)
    asset_lifespan_years = Column(Integer, default=20)
    estimated_annual_savings_usd = Column(Float, nullable=False)
    payback_period_years = Column(Float, nullable=False)
    five_year_roi_pct = Column(Float, nullable=False)
    ten_year_roi_pct = Column(Float, nullable=False)
    twenty_year_roi_pct = Column(Float, nullable=False)
    npv_usd = Column(Float, nullable=False)
    avoided_outage_days_per_year = Column(Float, default=0.0)
    avoided_outage_cost_per_year_usd = Column(Float, default=0.0)
    maintenance_savings_per_year_usd = Column(Float, default=0.0)
    efficiency_gain_savings_per_year_usd = Column(Float, default=0.0)
    recommendation = Column(String(16), default="medium")
    breakdown = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "calculation_id": self.calculation_id,
            "city_slug": self.city_slug,
            "infra_type": self.infra_type,
            "asset_id": self.asset_id,
            "upgrade_description": self.upgrade_description,
            "upgrade_cost_kes": self.upgrade_cost_usd,
            "asset_lifespan_years": self.asset_lifespan_years,
            "estimated_annual_savings_kes": self.estimated_annual_savings_usd,
            "payback_period_years": self.payback_period_years,
            "5yr_roi_pct": self.five_year_roi_pct,
            "10yr_roi_pct": self.ten_year_roi_pct,
            "20yr_roi_pct": self.twenty_year_roi_pct,
            "npv_kes": self.npv_usd,
            "avoided_outage_days_per_year": self.avoided_outage_days_per_year,
            "avoided_outage_cost_per_year_kes": self.avoided_outage_cost_per_year_usd,
            "maintenance_savings_per_year_kes": self.maintenance_savings_per_year_usd,
            "efficiency_gain_savings_per_year_kes": self.efficiency_gain_savings_per_year_usd,
            "recommendation": self.recommendation,
            "breakdown": self.breakdown,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
