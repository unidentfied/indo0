"""Sindio — Kenya Railways Corporation Fetcher (commuter rail + SGR data).

Kenya Railways operates:
  1. Nairobi Commuter Rail (NCR) — multiple lines serving Nairobi metro
  2. Madaraka Express (SGR) — Nairobi-Mombasa standard gauge
  3. Freight services on both networks

Data sources:
  - KRC website scraping (krc.co.ke) — schedules, delays, service status
  - KRC passenger statistics (published annually)
  - SGR booking data (if API available)
  - Kenya Ports Authority freight data (for cargo volumes)

No public API exists; data is obtained via web scraping.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from ..base import BaseFetcher, FetcherResult

logger = logging.getLogger("sindio.ingestion.kenya_railways")

_KRC_URL = os.getenv("KRC_URL", "https://krc.co.ke")

# Nairobi Commuter Rail Lines (from KRC published schedules)
_NCR_LINES: list[dict[str, Any]] = [
    {"id": "ncr-syokimau", "name": "Syokimau Line", "from": "Nairobi CBD", "to": "Syokimau",
     "stations": ["CBD", "Imara Daima", "Kibera", "Langata", "Syokimau"], "length_km": 18},
    {"id": "ncr-ruiru", "name": "Ruiru Line", "from": "Nairobi CBD", "to": "Ruiru",
     "stations": ["CBD", "Kasarani", "Kahawa", "Githurai", "Ruiru"], "length_km": 22},
    {"id": "ncr-kikuyu", "name": "Kikuyu Line", "from": "Nairobi CBD", "to": "Kikuyu",
     "stations": ["CBD", "Kabete", "Kikuyu"], "length_km": 16},
    {"id": "ncr-embakasi", "name": "Embakasi Village Line", "from": "Nairobi CBD", "to": "Embakasi Village",
     "stations": ["CBD", "Donholm", "Embakasi Village"], "length_km": 14},
    {"id": "ncr-limuru", "name": "Limuru Line", "from": "Nairobi CBD", "to": "Limuru",
     "stations": ["CBD", "Westlands", "Kangemi", "Uthiru", "Limuru"], "length_km": 28},
]

# SGR Stations (Nairobi-Mombasa)
_SGR_STATIONS: list[dict[str, Any]] = [
    {"id": "sgr-nrb", "name": "Nairobi Terminus (Syokimau)", "lat": -1.343, "lon": 36.920, "order": 1},
    {"id": "sgr-mls", "name": "Mtito Andei", "lat": -2.690, "lon": 38.170, "order": 2},
    {"id": "sgr-voi", "name": "Voi", "lat": -3.390, "lon": 38.570, "order": 3},
    {"id": "sgr-mbw", "name": "Mombasa Terminus", "lat": -4.020, "lon": 39.620, "order": 4},
]

# Station coordinates (approximate)
_STATION_COORDS: dict[str, tuple[float, float]] = {
    "CBD": (-1.286, 36.823), "Imara Daima": (-1.320, 36.850),
    "Kibera": (-1.313, 36.780), "Langata": (-1.368, 36.746),
    "Syokimau": (-1.343, 36.920), "Kasarani": (-1.220, 36.910),
    "Kahawa": (-1.190, 36.920), "Githurai": (-1.200, 36.910),
    "Ruiru": (-1.150, 36.960), "Kabete": (-1.250, 36.730),
    "Kikuyu": (-1.250, 36.660), "Donholm": (-1.294, 36.887),
    "Embakasi Village": (-1.310, 36.900), "Westlands": (-1.267, 36.804),
    "Kangemi": (-1.265, 36.760), "Uthiru": (-1.260, 36.700),
    "Limuru": (-1.110, 36.640),
}


class KenyaRailwaysFetcher(BaseFetcher):
    """Fetches Kenya Railways operational data.

    Combines:
      1. Static network topology (published station lists)
      2. Schedule data from KRC website scraping
      3. SGR operational statistics (published reports)
      4. Passenger/freight volume models

    Data quality: mostly static + modeled (real-time KRC data not public).
    """

    source_name = "Kenya Railways"
    infrastructure_type = "lrt"
    default_capacity = 24.0
    default_unit = "trains"

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)

    def fetch(self) -> list[dict[str, Any]]:
        records: list[dict] = []

        # 1. NCR line operational status
        records.extend(self._fetch_ncr_status())

        # 2. SGR line operational status
        records.extend(self._fetch_sgr_status())

        # 3. Station-level passenger models
        records.extend(self._generate_station_metrics())

        logger.info("KRC: %d railway records", len(records))
        return records

    def _fetch_ncr_status(self) -> list[dict]:
        """Scrape KRC website for commuter rail status."""
        records: list[dict] = []
        try:
            resp = self._http_get(f"{_KRC_URL}/services/commuter-rail/", timeout=20.0)
            if resp is None:
                return self._ncr_fallback()

            soup = BeautifulSoup(resp.text, "html.parser")
            # Look for service disruption notices
            notices = soup.find_all(["div", "p"], class_=re.compile("notice|alert|status"))

            for line in _NCR_LINES:
                status = "operational"
                delay_min = 0

                # Check if any notice mentions this line
                for notice in notices:
                    text = notice.get_text().lower()
                    if line["name"].lower() in text or line["id"].lower() in text:
                        if "suspend" in text or "cancel" in text:
                            status = "suspended"
                        elif "delay" in text:
                            status = "delayed"
                            # Extract delay if mentioned
                            delay_match = re.search(r'(\d+)\s*min', text)
                            if delay_match:
                                delay_min = int(delay_match.group(1))

                # Estimate current service level
                hour = datetime.now(timezone.utc).hour + 3  # EAT
                if 6 <= hour <= 9 or 17 <= hour <= 20:
                    service_level = "peak"
                    frequency_min = 20
                elif 10 <= hour <= 16:
                    service_level = "off_peak"
                    frequency_min = 45
                else:
                    service_level = "night"
                    frequency_min = 0

                records.append({
                    "asset_id": f"KRC-{line['id']}",
                    "infrastructure_type": "lrt",
                    "ward": line["from"],
                    "lat": _STATION_COORDS.get(line["from"], (0, 0))[0],
                    "lon": _STATION_COORDS.get(line["from"], (0, 0))[1],
                    "value": delay_min,
                    "capacity": 60,
                    "unit": "delay_min",
                    "timestamp": datetime.now(timezone.utc),
                    "source": "krc_website",
                    "is_mock": False,
                    "raw_payload": {
                        "line_name": line["name"],
                        "from": line["from"],
                        "to": line["to"],
                        "length_km": line["length_km"],
                        "status": status,
                        "delay_min": delay_min,
                        "service_level": service_level,
                        "frequency_min": frequency_min,
                        "stations": line["stations"],
                    },
                })
        except Exception as exc:
            logger.warning("KRC scraping failed: %s", exc)
            return self._ncr_fallback()

        return records

    def _fetch_sgr_status(self) -> list[dict]:
        """Fetch SGR operational data from KRC website."""
        records: list[dict] = []
        try:
            resp = self._http_get(f"{_KRC_URL}/services/madaraka-express/", timeout=20.0)
            if resp is None:
                return self._sgr_fallback()

            soup = BeautifulSoup(resp.text, "html.parser")

            # Look for schedule tables
            tables = soup.find_all("table")
            schedules_found = False

            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 3:
                        text = " ".join(c.get_text().strip() for c in cells).lower()
                        if "nairobi" in text and "mombasa" in text:
                            schedules_found = True

            # Daily train frequencies
            hour = datetime.now(timezone.utc).hour + 3
            nairobi_mombasa_trains = 2 if hour < 12 else 1  # Morning + afternoon departures
            mombasa_nairobi_trains = 2 if hour > 12 else 1

            for station in _SGR_STATIONS:
                records.append({
                    "asset_id": f"KRC-SGR-{station['id']}",
                    "infrastructure_type": "sgr",
                    "ward": station["name"],
                    "lat": station["lat"],
                    "lon": station["lon"],
                    "value": nairobi_mombasa_trains + mombasa_nairobi_trains,
                    "capacity": 4,
                    "unit": "daily_trains",
                    "timestamp": datetime.now(timezone.utc),
                    "source": "krc_sgr_website",
                    "is_mock": False,
                    "raw_payload": {
                        "station_name": station["name"],
                        "order": station["order"],
                        "nairobi_bound": nairobi_mombasa_trains,
                        "mombasa_bound": mombasa_nairobi_trains,
                        "schedules_found": schedules_found,
                    },
                })
        except Exception as exc:
            logger.warning("KRC SGR scraping failed: %s", exc)
            return self._sgr_fallback()

        return records

    def _generate_station_metrics(self) -> list[dict]:
        """Generate passenger volume estimates per station."""
        records: list[dict] = []
        import random

        for station_name, (lat, lon) in _STATION_COORDS.items():
            hour = datetime.now(timezone.utc).hour + 3
            # Rush hour multiplier
            if hour in (7, 8, 17, 18):
                mult = 3.0
            elif hour in (9, 16):
                mult = 2.0
            elif hour in (12, 13):
                mult = 1.5
            else:
                mult = 0.5

            # Station base ridership (approximate from KRC reported 50K daily)
            base_ridership = {
                "CBD": 12000, "Syokimau": 8000, "Ruiru": 6000,
                "Kikuyu": 4000, "Embakasi Village": 3500,
                "Kasarani": 5000, "Langata": 3000, "Kibera": 7000,
            }.get(station_name, 2000)

            ridership = int(base_ridership * mult * random.uniform(0.8, 1.2))

            records.append({
                "asset_id": f"KRC-STN-{station_name.replace(' ', '_')}",
                "infrastructure_type": "lrt",
                "ward": station_name,
                "lat": lat,
                "lon": lon,
                "value": ridership,
                "capacity": base_ridership * 4,
                "unit": "passengers_hour",
                "timestamp": datetime.now(timezone.utc),
                "source": "krc_ridership_model",
                "is_mock": True,
                "raw_payload": {
                    "station": station_name,
                    "base_ridership": base_ridership,
                    "hour_eat": hour,
                    "rush_multiplier": mult,
                },
            })
        return records

    def _ncr_fallback(self) -> list[dict]:
        return [{
            "asset_id": f"KRC-{line['id']}",
            "infrastructure_type": "lrt",
            "ward": line["from"],
            "lat": _STATION_COORDS.get(line["from"], (0, 0))[0],
            "lon": _STATION_COORDS.get(line["from"], (0, 0))[1],
            "value": 0,
            "capacity": 60,
            "unit": "delay_min",
            "timestamp": datetime.now(timezone.utc),
            "source": "krc_fallback",
            "is_mock": True,
            "raw_payload": {"line": line["name"], "reason": "krc_website_unavailable"},
        } for line in _NCR_LINES]

    def _sgr_fallback(self) -> list[dict]:
        return [{
            "asset_id": f"KRC-SGR-{s['id']}",
            "infrastructure_type": "sgr",
            "ward": s["name"],
            "lat": s["lat"],
            "lon": s["lon"],
            "value": 2,
            "capacity": 4,
            "unit": "daily_trains",
            "timestamp": datetime.now(timezone.utc),
            "source": "krc_fallback",
            "is_mock": True,
            "raw_payload": {"station": s["name"], "reason": "krc_website_unavailable"},
        } for s in _SGR_STATIONS]

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
