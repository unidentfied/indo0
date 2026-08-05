from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

CityBase = declarative_base()


class City(CityBase):
    __tablename__ = "cities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    country = Column(String(64), nullable=False)
    timezone = Column(String(64), default="Africa/Nairobi")
    center_lat = Column(Float, nullable=False)
    center_lng = Column(Float, nullable=False)
    zoom = Column(Integer, default=13)
    bbox_west = Column(Float, nullable=False)
    bbox_south = Column(Float, nullable=False)
    bbox_east = Column(Float, nullable=False)
    bbox_north = Column(Float, nullable=False)
    wards = Column(JSON, nullable=False, default=list)
    data_sources = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    infra_overrides = relationship("CityInfraOverride", back_populates="city", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "country": self.country,
            "timezone": self.timezone,
            "center": {"lat": self.center_lat, "lng": self.center_lng},
            "zoom": self.zoom,
            "bbox": {
                "west": self.bbox_west,
                "south": self.bbox_south,
                "east": self.bbox_east,
                "north": self.bbox_north,
            },
            "wards": self.wards,
            "data_sources": self.data_sources,
            "is_active": self.is_active,
            "infra_overrides": [o.to_dict() for o in self.infra_overrides],
        }


class CityInfraOverride(CityBase):
    __tablename__ = "city_infra_overrides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False)
    infra_type = Column(String(64), nullable=False)
    region = Column(String(128), default="")
    unit = Column(String(32), default="")
    data_sources = Column(JSON, default=list)
    thresholds = Column(JSON, default=dict)
    actions = Column(JSON, default=dict)
    heuristic_base_stress = Column(Float, default=0.3)
    heuristic_variance = Column(Float, default=0.1)
    default_asset_count = Column(Integer, default=500)

    city = relationship("City", back_populates="infra_overrides")

    def to_dict(self) -> dict:
        return {
            "infra_type": self.infra_type,
            "region": self.region,
            "unit": self.unit,
            "data_sources": self.data_sources,
            "thresholds": self.thresholds,
            "actions": self.actions,
            "heuristic_base_stress": self.heuristic_base_stress,
            "heuristic_variance": self.heuristic_variance,
            "default_asset_count": self.default_asset_count,
        }
