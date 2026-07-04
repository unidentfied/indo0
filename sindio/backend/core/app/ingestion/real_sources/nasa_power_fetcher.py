"""Sindio — NASA POWER Fetcher (climate, solar radiation, wind for power demand forecasting).

NASA POWER provides free meteorological data derived from satellite observations.
No API key required. Supports any lat/lon globally.

API: https://power.larc.nasa.gov/api/pages/
Endpoint: GET /api/temporal/daily/point
Parameters: parameters, community, longitude, latitude, start, end, format

Useful parameters for Nairobi infrastructure:
  - T2M: Temperature at 2 meters (C) — power demand correlation
  - TS: Earth Skin Temperature (C) — thermal stress
  - ALLSKY_SFC_SW_DWN: All Sky Surface Shortwave Downward Irradiance (W/m²) — solar generation potential
  - WS10M: Wind Speed at 10 Meters (m/s) — wind generation potential
  - PRECTOTCORR: Precipitation Corrected (mm/day) — water reservoir inflow
  - RH2M: Relative Humidity at 2 Meters (%) — transformer cooling efficiency
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from ..base import BaseFetcher, FetcherResult

logger = logging.getLogger("sindio.ingestion.nasa_power")

_NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

_NAIROBI_GRID_POINTS: list[dict[str, Any]] = [
    {"name": "CBD", "lat": -1.286, "lon": 36.823},
    {"name": "Industrial_Area", "lat": -1.315, "lon": 36.847},
    {"name": "Westlands", "lat": -1.267, "lon": 36.804},
    {"name": "Karen", "lat": -1.378, "lon": 36.726},
    {"name": "Eastleigh", "lat": -1.268, "lon": 36.850},
    {"name": "Embakasi", "lat": -1.315, "lon": 36.900},
    {"name": "Kasarani", "lat": -1.220, "lon": 36.910},
    {"name": "Kibera", "lat": -1.313, "lon": 36.780},
    {"name": "Ruaraka", "lat": -1.210, "lon": 36.880},
    {"name": "Dagoretti", "lat": -1.295, "lon": 36.756},
]

_POWER_DEMAND_PARAMS = "T2M,TS,ALLSKY_SFC_SW_DWN,WS10M,PRECTOTCORR,RH2M"


class NASA_POWER_Fetcher(BaseFetcher):
    """Fetches NASA satellite-derived climate data for Nairobi.

    Primary use cases:
      1. Power demand forecasting (temperature correlation)
      2. Solar generation potential (irradiance)
      3. Wind generation assessment
      4. Water reservoir inflow estimation (precipitation)
      5. Thermal stress index (humidity + temperature)

    Data latency: ~2-3 days (reanalysis products)
    Resolution: 0.5° x 0.5° (approx 55km), interpolated to point
    """

    source_name = "NASA POWER"
    infrastructure_type = "power"
    default_capacity = 100.0
    default_unit = "index"

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)

    def fetch(self) -> list[dict[str, Any]]:
        records: list[dict] = []

        # Fetch last 7 days of data
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=7)

        for point in _NAIROBI_GRID_POINTS:
            data = self._fetch_point(point["lat"], point["lon"], start_date, end_date)
            if data and "properties" in data:
                parsed = self._parse_daily_data(data, point)
                records.extend(parsed)
            else:
                # Fallback: generate synthetic based on known Nairobi climate
                records.extend(self._climate_fallback(point, start_date, end_date))
            time.sleep(0.5)  # Rate limit

        logger.info("NASA POWER: %d daily records across %d locations", len(records), len(_NAIROBI_GRID_POINTS))
        return records

    def _fetch_point(self, lat: float, lon: float, start: datetime, end: datetime) -> Optional[dict]:
        params = {
            "parameters": _POWER_DEMAND_PARAMS,
            "community": "RE",  # Renewable Energy community
            "longitude": lon,
            "latitude": lat,
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "format": "JSON",
        }
        url = _NASA_POWER_URL
        try:
            resp = self._http_get(url, timeout=30.0)
            if resp is None:
                return None
            return resp.json()
        except Exception as exc:
            logger.warning("NASA POWER fetch failed for (%.3f, %.3f): %s", lat, lon, exc)
            return None

    def _parse_daily_data(self, data: dict, point: dict) -> list[dict]:
        records: list[dict] = []
        props = data.get("properties", {})
        params = props.get("parameter", {})

        # NASA POWER returns dates as keys in each parameter dict
        dates = set()
        for param_values in params.values():
            if isinstance(param_values, dict):
                dates.update(param_values.keys())

        for date_str in sorted(dates):
            temp_c = params.get("T2M", {}).get(date_str, 22.0)
            skin_temp = params.get("TS", {}).get(date_str, 25.0)
            irradiance = params.get("ALLSKY_SFC_SW_DWN", {}).get(date_str, 200.0)
            wind_speed = params.get("WS10M", {}).get(date_str, 3.0)
            rainfall = params.get("PRECTOTCORR", {}).get(date_str, 0.0)
            humidity = params.get("RH2M", {}).get(date_str, 65.0)

            # Compute power demand index (0-100)
            # Higher temperature → higher cooling demand → higher power consumption
            # Peak demand typically at 30°C+, minimum at 18°C
            demand_index = max(0, min(100, (temp_c - 18) * 3.5 + (humidity - 50) * 0.5))

            # Solar generation potential (0-100)
            # 1000 W/m² is roughly clear sky noon in equatorial regions
            solar_potential = min(100, irradiance / 10.0)

            # Water inflow estimate (0-100, relative)
            # Nairobi receives ~1000mm/year = ~2.7mm/day average
            # Wet season peaks at 10-15mm/day
            inflow_index = min(100, rainfall * 7.0)

            dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)

            records.append({
                "asset_id": f"NASA-{point['name']}-{date_str}",
                "infrastructure_type": "power",
                "ward": point["name"],
                "lat": point["lat"],
                "lon": point["lon"],
                "value": round(demand_index, 1),
                "capacity": 100.0,
                "unit": "demand_index",
                "timestamp": dt,
                "source": "nasa_power",
                "is_mock": False,
                "raw_payload": {
                    "temperature_c": temp_c,
                    "skin_temp_c": skin_temp,
                    "solar_irradiance_wm2": irradiance,
                    "wind_speed_ms": wind_speed,
                    "rainfall_mm": rainfall,
                    "humidity_pct": humidity,
                    "solar_potential": round(solar_potential, 1),
                    "water_inflow_index": round(inflow_index, 1),
                },
            })

        return records

    def _climate_fallback(self, point: dict, start: datetime, end: datetime) -> list[dict]:
        """Generate Nairobi climate model data when NASA API is unavailable."""
        records: list[dict] = []
        current = start
        while current <= end:
            month = current.month
            # Nairobi climate model
            seasonal = {
                1: (25.0, 2.0, 65.0, 220.0),  # Jan: warm, dry
                2: (26.0, 3.0, 62.0, 230.0),
                3: (26.5, 5.0, 60.0, 210.0),  # Mar: warm, wet start
                4: (25.0, 8.0, 72.0, 180.0),  # Apr: wet
                5: (23.0, 6.0, 78.0, 160.0),  # May: cooler, wet
                6: (21.0, 1.0, 75.0, 170.0),  # Jun: cool, dry
                7: (20.0, 0.5, 72.0, 180.0),  # Jul: coolest
                8: (21.0, 1.0, 68.0, 190.0),  # Aug: warming
                9: (23.0, 2.0, 62.0, 210.0),  # Sep: warm, dry
                10: (25.0, 5.0, 60.0, 220.0), # Oct: short rains
                11: (24.5, 4.0, 66.0, 210.0),
                12: (24.0, 3.0, 65.0, 200.0),
            }
            temp, rain, humid, irradiance = seasonal.get(month, (23.0, 2.0, 65.0, 200.0))

            demand_index = max(0, min(100, (temp - 18) * 3.5 + (humidity - 50) * 0.5))

            records.append({
                "asset_id": f"NASA-{point['name']}-{current.strftime('%Y%m%d')}",
                "infrastructure_type": "power",
                "ward": point["name"],
                "lat": point["lat"],
                "lon": point["lon"],
                "value": round(demand_index, 1),
                "capacity": 100.0,
                "unit": "demand_index",
                "timestamp": current.replace(tzinfo=timezone.utc),
                "source": "nasa_power_fallback",
                "is_mock": True,
                "raw_payload": {
                    "temperature_c": temp,
                    "rainfall_mm": rain,
                    "humidity_pct": humid,
                    "solar_irradiance_wm2": irradiance,
                    "method": "nairobi_climate_model",
                },
            })
            current += timedelta(days=1)
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
                logger.error("NASA POWER DB insert failed: %s", exc)

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
