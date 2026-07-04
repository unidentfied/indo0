"""Sindio — Nairobi Waste Collection Fetcher.

Nairobi generates ~2,500 tons of solid waste daily. Collection is managed by:
  1. Nairobi County Environment Department
  2. Private collectors (TakaTaka Solutions, Bins, etc.)
  3. Community-based organizations

Data sources:
  - Nairobi County waste management reports (published)
  - World Bank / UN-Habitat solid waste management studies
  - JICA Nairobi Integrated Solid Waste Management Master Plan
  - Waste collection route schedules (from NMS/County)

No public API exists. Data is derived from published reports + modeled
based on ward population and known collection coverage rates.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..base import BaseFetcher, FetcherResult

logger = logging.getLogger("sindio.ingestion.nairobi_waste")

# Nairobi ward waste generation profiles (tons/day)
# Based on population × 0.6 kg/person/day (Nairobi average)
_WARD_WASTE_PROFILES: list[dict[str, Any]] = [
    {"name": "CBD", "population": 65000, "waste_tons_day": 39, "collection_rate": 0.85, "landfill_dist_km": 18},
    {"name": "Westlands", "population": 72000, "waste_tons_day": 43, "collection_rate": 0.80, "landfill_dist_km": 15},
    {"name": "Industrial_Area", "population": 28000, "waste_tons_day": 67, "collection_rate": 0.70, "landfill_dist_km": 12},
    {"name": "Eastleigh", "population": 95000, "waste_tons_day": 57, "collection_rate": 0.65, "landfill_dist_km": 16},
    {"name": "Karen", "population": 42000, "waste_tons_day": 25, "collection_rate": 0.75, "landfill_dist_km": 22},
    {"name": "Kibera", "population": 185000, "waste_tons_day": 111, "collection_rate": 0.40, "landfill_dist_km": 14},
    {"name": "Embakasi", "population": 125000, "waste_tons_day": 75, "collection_rate": 0.60, "landfill_dist_km": 20},
    {"name": "Kasarani", "population": 92000, "waste_tons_day": 55, "collection_rate": 0.70, "landfill_dist_km": 14},
    {"name": "Ruaraka", "population": 78000, "waste_tons_day": 47, "collection_rate": 0.68, "landfill_dist_km": 13},
    {"name": "Langata", "population": 58000, "waste_tons_day": 35, "collection_rate": 0.72, "landfill_dist_km": 20},
    {"name": "Kilimani", "population": 52000, "waste_tons_day": 31, "collection_rate": 0.82, "landfill_dist_km": 16},
    {"name": "Parklands", "population": 45000, "waste_tons_day": 27, "collection_rate": 0.78, "landfill_dist_km": 14},
    {"name": "South B", "population": 62000, "waste_tons_day": 37, "collection_rate": 0.62, "landfill_dist_km": 15},
    {"name": "South C", "population": 55000, "waste_tons_day": 33, "collection_rate": 0.65, "landfill_dist_km": 14},
    {"name": "Donholm", "population": 48000, "waste_tons_day": 29, "collection_rate": 0.58, "landfill_dist_km": 12},
    {"name": "Mathare", "population": 160000, "waste_tons_day": 96, "collection_rate": 0.35, "landfill_dist_km": 10},
]

# Dandora landfill (main Nairobi landfill)
_DANDORA_LANDFILL = {"lat": -1.256, "lon": 36.903, "capacity_tons": 3000, "daily_inflow": 1800}


class NairobiWasteFetcher(BaseFetcher):
    """Fetches Nairobi solid waste management data.

    Sources:
      1. Nairobi County waste reports (modeled from published statistics)
      2. JICA/World Bank studies on collection coverage
      3. Private sector collection data (where available)

    Primary indicators:
      - Waste generation (tons/day per ward)
      - Collection coverage rate (%)
      - Landfill capacity stress
      - Route efficiency (distance to landfill)
    """

    source_name = "Nairobi Waste"
    infrastructure_type = "solid_waste"
    default_capacity = 100.0
    default_unit = "tons_day"

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)

    def fetch(self) -> list[dict[str, Any]]:
        records: list[dict] = []

        # Ward-level waste metrics
        for ward in _WARD_WASTE_PROFILES:
            records.extend(self._generate_ward_metrics(ward))

        # Landfill-level summary
        records.append(self._generate_landfill_metric())

        logger.info("Waste: %d records", len(records))
        return records

    def _generate_ward_metrics(self, ward: dict) -> list[dict]:
        records: list[dict] = []

        # Collection stress = uncollected waste / total waste
        uncollected = ward["waste_tons_day"] * (1 - ward["collection_rate"])
        collection_stress = min(100, (uncollected / ward["waste_tons_day"]) * 100)

        # Distance stress (longer routes = lower efficiency)
        distance_stress = min(100, ward["landfill_dist_km"] * 3)

        # Combined stress index
        combined_stress = (collection_stress * 0.7) + (distance_stress * 0.3)

        records.append({
            "asset_id": f"WST-WARD-{ward['name'].replace(' ', '_')}",
            "infrastructure_type": "solid_waste",
            "ward": ward["name"],
            "lat": 0.0,
            "lon": 0.0,
            "value": round(combined_stress, 1),
            "capacity": 100.0,
            "unit": "stress_index",
            "timestamp": datetime.now(timezone.utc),
            "source": "nairobi_waste_model",
            "is_mock": True,
            "raw_payload": {
                "population": ward["population"],
                "waste_generation_tons_day": ward["waste_tons_day"],
                "collection_rate_pct": round(ward["collection_rate"] * 100, 1),
                "uncollected_tons_day": round(uncollected, 1),
                "landfill_distance_km": ward["landfill_dist_km"],
                "collection_stress": round(collection_stress, 1),
                "distance_stress": round(distance_stress, 1),
            },
        })

        # Also record pure generation tonnage
        records.append({
            "asset_id": f"WST-GEN-{ward['name'].replace(' ', '_')}",
            "infrastructure_type": "solid_waste",
            "ward": ward["name"],
            "lat": 0.0,
            "lon": 0.0,
            "value": ward["waste_tons_day"],
            "capacity": ward["waste_tons_day"] * 1.5,
            "unit": "tons_day",
            "timestamp": datetime.now(timezone.utc),
            "source": "nairobi_waste_model",
            "is_mock": True,
            "raw_payload": {
                "population": ward["population"],
                "per_capita_kg_day": 0.6,
            },
        })

        return records

    def _generate_landfill_metric(self) -> dict:
        landfill = _DANDORA_LANDFILL
        capacity_stress = (landfill["daily_inflow"] / landfill["capacity_tons"]) * 100

        return {
            "asset_id": "WST-LANDFILL-DANDORA",
            "infrastructure_type": "solid_waste",
            "ward": "Dandora",
            "lat": landfill["lat"],
            "lon": landfill["lon"],
            "value": round(capacity_stress, 1),
            "capacity": 100.0,
            "unit": "capacity_stress_pct",
            "timestamp": datetime.now(timezone.utc),
            "source": "nairobi_landfill_model",
            "is_mock": True,
            "raw_payload": {
                "landfill_name": "Dandora",
                "daily_capacity_tons": landfill["capacity_tons"],
                "daily_inflow_tons": landfill["daily_inflow"],
                "remaining_life_years": 3.5,  # Published estimate
            },
        }

    def run(self) -> FetcherResult:
        t0 = time.monotonic()
        records = self.fetch()
        elapsed = time.monotonic() - t0

        result = FetcherResult(self.source_name)
        result.status = "success"
        result.records = records
        result.finished_at = datetime.now(timezone.utc)

        if records:
            try:
                self._insert_readings(records)
            except Exception as exc:
                result.status = "partial"
                result.errors.append(str(exc))

        try:
            self._log_run(result)
        except Exception:
            pass
        return result
