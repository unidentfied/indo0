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


_MONITOR_DDL = {
    "power_scada": """
        CREATE TABLE IF NOT EXISTS power_scada (
            id SERIAL PRIMARY KEY,
            bus_id VARCHAR(64) NOT NULL,
            voltage_pu FLOAT NOT NULL,
            load_mw FLOAT NOT NULL,
            ward VARCHAR(64) DEFAULT '',
            lat FLOAT DEFAULT 0,
            lon FLOAT DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            inserted_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_power_scada_time ON power_scada(updated_at);
        CREATE INDEX IF NOT EXISTS idx_power_scada_bus ON power_scada(bus_id);
    """,
    "water_scada": """
        CREATE TABLE IF NOT EXISTS water_scada (
            id SERIAL PRIMARY KEY,
            node_id VARCHAR(64) NOT NULL,
            pressure_m FLOAT NOT NULL,
            flow_lps FLOAT NOT NULL,
            ward VARCHAR(64) DEFAULT '',
            lat FLOAT DEFAULT 0,
            lon FLOAT DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            inserted_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_water_scada_time ON water_scada(updated_at);
        CREATE INDEX IF NOT EXISTS idx_water_scada_node ON water_scada(node_id);
    """,
    "mobility_aggregates": """
        CREATE TABLE IF NOT EXISTS mobility_aggregates (
            id SERIAL PRIMARY KEY,
            h3_index VARCHAR(32) NOT NULL,
            vehicle_count FLOAT NOT NULL,
            ward VARCHAR(64) DEFAULT '',
            lat FLOAT DEFAULT 0,
            lon FLOAT DEFAULT 0,
            time TIMESTAMP DEFAULT NOW(),
            inserted_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_mobility_time ON mobility_aggregates(time);
        CREATE INDEX IF NOT EXISTS idx_mobility_h3 ON mobility_aggregates(h3_index);
    """,
    "waste_sensors": """
        CREATE TABLE IF NOT EXISTS waste_sensors (
            id SERIAL PRIMARY KEY,
            station_id VARCHAR(64) NOT NULL,
            fill_level FLOAT NOT NULL,
            ward VARCHAR(64) DEFAULT '',
            lat FLOAT DEFAULT 0,
            lon FLOAT DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            inserted_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_waste_sensors_time ON waste_sensors(updated_at);
    """,
    "sidewalk_counters": """
        CREATE TABLE IF NOT EXISTS sidewalk_counters (
            id SERIAL PRIMARY KEY,
            path_id VARCHAR(64) NOT NULL,
            pedestrian_count FLOAT NOT NULL,
            ward VARCHAR(64) DEFAULT '',
            lat FLOAT DEFAULT 0,
            lon FLOAT DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            inserted_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_sidewalk_counters_time ON sidewalk_counters(updated_at);
    """,
    "lrt_telemetry": """
        CREATE TABLE IF NOT EXISTS lrt_telemetry (
            id SERIAL PRIMARY KEY,
            segment_id VARCHAR(64) NOT NULL,
            train_count FLOAT NOT NULL,
            headway_sec FLOAT NOT NULL,
            ward VARCHAR(64) DEFAULT '',
            lat FLOAT DEFAULT 0,
            lon FLOAT DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            inserted_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_lrt_telemetry_time ON lrt_telemetry(updated_at);
    """,
    "sgr_telemetry": """
        CREATE TABLE IF NOT EXISTS sgr_telemetry (
            id SERIAL PRIMARY KEY,
            segment_id VARCHAR(64) NOT NULL,
            stress_level FLOAT NOT NULL,
            speed_limit FLOAT NOT NULL,
            ward VARCHAR(64) DEFAULT '',
            lat FLOAT DEFAULT 0,
            lon FLOAT DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            inserted_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_sgr_telemetry_time ON sgr_telemetry(updated_at);
    """,
    "airport_telemetry": """
        CREATE TABLE IF NOT EXISTS airport_telemetry (
            id SERIAL PRIMARY KEY,
            runway_id VARCHAR(64) NOT NULL,
            flight_rate FLOAT NOT NULL,
            surface_condition FLOAT NOT NULL,
            ward VARCHAR(64) DEFAULT '',
            lat FLOAT DEFAULT 0,
            lon FLOAT DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            inserted_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_airport_telemetry_time ON airport_telemetry(updated_at);
    """,
}


def create_tables(engine_url: str) -> None:
    """Create all ingestion and monitor tables if they do not exist."""
    from sqlalchemy import text
    engine = create_engine(engine_url)
    inspector = inspect(engine)

    # ORM tables
    orm_tables = [InfrastructureAsset.__tablename__, SensorReading.__tablename__,
                  PopulationDensity.__tablename__, IngestionLog.__tablename__]
    missing_orm = [t for t in orm_tables if not inspector.has_table(t)]
    if missing_orm:
        Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in missing_orm])

    # Monitor tables (raw DDL)
    with engine.begin() as conn:
        for table_name, ddl in _MONITOR_DDL.items():
            if not inspector.has_table(table_name):
                conn.execute(text(ddl))


def get_sessionmaker(engine_url: str):
    """Return a configured sessionmaker bound to engine."""
    engine = create_engine(engine_url)
    return sessionmaker(bind=engine)
