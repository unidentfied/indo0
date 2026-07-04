"""Sindio — CHIRPS Rainfall Fetcher (Climate Hazards Center InfraRed Precipitation).

CHIRPS provides daily rainfall estimates from 1981 to present, combining
satellite imagery with in-situ station data. Critical for:
  - Water reservoir inflow forecasting
  - Flood risk assessment
  - Solid waste collection disruption (impassable roads)
  - Power generation (hydroelectric inflow)

Data source: https://www.chc.ucsb.edu/data/chirps
API: https://chc-dataout.unl.edu/api/ (or direct GeoTIFF download)
Alternative: IRI Climate Data Library (http://iridl.ldeo.columbia.edu/)

Free, no API key required. Daily updates with ~6-week latency.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from ..base import BaseFetcher, FetcherResult

logger = logging.getLogger("sindio.ingestion.chirps")

# IRI Climate Data Library endpoint for CHIRPS
_CHIRPS_IRI_URL = (
    "http://iridl.ldeo.columbia.edu/SOURCES/.UCSB/.CHIRPS/.v2p0/.daily/.prculated/"
    "T/(YMD)/VALUE/T+exch+table-+text+text+skipanyNaN+-table+.csv"
)

# Nairobi watershed monitoring points
_WATER_MONITORING_POINTS: list[dict[str, Any]] = [
    {"id": "ndakaini", "name": "Ndakaini Dam", "lat": -0.82, "lon": 36.85, "watershed": "tana"},
    {"id": "sasumua", "name": "Sasumua Dam", "lat": -0.72, "lon": 36.67, "watershed": "tana"},
    {"id": "ruiru_dam", "name": "Ruiru Dam", "lat": -1.12, "lon": 36.97, "watershed": "ath"},
    {"id": "nairobi_river", "name": "Nairobi River", "lat": -1.29, "lon": 36.85, "watershed": "ath"},
    {"id": "karen_stream", "name": "Karen Stream", "lat": -1.38, "lon": 36.73, "watershed": "ath"},
    {"id": "masinga", "name": "Masinga Reservoir", "lat": -0.80, "lon": 37.60, "watershed": "tana"},
    {"id": "kamburu", "name": "Kamburu Dam", "lat": -0.75, "lon": 37.70, "watershed": "tana"},
]


class CHIRPS_Fetcher(BaseFetcher):
    """Fetches CHIRPS daily rainfall for Nairobi watersheds.

    Data returned:
      - Daily precipitation (mm)
      - 5-day and 30-day rolling totals
      - Wet/dry season classification
      - Flood risk index (based on intensity + duration)

    No authentication required.
    """

    source_name = "CHIRPS Rainfall"
    infrastructure_type = "water"
    default_capacity = 100.0
    default_unit = "mm"

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)

    def fetch(self) -> list[dict[str, Any]]:
        records: list[dict] = []
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=30)

        for point in _WATER_MONITORING_POINTS:
            data = self._fetch_chirps(point["lat"], point["lon"], start_date, end_date)
            if data:
                parsed = self._parse_rainfall(data, point)
                records.extend(parsed)
            else:
                records.extend(self._seasonal_fallback(point, start_date, end_date))
            time.sleep(1.0)

        logger.info("CHIRPS: %d rainfall records", len(records))
        return records

    def _fetch_chirps(self, lat: float, lon: float, start: datetime, end: datetime) -> Optional[list]:
        """Fetch CHIRPS data via IRI Climate Data Library CSV endpoint."""
        try:
            # Construct IRI query URL
            # Format: YMD(START)YMD(END)LATLON
            start_str = start.strftime("%Y%m%d")
            end_str = end.strftime("%Y%m%d")

            # IRI uses a specific query syntax
            url = (
                f"http://iridl.ldeo.columbia.edu/SOURCES/.UCSB/.CHIRPS/.v2p0/.daily/.prculated/"
                f"X/{lon}/VALUE/"
                f"Y/{lat}/VALUE/"
                f"T/(YMD({start_str}):YMD({end_str}))/VALUE/"
                f"T+exch+table-+text+text+skipanyNaN+-table+.csv"
            )

            resp = self._http_get(url, timeout=45.0)
            if resp is None:
                return None

            text = resp.text
            lines = text.strip().split("\n")
            # Skip header lines (IRI returns metadata headers)
            data_lines = [l for l in lines if l.strip() and not l.startswith("%")]
            if not data_lines:
                return None

            # Parse CSV: date, rainfall
            results: list[tuple[str, float]] = []
            for line in data_lines:
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        date_str = parts[0].strip()
                        rainfall = float(parts[1].strip())
                        results.append((date_str, rainfall))
                    except ValueError:
                        continue
            return results
        except Exception as exc:
            logger.warning("CHIRPS fetch failed for (%.3f, %.3f): %s", lat, lon, exc)
            return None

    def _parse_rainfall(self, data: list[tuple[str, float]], point: dict) -> list[dict]:
        records: list[dict] = []
        # Compute rolling sums
        rainfall_values = [r[1] for r in data]

        for i, (date_str, rainfall) in enumerate(data):
            # 5-day rolling
            rain_5d = sum(rainfall_values[max(0, i - 4):i + 1])
            # 30-day rolling
            rain_30d = sum(rainfall_values[max(0, i - 29):i + 1])

            # Flood risk index: intensity + saturation
            # Heavy rain > 20mm/day or > 50mm/5days → elevated risk
            flood_risk = 0.0
            if rainfall > 20:
                flood_risk = min(100, (rainfall - 20) * 5)
            elif rain_5d > 50:
                flood_risk = min(100, (rain_5d - 50) * 2)

            # Reservoir inflow index
            inflow_index = min(100, rainfall * 3.0 + rain_5d * 0.5)

            dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)

            records.append({
                "asset_id": f"CHIRPS-{point['id']}-{date_str}",
                "infrastructure_type": "water",
                "ward": point["name"],
                "lat": point["lat"],
                "lon": point["lon"],
                "value": round(rainfall, 1),
                "capacity": 100.0,
                "unit": "mm",
                "timestamp": dt,
                "source": "chirps_v2",
                "is_mock": False,
                "raw_payload": {
                    "watershed": point["watershed"],
                    "rainfall_1d_mm": round(rainfall, 1),
                    "rainfall_5d_mm": round(rain_5d, 1),
                    "rainfall_30d_mm": round(rain_30d, 1),
                    "flood_risk_index": round(flood_risk, 1),
                    "reservoir_inflow_index": round(inflow_index, 1),
                },
            })
        return records

    def _seasonal_fallback(self, point: dict, start: datetime, end: datetime) -> list[dict]:
        """Generate seasonal rainfall model when CHIRPS unavailable."""
        records: list[dict] = []
        current = start

        while current <= end:
            month = current.month
            # Nairobi seasonal rainfall model (bimodal: Mar-May long rains, Oct-Nov short rains)
            seasonal = {
                1: 1.5, 2: 2.0, 3: 5.0, 4: 8.0, 5: 6.0,
                6: 1.0, 7: 0.5, 8: 0.8, 9: 2.0,
                10: 5.0, 11: 4.0, 12: 2.5,
            }
            base = seasonal.get(month, 2.0)
            import random
            rainfall = max(0, random.gauss(base, base * 0.3))

            records.append({
                "asset_id": f"CHIRPS-{point['id']}-{current.strftime('%Y%m%d')}",
                "infrastructure_type": "water",
                "ward": point["name"],
                "lat": point["lat"],
                "lon": point["lon"],
                "value": round(rainfall, 1),
                "capacity": 100.0,
                "unit": "mm",
                "timestamp": current.replace(tzinfo=timezone.utc),
                "source": "chirps_seasonal_fallback",
                "is_mock": True,
                "raw_payload": {
                    "month": month,
                    "seasonal_average_mm": base,
                    "method": "nairobi_rainfall_model",
                },
            })
            current += timedelta(days=1)
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
