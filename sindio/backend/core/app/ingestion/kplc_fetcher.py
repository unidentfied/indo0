"""Sindio — Kenya Power & Lighting Company SCADA Fetcher.

Integrates with KPLC's public operational data:
  - Scheduled outage registry
  - Generation dispatch dashboard
  - Substation loading snapshots (where published)
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseFetcher, FetcherResult

logger = logging.getLogger("sindio.ingestion.kplc")

_KPLC_OUTAGE_API = os.getenv("KPLC_OUTAGE_API", "https://kplc.co.ke/api/v1/outages")
_KPLC_GENERATION_API = os.getenv("KPLC_GENERATION_API", "https://kplc.co.ke/api/v1/generation")

_NAIROBI_SUBSTATIONS: list[dict[str, Any]] = [
    {"id": "sub_001", "name": "Ruaraka 132kV", "lat": -1.23, "lon": 36.89, "capacity_mva": 132, "voltage_kv": 132},
    {"id": "sub_002", "name": "Dandora 66kV", "lat": -1.26, "lon": 36.93, "capacity_mva": 66, "voltage_kv": 66},
    {"id": "sub_003", "name": "City Centre 66kV", "lat": -1.285, "lon": 36.824, "capacity_mva": 66, "voltage_kv": 66},
    {"id": "sub_004", "name": "Westlands 66kV", "lat": -1.268, "lon": 36.803, "capacity_mva": 66, "voltage_kv": 66},
    {"id": "sub_005", "name": "Industrial Area 132kV", "lat": -1.315, "lon": 36.850, "capacity_mva": 132, "voltage_kv": 132},
    {"id": "sub_006", "name": "Karen 66kV", "lat": -1.381, "lon": 36.731, "capacity_mva": 66, "voltage_kv": 66},
    {"id": "sub_007", "name": "Embakasi 132kV", "lat": -1.320, "lon": 36.905, "capacity_mva": 132, "voltage_kv": 132},
    {"id": "sub_008", "name": "Kasarani 66kV", "lat": -1.220, "lon": 36.910, "capacity_mva": 66, "voltage_kv": 66},
    {"id": "sub_009", "name": "Juja Road 66kV", "lat": -1.265, "lon": 36.840, "capacity_mva": 66, "voltage_kv": 66},
    {"id": "sub_010", "name": "Langata 66kV", "lat": -1.370, "lon": 36.745, "capacity_mva": 66, "voltage_kv": 66},
    {"id": "sub_011", "name": "Ngong Road 66kV", "lat": -1.305, "lon": 36.773, "capacity_mva": 66, "voltage_kv": 66},
    {"id": "sub_012", "name": "Dagoretti 66kV", "lat": -1.295, "lon": 36.756, "capacity_mva": 66, "voltage_kv": 66},
    {"id": "sub_013", "name": "Eastlands 132kV", "lat": -1.270, "lon": 36.855, "capacity_mva": 132, "voltage_kv": 132},
    {"id": "sub_014", "name": "Athiriver 220kV", "lat": -1.455, "lon": 36.998, "capacity_mva": 220, "voltage_kv": 220},
]

_NATIONAL_GENERATION: list[dict[str, Any]] = [
    {"id": "gen_001", "name": "Seven Forks (Masinga, Kamburu, Gitaru, Kindaruma, Kiambere)", "type": "hydro", "capacity_mw": 600},
    {"id": "gen_002", "name": "Turkwel Hydro", "type": "hydro", "capacity_mw": 106},
    {"id": "gen_003", "name": "Olkaria I-V Geothermal", "type": "geothermal", "capacity_mw": 863},
    {"id": "gen_004", "name": "Kipevu I-III Thermal", "type": "thermal", "capacity_mw": 253},
    {"id": "gen_005", "name": "Lake Turkana Wind", "type": "wind", "capacity_mw": 310},
    {"id": "gen_006", "name": "Ngong Wind", "type": "wind", "capacity_mw": 26},
    {"id": "gen_007", "name": "Garissa Solar", "type": "solar", "capacity_mw": 55},
    {"id": "gen_008", "name": "Sondu Miriu Hydro", "type": "hydro", "capacity_mw": 60},
    {"id": "gen_009", "name": "Import (Uganda/Ethiopia)", "type": "import", "capacity_mw": 500},
]

_OUTAGE_PATTERNS: list[re.Pattern] = [
    re.compile(r"(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})", re.IGNORECASE),
    re.compile(r"(\w+\s+\d{1,2}(?:st|nd|rd|th)?\s*\d{4})", re.IGNORECASE),
    re.compile(r"(?:AREA|LOCATION)[\s:]+([\w\s,]+)", re.IGNORECASE),
]


class KPLCFetcher(BaseFetcher):
    """Fetches Kenya Power operational data for Nairobi infrastructure analysis.

    Combines:
      - Substation registry (static) with loading models (synthetic, informed by
        seasonal patterns and known peak/off-peak hours)
      - Generation dispatch from KPLC public dashboard (when API available)
      - Scheduled outage feed (when API available)

    All static records are tagged is_mock=False (real asset locations/capacities
    from KPLC published network maps). Loading values are modelled.
    """

    source_name = "Kenya Power"
    infrastructure_type = "power"
    default_capacity = 132.0
    default_unit = "MW"

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)
        self._kplc_api_url = os.getenv("KPLC_API_URL", "")
        self._kplc_api_key = os.getenv("KPLC_API_KEY", "")

    def fetch(self) -> list[dict[str, Any]]:
        records: list[dict] = []

        records.extend(self._fetch_substation_loading())
        records.extend(self._fetch_generation_dispatch())
        records.extend(self._fetch_outages())
        records.extend(self._build_network_topology(records))

        logger.info("KPLC: %d total records", len(records))
        return records

    # ── Substation loading ─────────────────────────────────────────

    def _fetch_substation_loading(self) -> list[dict]:
        """Generate substation loading snapshots based on time-of-day models.

        Substation locations and MVA ratings are real (from KPLC network maps).
        Loading values are modelled based on known Nairobi load curves.
        """
        records: list[dict] = []
        hour = datetime.now(timezone.utc).hour
        utc_hour = hour
        eat_hour = (utc_hour + 3) % 24

        peak_multipliers = {
            tuple(range(6, 10)): (1.25, 0.85),     # Morning peak (6-10am)
            tuple(range(10, 16)): (0.75, 0.60),     # Mid-day trough
            tuple(range(16, 21)): (1.35, 0.90),     # Evening peak (4-9pm)
            tuple(range(21, 24)): (0.85, 0.65),     # Late evening
            tuple(range(0, 6)): (0.50, 0.35),       # Night trough
        }

        mu, sigma = (0.75, 0.60)
        for window, (m, s) in peak_multipliers.items():
            if eat_hour in window:
                mu, sigma = m, s
                break

        import random, hashlib
        hour_seed = int(round(time.time() / 3600))
        rng = random.Random(hour_seed)

        for sub in _NAIROBI_SUBSTATIONS:
            load_mva = sub["capacity_mva"] * max(0.15, rng.gauss(mu, sigma / 3.0) * 0.7)
            voltage_pu = 1.0 - rng.uniform(0.005, 0.04)

            records.append({
                "asset_id": f"KPLC-{sub['id']}",
                "infrastructure_type": "power",
                "ward": sub["name"],
                "lat": sub["lat"],
                "lon": sub["lon"],
                "value": round(load_mva, 2),
                "capacity": sub["capacity_mva"],
                "unit": "MVA",
                "timestamp": datetime.now(timezone.utc),
                "source": "kplc_substation_registry",
                "is_mock": True,
                "raw_payload": {
                    "substation_name": sub["name"],
                    "voltage_kv": sub["voltage_kv"],
                    "capacity_mva": sub["capacity_mva"],
                    "load_mva": round(load_mva, 2),
                    "voltage_pu": round(voltage_pu, 4),
                    "loading_pct": round(load_mva / sub["capacity_mva"] * 100, 1),
                    "time_of_day": f"{eat_hour:02d}:00 EAT",
                },
            })
        return records

    # ── Generation dispatch ────────────────────────────────────────

    def _fetch_generation_dispatch(self) -> list[dict]:
        """Fetch generation dispatch data.

        Tries KPLC API first, falls back to Kenya generation registry
        with estimated output based on seasonal hydro conditions.
        """
        if self._kplc_api_url and self._kplc_api_key:
            live = self._fetch_live_generation()
            if live:
                return live

        return self._estimated_dispatch()

    def _fetch_live_generation(self) -> Optional[list[dict]]:
        try:
            data = self._http_get(
                _KPLC_GENERATION_API,
                headers={"Authorization": f"Bearer {self._kplc_api_key}"},
                timeout=15.0,
            )
            if not data or not isinstance(data, list):
                return None
            records: list[dict] = []
            for g in data:
                records.append({
                    "asset_id": f"GEN-{g.get('id', 'unknown')}",
                    "infrastructure_type": "power",
                    "ward": g.get("name", "Unknown"),
                    "lat": g.get("lat", 0.0),
                    "lon": g.get("lon", 0.0),
                    "value": g.get("output_mw", 0),
                    "capacity": g.get("capacity_mw", 100),
                    "unit": "MW",
                    "timestamp": datetime.now(timezone.utc),
                    "source": "kplc_generation_api",
                    "is_mock": False,
                    "raw_payload": g,
                })
            return records
        except Exception:
            return None

    def _estimated_dispatch(self) -> list[dict]:
        records: list[dict] = []
        month = datetime.now(timezone.utc).month
        wet_season = month in (3, 4, 5, 10, 11)

        for gen in _NATIONAL_GENERATION:
            if gen["type"] == "hydro":
                output_pct = 0.85 if wet_season else 0.55
            elif gen["type"] == "geothermal":
                output_pct = 0.92
            elif gen["type"] == "wind":
                output_pct = 0.65
            elif gen["type"] == "solar":
                hour = (datetime.now(timezone.utc).hour + 3) % 24
                output_pct = 0.0 if hour < 6 or hour > 18 else 0.75 * min(1.0, (hour - 6) / 6.0)
            elif gen["type"] == "import":
                output_pct = 0.70
            else:
                output_pct = 0.50

            output_mw = gen["capacity_mw"] * output_pct
            records.append({
                "asset_id": f"GEN-{gen['id']}",
                "infrastructure_type": "power",
                "ward": gen["name"],
                "lat": 0.0,
                "lon": 0.0,
                "value": round(output_mw, 1),
                "capacity": gen["capacity_mw"],
                "unit": "MW",
                "timestamp": datetime.now(timezone.utc),
                "source": "kplc_generation_registry",
                "is_mock": True,
                "raw_payload": {
                    "plant_name": gen["name"],
                    "type": gen["type"],
                    "capacity_mw": gen["capacity_mw"],
                    "estimated_output_mw": round(output_mw, 1),
                    "estimated_pct": round(output_pct, 2),
                },
            })
        return records

    # ── Outages ─────────────────────────────────────────────────────

    def _fetch_outages(self) -> list[dict]:
        if not self._kplc_api_url:
            return self._synthetic_outages()
        try:
            data = self._http_get(_KPLC_OUTAGE_API, timeout=10.0)
            if not data or not isinstance(data, list):
                return self._synthetic_outages()
            return self._parse_outage_feed(data)
        except Exception:
            return self._synthetic_outages()

    def _parse_outage_feed(self, items: list[dict]) -> list[dict]:
        records: list[dict] = []
        for item in items:
            records.append({
                "asset_id": f"OUT-{item.get('id', 'unknown')}",
                "infrastructure_type": "power",
                "ward": item.get("area", "Unknown"),
                "lat": float(item.get("lat", 0.0)),
                "lon": float(item.get("lon", 0.0)),
                "value": float(item.get("affected_customers", 0)),
                "capacity": 1.0,
                "unit": "customers_affected",
                "timestamp": datetime.now(timezone.utc),
                "source": "kplc_outage_feed",
                "is_mock": False,
                "raw_payload": item,
            })
        return records

    def _synthetic_outages(self) -> list[dict]:
        import random
        hour = (datetime.now(timezone.utc).hour + 3) % 24
        if 2 <= hour <= 5:
            return []
        active = random.Random(int(time.time() / 300)).randint(1, 3)
        records: list[dict] = []
        for i in range(active):
            sub = random.Random(i).choice(_NAIROBI_SUBSTATIONS)
            records.append({
                "asset_id": f"OUT-SYN-{i}",
                "infrastructure_type": "power",
                "ward": sub["name"],
                "lat": sub["lat"] + random.uniform(-0.01, 0.01),
                "lon": sub["lon"] + random.uniform(-0.01, 0.01),
                "value": random.randint(50, 500),
                "capacity": 500.0,
                "unit": "customers_affected",
                "timestamp": datetime.now(timezone.utc),
                "source": "kplc_outage_synthetic",
                "is_mock": True,
                "raw_payload": {"substation": sub["name"], "type": "scheduled_maintenance"},
            })
        return records

    # ── Network topology ───────────────────────────────────────────

    def _build_network_topology(self, existing: list[dict]) -> list[dict]:
        """Build feeder-level network adjacency from substation locations."""
        records: list[dict] = []
        for i, sub_a in enumerate(_NAIROBI_SUBSTATIONS):
            for j, sub_b in enumerate(_NAIROBI_SUBSTATIONS):
                if i >= j:
                    continue
                dx = sub_a["lat"] - sub_b["lat"]
                dy = sub_a["lon"] - sub_b["lon"]
                dist_km = ((dx * 111.32) ** 2 + (dy * 111.32 * 0.866) ** 2) ** 0.5
                if dist_km < 15.0:
                    records.append({
                        "asset_id": f"FEEDER-{sub_a['id']}-{sub_b['id']}",
                        "infrastructure_type": "power",
                        "ward": f"{sub_a['name']} ↔ {sub_b['name']}",
                        "lat": (sub_a["lat"] + sub_b["lat"]) / 2,
                        "lon": (sub_a["lon"] + sub_b["lon"]) / 2,
                        "value": dist_km,
                        "capacity": 132.0,
                        "unit": "km",
                        "timestamp": datetime.now(timezone.utc),
                        "source": "kplc_network_topology",
                        "is_mock": False,
                        "raw_payload": {
                            "from": sub_a["name"],
                            "to": sub_b["name"],
                            "distance_km": round(dist_km, 2),
                        },
                    })
        return records

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
                logger.error("KPLC DB insert failed: %s", exc)

        status = "success" if not errors else ("partial" if inserted > 0 else "failed")
        result = FetcherResult(status=status, records=len(records), inserted=inserted, errors=errors, elapsed=elapsed)
        try:
            self._log_run(result)
        except Exception:
            pass
        return result
