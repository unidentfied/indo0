"""
Sindio — Base Fetcher
=====================
Abstract base class for all external-data fetchers.
Provides: HTTP client with retries, DB session management,
normalized insert logic, and structured logging.
"""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from .models import SensorReading, IngestionLog, get_sessionmaker

logger = logging.getLogger("sindio.ingestion")


class FetcherResult:
    """Outcome of one fetcher run."""
    def __init__(self, fetcher_name: str):
        self.fetcher_name = fetcher_name
        self.records: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self.status = "success"  # success | partial | failed
        self.started_at = datetime.now(timezone.utc)
        self.finished_at: Optional[datetime] = None

    @property
    def duration_ms(self) -> float:
        if self.finished_at is None:
            return 0.0
        return (self.finished_at - self.started_at).total_seconds() * 1000


class BaseFetcher(ABC):
    """Base class for Sindio data fetchers.

    Subclasses must implement:
      - `source_name` (str): human-readable source identifier
      - `infrastructure_type` (str): registry key (power, water, roads, ...)
      - `fetch()` -> List[Dict]: raw records from external API
      - `normalize(raw)` -> Dict: convert raw record to Sindio schema
    """

    source_name: str = "unknown"
    infrastructure_type: str = "unknown"
    default_capacity: float = 100.0
    default_unit: str = ""

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.getenv(
            "DATABASE_URL",
            f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
            f"{os.getenv('DB_PASSWORD', '')}@"
            f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
            f"{os.getenv('DB_NAME', 'sindio')}",
        )
        self._session_factory = get_sessionmaker(self.db_url)

    # ── HTTP helpers ─────────────────────────────────────────────

    def _http_get(self, url: str, headers: Optional[Dict] = None, timeout: float = 30.0) -> Optional[httpx.Response]:
        """GET with 3 retries and exponential backoff."""
        headers = headers or {}
        headers.setdefault("User-Agent", "Sindio/1.0 (+https://sindio.net)")
        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                    resp = client.get(url, headers=headers)
                    resp.raise_for_status()
                    return resp
            except Exception as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning("[%s] GET %s failed (attempt %d/3): %s — retrying in %ds",
                               self.source_name, url, attempt, exc, wait)
                time.sleep(wait)
        logger.error("[%s] GET %s failed permanently: %s", self.source_name, url, last_exc)
        return None

    def _http_post(self, url: str, json_data: Optional[Dict] = None,
                   headers: Optional[Dict] = None, timeout: float = 30.0) -> Optional[httpx.Response]:
        """POST with 3 retries."""
        headers = headers or {}
        headers.setdefault("User-Agent", "Sindio/1.0 (+https://sindio.net)")
        headers.setdefault("Content-Type", "application/json")
        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                    resp = client.post(url, json=json_data, headers=headers)
                    resp.raise_for_status()
                    return resp
            except Exception as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning("[%s] POST %s failed (attempt %d/3): %s — retrying in %ds",
                               self.source_name, url, attempt, exc, wait)
                time.sleep(wait)
        logger.error("[%s] POST %s failed permanently: %s", self.source_name, url, last_exc)
        return None

    # ── DB helpers ──────────────────────────────────────────────

    def _insert_readings(self, records: List[Dict[str, Any]]) -> int:
        """Insert normalized records into sensor_readings. Returns inserted count."""
        if not records:
            return 0
        session: Session = self._session_factory()
        inserted = 0
        try:
            for rec in records:
                reading = SensorReading(
                    asset_id=str(rec.get("asset_id", "unknown")),
                    infrastructure_type=rec.get("infrastructure_type", self.infrastructure_type),
                    value=float(rec.get("value", 0)),
                    capacity=float(rec.get("capacity", self.default_capacity)),
                    unit=str(rec.get("unit", self.default_unit)),
                    timestamp=rec.get("timestamp") or datetime.now(timezone.utc),
                    source=str(rec.get("source", self.source_name)),
                    ward=str(rec.get("ward", "")),
                    lat=float(rec.get("lat", 0)),
                    lon=float(rec.get("lon", 0)),
                    is_mock=bool(rec.get("is_mock", False)),
                    raw_payload=str(rec.get("raw_payload", ""))[:4096],
                )
                session.add(reading)
                inserted += 1
            session.commit()
            logger.info("[%s] Inserted %d readings into sensor_readings",
                        self.source_name, inserted)
        except Exception as exc:
            session.rollback()
            logger.error("[%s] DB insert failed: %s", self.source_name, exc)
            raise
        finally:
            session.close()
        return inserted

    def _log_run(self, result: FetcherResult) -> None:
        """Persist audit log entry."""
        session: Session = self._session_factory()
        try:
            log = IngestionLog(
                fetcher_name=result.fetcher_name,
                status=result.status,
                records_fetched=len(result.records),
                records_inserted=len(result.records) if result.status != "failed" else 0,
                error_message="; ".join(result.errors)[:1024],
                started_at=result.started_at,
                finished_at=result.finished_at or datetime.now(timezone.utc),
            )
            session.add(log)
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning("[%s] Failed to write ingestion log: %s", self.source_name, exc)
        finally:
            session.close()

    # ── Abstract interface ─────────────────────────────────────

    @abstractmethod
    def fetch(self) -> List[Dict[str, Any]]:
        """Fetch raw records from external source. Must be implemented."""
        ...

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Convert raw record to unified schema. Override per source."""
        return {
            "asset_id": str(raw.get("id", raw.get("asset_id", "unknown"))),
            "infrastructure_type": self.infrastructure_type,
            "value": float(raw.get("value", raw.get("reading", 0))),
            "capacity": float(raw.get("capacity", self.default_capacity)),
            "unit": str(raw.get("unit", self.default_unit)),
            "timestamp": raw.get("timestamp") or datetime.now(timezone.utc),
            "source": self.source_name,
            "ward": str(raw.get("ward", "")),
            "lat": float(raw.get("lat", raw.get("latitude", 0))),
            "lon": float(raw.get("lon", raw.get("longitude", 0))),
            "is_mock": False,
            "raw_payload": str(raw)[:4096],
        }

    # ── Public runner ─────────────────────────────────────────────

    def run(self) -> FetcherResult:
        """Execute full fetch → normalize → insert pipeline."""
        result = FetcherResult(self.source_name)
        logger.info("[%s] Starting fetch", self.source_name)
        try:
            raw_records = self.fetch()
            if not raw_records:
                result.status = "partial"
                result.errors.append("No records returned from source")
            else:
                normalized = [self.normalize(r) for r in raw_records]
                result.records = normalized
                inserted = self._insert_readings(normalized)
                if inserted < len(normalized):
                    result.status = "partial"
                    result.errors.append(f"Only {inserted}/{len(normalized)} inserted")
        except Exception as exc:
            result.status = "failed"
            result.errors.append(str(exc))
            logger.exception("[%s] Fetch failed", self.source_name)
        finally:
            result.finished_at = datetime.now(timezone.utc)
            self._log_run(result)
            logger.info("[%s] Run finished: %s in %.0fms — %d records",
                        self.source_name, result.status, result.duration_ms,
                        len(result.records))
        return result
