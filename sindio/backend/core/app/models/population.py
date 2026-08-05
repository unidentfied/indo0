from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import declarative_base

PopulationBase = declarative_base()


class SyntheticHousehold(PopulationBase):
    __tablename__ = "synthetic_households"

    id = Column(Integer, primary_key=True, autoincrement=True)
    city_slug = Column(String(64), nullable=False, index=True)
    ward = Column(String(128), nullable=False, index=True)
    household_id = Column(String(64), nullable=False, unique=True)
    size = Column(Integer, default=1)
    income_level = Column(String(16), default="medium")
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    property_type = Column(String(32), default="residential")
    has_electricity = Column(Boolean, default=True)
    has_water = Column(Boolean, default=True)
    members = Column(JSON, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "city_slug": self.city_slug,
            "ward": self.ward,
            "household_id": self.household_id,
            "size": self.size,
            "income_level": self.income_level,
            "lat": self.lat,
            "lng": self.lng,
            "property_type": self.property_type,
            "has_electricity": self.has_electricity,
            "has_water": self.has_water,
            "members": self.members,
        }


class MovementPattern(PopulationBase):
    __tablename__ = "movement_patterns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    city_slug = Column(String(64), nullable=False, index=True)
    hour_of_day = Column(Integer, nullable=False)
    day_of_week = Column(Integer, nullable=False)
    origin_ward = Column(String(128), nullable=False, index=True)
    destination_ward = Column(String(128), nullable=False)
    trip_count = Column(Integer, default=0)
    primary_mode = Column(String(32), default="bus")
    avg_duration_min = Column(Float, default=15.0)
    avg_distance_km = Column(Float, default=3.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "city_slug": self.city_slug,
            "hour_of_day": self.hour_of_day,
            "day_of_week": self.day_of_week,
            "origin_ward": self.origin_ward,
            "destination_ward": self.destination_ward,
            "trip_count": self.trip_count,
            "primary_mode": self.primary_mode,
            "avg_duration_min": self.avg_duration_min,
            "avg_distance_km": self.avg_distance_km,
        }
