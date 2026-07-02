"""
Sindio — Data Ingestion ORM Models
===================================
SQLAlchemy declarative models for real-world data fetched from
external APIs (Kenya Open Data, NMS, Kenya Power, WorldPop, etc.)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column, String, Float, DateTime, Boolean, Integer,
    Index, UniqueConstraint, create_engine, inspect,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func

Base = declarative_base()


class InfrastructureAsset(Base):
    """Static infrastructure asset geometry + metadata from Open Data."""
    __tablename__ = "infrastructure_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_type = Column(String(32), nullable=False, index=True)   # power, water, roads, etc.
    source_name = Column(String(256), nullable=False)
    geometry_wkt = Column(String(4096))  # WKT in EPSG:32737 (UTM 37S)
    capacity_value = Column(Float, default=0.0)
    capacity_unit = Column(String(16), default="unknown")
    year_constructed = Column(Integer, default=2005)
    last_maintenance = Column(DateTime, default=func.now())
    source_hash = Column(String(64))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("asset_type", "source_name", name="uq_asset_type_source"),
        Index("idx_asset_type_geom", "asset_type", "geometry_wkt"),
    )


class SensorReading(Base):
    """Time-series sensor readings from external APIs / SCADA."""
    __tablename__ = "sensor_readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(String(128), nullable=False, index=True)
    infrastructure_type = Column(String(32), nullable=False, index=True)
    value = Column(Float, nullable=False)
    capacity = Column(Float, default=0.0)
    unit = Column(String(16), default="")
    timestamp = Column(DateTime, nullable=False, index=True)
    source = Column(String(128), nullable=False)   # e.g. "Kenya Power API"
    ward = Column(String(64), default="")
    lat = Column(Float, default=0.0)
    lon = Column(Float, default=0.0)
    is_mock = Column(Boolean, default=False)
    raw_payload = Column(String(4096), default="")  # original JSON for audit
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_reading_time_type", "infrastructure_type", "timestamp"),
        Index("idx_reading_asset_time", "asset_id", "timestamp"),
    )


class PopulationDensity(Base):
    """High-density population points from WorldPop raster sampling."""
    __tablename__ = "population_density"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    density = Column(Float, nullable=False)   # people per km²
    ward = Column(String(64), default="")
    source = Column(String(64), default="worldpop_ken_ppp_2020")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("lat", "lon", name="uq_pop_lat_lon"),
        Index("idx_pop_density", "density"),
    )


class IngestionLog(Base):
    """Audit trail of every fetcher run."""
    __tablename__ = "ingestion_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fetcher_name = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False)   # success | partial | failed
    records_fetched = Column(Integer, default=0)
    records_inserted = Column(Integer, default=0)
    error_message = Column(String(1024), default="")
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=False)


def create_tables(engine_url: str) -> None:
    """Create all ingestion tables if they do not exist."""
    engine = create_engine(engine_url)
    inspector = inspect(engine)
    tables = [InfrastructureAsset.__tablename__, SensorReading.__tablename__,
              PopulationDensity.__tablename__, IngestionLog.__tablename__]
    missing = [t for t in tables if not inspector.has_table(t)]
    if missing:
        Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in missing])


def get_sessionmaker(engine_url: str):
    """Return a configured sessionmaker bound to engine."""
    engine = create_engine(engine_url)
    return sessionmaker(bind=engine)
