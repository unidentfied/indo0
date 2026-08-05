from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, JSON, DateTime
from sqlalchemy.orm import declarative_base

CascadeBase = declarative_base()


class CascadeAnalysis(CascadeBase):
    __tablename__ = "cascade_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(String(64), unique=True, index=True, nullable=False)
    city_slug = Column(String(64), index=True, nullable=False)
    trigger_asset_type = Column(String(64), nullable=False)
    trigger_asset_id = Column(String(128), nullable=False)
    cascade_chain = Column(JSON, nullable=False)
    affected_wards = Column(JSON, nullable=False)
    critical_facilities = Column(JSON, nullable=False)
    summary = Column(JSON, nullable=False)
    total_events = Column(Integer, default=0)
    total_pop_affected = Column(Integer, default=0)
    cascade_depth = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "analysis_id": self.analysis_id,
            "city_slug": self.city_slug,
            "trigger_asset_type": self.trigger_asset_type,
            "trigger_asset_id": self.trigger_asset_id,
            "cascade_chain": self.cascade_chain,
            "affected_wards": self.affected_wards,
            "critical_facilities": self.critical_facilities,
            "summary": self.summary,
            "total_events": self.total_events,
            "total_pop_affected": self.total_pop_affected,
            "cascade_depth": self.cascade_depth,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
