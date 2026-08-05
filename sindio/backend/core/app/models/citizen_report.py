from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import declarative_base

CitizenReportBase = declarative_base()


class CitizenReport(CitizenReportBase):
    __tablename__ = "citizen_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(String(32), unique=True, index=True, nullable=False)
    category = Column(String(32), index=True, nullable=False)
    description = Column(Text, default="")
    photo_url = Column(String(512), default="")
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    ward = Column(String(64), default="")
    reporter_name = Column(String(128), default="")
    reporter_contact = Column(String(128), default="")
    status = Column(String(32), default="reported", index=True)
    severity = Column(String(16), default="medium")
    upvotes = Column(Integer, default=0)
    resolution_notes = Column(Text, default="")
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "report_id": self.report_id,
            "category": self.category,
            "description": self.description,
            "photo_url": self.photo_url,
            "lat": self.lat,
            "lng": self.lng,
            "ward": self.ward,
            "reporter_name": (self.reporter_name[:2] + "***") if self.reporter_name and len(self.reporter_name) >= 2 else (self.reporter_name or ""),
            "status": self.status,
            "severity": self.severity,
            "upvotes": self.upvotes,
            "resolution_notes": self.resolution_notes,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
