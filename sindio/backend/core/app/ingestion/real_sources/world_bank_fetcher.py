"""Sindio — World Bank API Fetcher (Kenya development indicators).

The World Bank provides free API access to development indicators for
every country. Useful for Sindio:
  - Access to electricity (% of population)
  - Access to clean water (% of population)
  - Road density (km per 100 km²)
  - Urban population (%)
  - GDP per capita (infrastructure investment proxy)
  - CO2 emissions (energy consumption proxy)

API: https://api.worldbank.org/v2/
No authentication required.
Data updated annually.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..base import BaseFetcher, FetcherResult

logger = logging.getLogger("sindio.ingestion.world_bank")

_WB_API_BASE = "https://api.worldbank.org/v2"
_WB_COUNTRY = "KEN"  # Kenya

# Relevant World Bank indicators for Sindio
_WB_INDICATORS: list[dict[str, Any]] = [
    {"id": "EG.ELC.ACCS.ZS", "name": "Access to electricity", "unit": "pct", "infra": "power"},
    {"id": "EG.ELC.RNEW.ZS", "name": "Renewable energy share", "unit": "pct", "infra": "power"},
    {"id": "SH.H2O.SMDW.ZS", "name": "Access to clean water", "unit": "pct", "infra": "water"},
    {"id": "ER.H2O.FWTL.ZS", "name": "Annual freshwater withdrawals", "unit": "pct", "infra": "water"},
    {"id": "IS.ROD.DNST.K2", "name": "Road density", "unit": "km_per_100km2", "infra": "roads"},
    {"id": "IS.ROD.PAVE.ZS", "name": "Paved roads", "unit": "pct", "infra": "roads"},
    {"id": "SP.URB.TOTL.IN.ZS", "name": "Urban population", "unit": "pct", "infra": "roads"},
    {"id": "EN.ATM.CO2E.KD.GD", "name": "CO2 intensity", "unit": "kg_per_usd", "infra": "power"},
    {"id": "NY.GDP.PCAP.CD", "name": "GDP per capita", "unit": "usd", "infra": "general"},
    {"id": "EG.IMP.CONS.ZS", "name": "Energy imports", "unit": "pct", "infra": "power"},
]


class WorldBankFetcher(BaseFetcher):
    """Fetches Kenya development indicators from World Bank API.

    Data is annual, with ~1 year lag. Provides macro-level context for
    infrastructure stress modeling (e.g., electrification rate affects
    power demand growth projections).
    """

    source_name = "World Bank"
    infrastructure_type = "power"
    default_capacity = 100.0
    default_unit = "pct"

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)

    def fetch(self) -> list[dict[str, Any]]:
        records: list[dict] = []

        for indicator in _WB_INDICATORS:
            data = self._fetch_indicator(indicator["id"])
            if data:
                parsed = self._parse_indicator(data, indicator)
                records.extend(parsed)
            time.sleep(0.5)  # Rate limit

        logger.info("World Bank: %d indicator records", len(records))
        return records

    def _fetch_indicator(self, indicator_id: str) -> Optional[list]:
        url = f"{_WB_API_BASE}/country/{_WB_COUNTRY}/indicator/{indicator_id}"
        params = {
            "format": "json",
            "per_page": 10,
            "date": "2015:2024",
        }
        try:
            resp = self._http_get(url, params=params, timeout=20.0)
            if resp is None:
                return None
            data = resp.json()
            # World Bank returns [metadata, [data...]]
            if isinstance(data, list) and len(data) > 1:
                return data[1]
            return None
        except Exception as exc:
            logger.warning("World Bank fetch failed for %s: %s", indicator_id, exc)
            return None

    def _parse_indicator(self, data: list, indicator: dict) -> list[dict]:
        records: list[dict] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            year = entry.get("date")
            value = entry.get("value")
            if value is None:
                continue

            records.append({
                "asset_id": f"WB-{_WB_COUNTRY}-{indicator['id']}-{year}",
                "infrastructure_type": indicator["infra"],
                "ward": "Kenya",
                "lat": 0.0,
                "lon": 36.0,
                "value": float(value),
                "capacity": 100.0 if indicator["unit"] == "pct" else 1000000,
                "unit": indicator["unit"],
                "timestamp": datetime(int(year), 6, 30, tzinfo=timezone.utc) if year else datetime.now(timezone.utc),
                "source": "world_bank_api",
                "is_mock": False,
                "raw_payload": {
                    "indicator_id": indicator["id"],
                    "indicator_name": indicator["name"],
                    "year": year,
                    "country": _WB_COUNTRY,
                },
            })
        return records

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
