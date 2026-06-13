"""
Sindio — Unified Real-Time Data Ingestion
==========================================

Ingests data for ANY infrastructure type using the same pipeline.
Tries each configured data source in order, falls back gracefully.
Tracks mock/real ratios for data quality metrics.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .registry import InfraConfig, InfraDataSource

logger = logging.getLogger("sindio.ingestion")


class DataIngestor:
    """Real-time data ingestion for one infrastructure type.

    Tries each configured data source in priority order.
    Falls back to synthetic data when all sources fail.
    """

    def __init__(self, config: InfraConfig, db_url: Optional[str] = None):
        self.config = config
        self.db_url = db_url or os.getenv(
            "DATABASE_URL",
            f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
            f"{os.getenv('DB_PASSWORD', '')}@"
            f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
            f"{os.getenv('DB_NAME', 'sindio')}",
        )
        if ':@' in self.db_url or ':/' in self.db_url.split('@')[0]:
            raise RuntimeError("DB_PASSWORD environment variable is required")
        self._real_count = 0
        self._mock_count = 0

    @property
    def mock_ratio(self) -> float:
        total = self._real_count + self._mock_count
        if total == 0:
            return 1.0
        return self._mock_count / total

    def ingest(self, force_mock: bool = False) -> List[Dict[str, Any]]:
        """Ingest data from all configured sources.

        Args:
            force_mock: skip real sources, use fallback immediately

        Returns:
            List of data point dicts with keys:
                asset_id, value, capacity, timestamp, source, ward, lat, lon, is_mock
        """
        self._real_count = 0
        self._mock_count = 0
        all_points: List[Dict[str, Any]] = []

        if force_mock:
            logger.info("[%s] Forcing mock data", self.config.display_name)
            points = self._generate_fallback()
            all_points.extend(points)
            self._mock_count += len(points)
            return all_points

        # Try each data source in order
        for ds in self.config.data_sources:
            points = self._try_source(ds)
            if points:
                all_points.extend(points)
                self._real_count += len(points)
                logger.info(
                    "[%s] Source '%s' returned %d points",
                    self.config.display_name, ds.source_name, len(points),
                )
                # If we got real data from any source, don't fall back
                return all_points

        # All sources failed — use fallback
        logger.warning(
            "[%s] All data sources failed — using fallback",
            self.config.display_name,
        )
        points = self._generate_fallback()
        all_points.extend(points)
        self._mock_count += len(points)
        return all_points

    def _try_source(self, ds: InfraDataSource) -> List[Dict[str, Any]]:
        """Attempt to fetch data from one source."""
        if ds.query.startswith("SELECT"):
            return self._query_postgres(ds)
        elif ds.query.startswith("http"):
            return self._query_api(ds)
        else:
            return self._query_kafka(ds)

    def _query_postgres(self, ds: InfraDataSource) -> List[Dict[str, Any]]:
        """Execute a SQL query against PostGIS."""
        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(self.db_url)
            with engine.connect() as conn:
                rows = conn.execute(text(ds.query)).fetchall()

            if not rows:
                return []

            id_keys = ("asset_id", "bus_id", "node_id", "h3_index",
                       "station_id", "path_id", "segment_id", "runway_id")
            value_keys = ("value", "load_mw", "pressure_m", "vehicle_count",
                          "fill_level", "pedestrian_count", "train_count",
                          "flight_rate", "stress_level")

            points = []
            for row in rows:
                row_dict = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)

                asset_id = "unknown"
                for k in id_keys:
                    if k in row_dict and row_dict[k] is not None:
                        asset_id = str(row_dict[k])
                        break

                raw_value = 0
                for k in value_keys:
                    if k in row_dict and row_dict[k] is not None:
                        raw_value = float(row_dict[k])
                        break

                capacity = float(row_dict.get("capacity", self.config.default_capacity))
                ts = row_dict.get("updated_at", row_dict.get("time"))
                if ts is None:
                    ts = datetime.now(timezone.utc).isoformat()

                points.append({
                    "asset_id": asset_id,
                    "value": raw_value,
                    "capacity": capacity,
                    "timestamp": str(ts),
                    "source": ds.source_name,
                    "ward": str(row_dict.get("ward", "")),
                    "lat": float(row_dict.get("lat", 0)),
                    "lon": float(row_dict.get("lon", 0)),
                    "is_mock": False,
                })
            return points

        except Exception as exc:
            logger.debug("[%s] Postgres query failed: %s", self.config.display_name, exc)
            return []

    def _query_api(self, ds: InfraDataSource) -> List[Dict[str, Any]]:
        """Fetch data from an HTTP API."""
        try:
            import httpx

            resp = httpx.get(ds.query, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            # Handle various response formats
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("results", data.get("data", data.get("assets", [data])))
            else:
                return []

            points = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                points.append({
                    "asset_id": str(item.get("id", item.get("asset_id", "unknown"))),
                    "value": float(item.get("value", item.get("reading", item.get("measurement", 0)))),
                    "capacity": float(item.get("capacity", self.config.default_capacity)),
                    "timestamp": str(item.get("timestamp", item.get("time", datetime.now(timezone.utc).isoformat()))),
                    "source": ds.source_name,
                    "ward": str(item.get("ward", "")),
                    "lat": float(item.get("lat", item.get("latitude", 0))),
                    "lon": float(item.get("lon", item.get("longitude", 0))),
                    "is_mock": False,
                })
            return points

        except Exception as exc:
            logger.debug("[%s] API query failed: %s", self.config.display_name, exc)
            return []

    def _query_kafka(self, ds: InfraDataSource) -> List[Dict[str, Any]]:
        """Consume messages from a Kafka topic."""
        try:
            try:
                from confluent_kafka import Consumer
            except ImportError:
                try:
                    from rdkafka import Consumer
                except ImportError:
                    logger.debug("[%s] No Kafka client installed", self.config.display_name)
                    return []

            conf = {
                "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "localhost:9092"),
                "group.id": f"sindio-{self.config.name}-ingestor",
                "auto.offset.reset": "latest",
            }
            consumer = Consumer(conf)
            consumer.subscribe([ds.query])

            points = []
            msg = consumer.poll(timeout=5.0)
            if msg and not msg.error():
                import json
                data = json.loads(msg.value().decode("utf-8"))
                points.append({
                    "asset_id": str(data.get("asset_id", "unknown")),
                    "value": float(data.get("value", 0)),
                    "capacity": float(data.get("capacity", self.config.default_capacity)),
                    "timestamp": str(data.get("timestamp", datetime.now(timezone.utc).isoformat())),
                    "source": ds.source_name,
                    "ward": str(data.get("ward", "")),
                    "lat": float(data.get("lat", 0)),
                    "lon": float(data.get("lon", 0)),
                    "is_mock": False,
                })

            consumer.close()
            return points

        except Exception as exc:
            logger.debug("[%s] Kafka query failed: %s", self.config.display_name, exc)
            return []

    def _generate_fallback(self) -> List[Dict[str, Any]]:
        """Generate synthetic fallback data based on config."""
        import numpy as np

        rng = np.random.RandomState(
            hash(f"{self.config.name}-{datetime.now(timezone.utc).date()}") % (2 ** 31)
        )

        wards = ["Central", "Kilimani", "Westlands", "Kibera", "Embakasi",
                 "Kasarani", "Dagoretti", "Kamukunji", "Starehe", "Mathare"]

        points = []
        count = self.config.default_asset_count
        base = self.config.heuristic_base_stress
        var = self.config.heuristic_variance

        for i in range(count):
            stress = float(np.clip(base + rng.normal(0, var), 0.0, 1.0))
            value = stress * self.config.default_capacity

            points.append({
                "asset_id": f"{self.config.name}_asset_{i:05d}",
                "value": round(value, 4),
                "capacity": self.config.default_capacity,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "fallback",
                "ward": wards[i % len(wards)],
                "lat": round(-1.29 + rng.uniform(-0.05, 0.05), 6),
                "lon": round(36.82 + rng.uniform(-0.05, 0.05), 6),
                "is_mock": True,
            })

        return points
