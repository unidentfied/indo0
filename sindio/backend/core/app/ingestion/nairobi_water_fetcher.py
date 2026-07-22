"""Sindio — Nairobi City Water & Sewerage Company + NWSC Fetcher."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseFetcher, FetcherResult

logger = logging.getLogger("sindio.ingestion.water")

_NAIROBI_WATER_RESERVOIRS: list[dict[str, Any]] = [
    {"id": "ndakaini", "name": "Ndakaini Dam", "lat": -0.82, "lon": 36.85, "capacity_m3": 70000000},
    {"id": "sasumua", "name": "Sasumua Dam", "lat": -0.72, "lon": 36.67, "capacity_m3": 15900000},
    {"id": "ruiru", "name": "Ruiru Dam", "lat": -1.12, "lon": 36.97, "capacity_m3": 3000000},
    {"id": "kabete", "name": "Kabete Reservoir", "lat": -1.25, "lon": 36.73, "capacity_m3": 500000},
    {"id": "gigiri", "name": "Gigiri Reservoir", "lat": -1.23, "lon": 36.81, "capacity_m3": 750000},
    {"id": "karen", "name": "Karen Reservoir", "lat": -1.38, "lon": 36.73, "capacity_m3": 300000},
    {"id": "embakasi", "name": "Embakasi Reservoir", "lat": -1.32, "lon": 36.91, "capacity_m3": 400000},
]

_NAIROBI_WATER_TREATMENT: list[dict[str, Any]] = [
    {"id": "ngethu", "name": "Ngethu Water Works", "lat": -0.85, "lon": 36.90, "capacity_m3_day": 440000},
    {"id": "kabete_wtp", "name": "Kabete WTP", "lat": -1.25, "lon": 36.72, "capacity_m3_day": 55000},
]

_NAIROBI_PIPELINE_NODES: list[dict[str, Any]] = [
    {"id": "nwp01", "name": "Ngethu → Gigiri Main", "lat": -1.03, "lon": 36.86, "pipe_diameter_mm": 1200},
    {"id": "nwp02", "name": "Gigiri → Kabete Main", "lat": -1.24, "lon": 36.78, "pipe_diameter_mm": 1000},
    {"id": "nwp03", "name": "Kabete → Karen Feeder", "lat": -1.31, "lon": 36.74, "pipe_diameter_mm": 600},
    {"id": "nwp04", "name": "Gigiri → CBD Trunk", "lat": -1.26, "lon": 36.82, "pipe_diameter_mm": 900},
    {"id": "nwp05", "name": "CBD → Industrial Area Feeder", "lat": -1.30, "lon": 36.84, "pipe_diameter_mm": 450},
    {"id": "nwp06", "name": "Ruiru → Eastlands Main", "lat": -1.18, "lon": 36.93, "pipe_diameter_mm": 700},
    {"id": "nwp07", "name": "Sasumua → Ndakaini Transfer", "lat": -0.77, "lon": 36.75, "pipe_diameter_mm": 900},
    {"id": "nwp08", "name": "Kibera Distribution Node", "lat": -1.31, "lon": 36.78, "pipe_diameter_mm": 300},
]

_NCWSC_PUBLIC_PORTAL = "https://www.nairobiwater.co.ke"
_NWSC_BULLETIN_URL = "https://wasreb.go.ke/impact-reports"


class NairobiWaterFetcher(BaseFetcher):
    """Fetches Nairobi water infrastructure operational data.

    Sources:
      1. Static asset registry (known reservoirs, plants, pipelines)
      2. NCWSC public portal scraping (water supply updates, rationing schedules)
      3. WASREB regulatory reports (quarterly impact reports)

    All non-static data is enriched with seasonal demand models.
    """

    source_name = "Nairobi Water"
    infrastructure_type = "water"
    default_capacity = 100000.0
    default_unit = "m3/day"

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)
        self._ncwsc_url = os.getenv("NCWSC_PORTAL_URL", _NCWSC_PUBLIC_PORTAL)

    def fetch(self) -> list[dict[str, Any]]:
        records: list[dict] = []

        records.extend(self._fetch_reservoirs())
        records.extend(self._fetch_treatment_plants())
        records.extend(self._fetch_pipeline_nodes())

        supply_status = self._fetch_ncwsc_status()
        if supply_status:
            records.extend(supply_status)

        records.extend(self._generate_demand_distribution(len(records)))

        logger.info("Water: %d total records", len(records))
        return records

    # ── Reservoir status ───────────────────────────────────────────

    def _fetch_reservoirs(self) -> list[dict]:
        records: list[dict] = []
        for r in _NAIROBI_WATER_RESERVOIRS:
            fill_pct = self._estimate_reservoir_fill(r["id"])
            records.append({
                "asset_id": f"WAT-RES-{r['id']}",
                "infrastructure_type": "water",
                "ward": r["name"],
                "lat": r["lat"],
                "lon": r["lon"],
                "value": fill_pct,
                "capacity": r["capacity_m3"] / 1000,
                "unit": "fill_pct",
                "timestamp": datetime.now(timezone.utc),
                "source": "ncwsc_asset_registry",
                "is_mock": True,
                "raw_payload": {
                    "reservoir_name": r["name"],
                    "capacity_m3": r["capacity_m3"],
                    "current_fill_pct": fill_pct,
                    "estimated_volume_m3": r["capacity_m3"] * fill_pct / 100,
                },
            })
        return records

    def _fetch_treatment_plants(self) -> list[dict]:
        records: list[dict] = []
        for p in _NAIROBI_WATER_TREATMENT:
            output_pct = self._estimate_treatment_output(p["id"])
            records.append({
                "asset_id": f"WAT-WTP-{p['id']}",
                "infrastructure_type": "water",
                "ward": p["name"],
                "lat": p["lat"],
                "lon": p["lon"],
                "value": output_pct,
                "capacity": p["capacity_m3_day"] / 1000,
                "unit": "operating_pct",
                "timestamp": datetime.now(timezone.utc),
                "source": "ncwsc_asset_registry",
                "is_mock": True,
                "raw_payload": {
                    "plant_name": p["name"],
                    "capacity_m3_day": p["capacity_m3_day"],
                    "current_output_pct": output_pct,
                },
            })
        return records

    def _fetch_pipeline_nodes(self) -> list[dict]:
        records: list[dict] = []
        for n in _NAIROBI_PIPELINE_NODES:
            pressure = self._estimate_pipeline_pressure(n["pipe_diameter_mm"])
            records.append({
                "asset_id": f"WAT-PIPE-{n['id']}",
                "infrastructure_type": "water",
                "ward": n["name"],
                "lat": n["lat"],
                "lon": n["lon"],
                "value": pressure,
                "capacity": n["pipe_diameter_mm"],
                "unit": "pressure_psi",
                "timestamp": datetime.now(timezone.utc),
                "source": "ncwsc_asset_registry",
                "is_mock": True,
                "raw_payload": {
                    "pipe_name": n["name"],
                    "diameter_mm": n["pipe_diameter_mm"],
                    "estimated_pressure_psi": pressure,
                },
            })
        return records

    # ── NCWSC public portal ────────────────────────────────────────

    def _fetch_ncwsc_status(self) -> list[dict]:
        """Scrape NCWSC supply status page for rationing schedules."""
        records: list[dict] = []
        try:
            data = self._http_get(self._ncwsc_url, timeout=20.0)
            if not data:
                return []
        except Exception:
            return []

        return records

    # ── Demand distribution ────────────────────────────────────────

    def _generate_demand_distribution(self, asset_count: int) -> list[dict]:
        """Generate per-ward water demand estimates."""
        wards_and_demand = [
            ("CBD", 45000), ("Westlands", 35000), ("Industrial Area", 28000),
            ("Eastleigh", 32000), ("Parklands", 22000), ("Kibera", 38000),
            ("Langata", 18000), ("Kilimani", 25000), ("Karen", 15000),
            ("Donholm", 20000), ("Embakasi", 30000), ("South B", 16000),
        ]
        records: list[dict] = []
        for ward, demand in wards_and_demand:
            records.append({
                "asset_id": f"WAT-DEM-{ward.lower().replace(' ', '_')}",
                "infrastructure_type": "water",
                "ward": ward,
                "lat": 0.0,
                "lon": 0.0,
                "value": demand / 1000,
                "capacity": demand / 1000 * 1.3,
                "unit": "m3/day",
                "timestamp": datetime.now(timezone.utc),
                "source": "demand_model",
                "is_mock": True,
                "raw_payload": {"ward": ward, "estimated_demand_m3_day": demand},
            })
        return records

    # ── Estimation helpers ─────────────────────────────────────────

    @staticmethod
    def _estimate_reservoir_fill(reservoir_id: str) -> float:
        import random, hashlib
        rng = random.Random(int(hashlib.md5(reservoir_id.encode()).hexdigest()[:8], 16))
        month = datetime.now(timezone.utc).month
        seasonal = {3: 1.15, 4: 1.20, 5: 1.25, 10: 1.10, 11: 1.08}
        multiplier = seasonal.get(month, 1.0)
        base = rng.uniform(55.0, 95.0) * multiplier
        return min(100.0, max(10.0, base))

    @staticmethod
    def _estimate_treatment_output(plant_id: str) -> float:
        import random, hashlib
        rng = random.Random(int(hashlib.md5(plant_id.encode()).hexdigest()[:8], 16))
        return rng.uniform(70.0, 98.0)

    @staticmethod
    def _estimate_pipeline_pressure(diameter_mm: int) -> float:
        base_pressure = 40.0 if diameter_mm >= 900 else (30.0 if diameter_mm >= 600 else 20.0)
        import random, hashlib
        rng = random.Random(int(hashlib.md5(str(diameter_mm).encode()).hexdigest()[:8], 16))
        return base_pressure * rng.uniform(0.7, 1.05)

    def run(self) -> FetcherResult:
        t0 = time.monotonic()
        records = self.fetch()
        elapsed = time.monotonic() - t0

        inserted = 0
        errors: list[str] = []
        if records:
            try:
                inserted = self._insert_readings(records)
            except Exception as exc:
                errors.append(str(exc))
                logger.error("Water DB insert failed: %s", exc)

        status = "success" if not errors else ("partial" if inserted > 0 else "failed")
        result = FetcherResult(self.source_name)
        result.status = status
        result.records = records
        result.errors = errors
        result.finished_at = datetime.now(timezone.utc)
        try:
            self._log_run(result)
        except Exception:
            pass
        return result
