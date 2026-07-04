"""Sindio — Open-Meteo Weather Fetcher (thermal stress, precipitation, UV)."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseFetcher, FetcherResult

logger = logging.getLogger("sindio.ingestion.weather")

_NAIROBI_WEATHER_STATIONS: list[dict[str, Any]] = [
    {"id": "dagoretti", "name": "Dagoretti Corner", "lat": -1.30, "lon": 36.76, "elevation_m": 1798},
    {"id": "jkia", "name": "JKIA", "lat": -1.33, "lon": 36.92, "elevation_m": 1624},
    {"id": "wilson", "name": "Wilson Airport", "lat": -1.32, "lon": 36.81, "elevation_m": 1691},
    {"id": "karen", "name": "Karen", "lat": -1.38, "lon": 36.72, "elevation_m": 1930},
    {"id": "ruiru", "name": "Ruiru", "lat": -1.15, "lon": 36.96, "elevation_m": 1530},
    {"id": "ongata_rongai", "name": "Ongata Rongai", "lat": -1.40, "lon": 36.74, "elevation_m": 1708},
    {"id": "kikuyu", "name": "Kikuyu", "lat": -1.25, "lon": 36.66, "elevation_m": 2080},
    {"id": "limuru", "name": "Limuru", "lat": -1.11, "lon": 36.64, "elevation_m": 2280},
    {"id": "thika", "name": "Thika", "lat": -1.03, "lon": 37.07, "elevation_m": 1531},
    {"id": "athi_river", "name": "Athi River", "lat": -1.45, "lon": 37.00, "elevation_m": 1534},
]

_OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
_OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"


class WeatherFetcher(BaseFetcher):
    """Fetches real-time thermal stress, precipitation, and UV data for Nairobi.

    Sources (tried in order):
      1. Open-Meteo free API (no key required) — preferred
      2. OpenWeatherMap (requires OPENWEATHER_API_KEY env var)
      3. Kenya Meteorological Department fallback (static seasonal averages)
    """

    source_name = "Nairobi Weather"
    infrastructure_type = "power"
    default_capacity = 50.0
    default_unit = "Celsius"

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)
        self._owm_key = os.getenv("OPENWEATHER_API_KEY", "")
        self._meteo_url = os.getenv("OPEN_METEO_URL", _OPEN_METEO_FORECAST_URL)

    def fetch(self) -> list[dict[str, Any]]:
        records: list[dict] = []

        for station in _NAIROBI_WEATHER_STATIONS:
            record = self._fetch_open_meteo(station) or self._fetch_openweather(station) or self._seasonal_fallback(station)
            if record:
                records.append(record)

        logger.info("Fetched %d weather station records", len(records))
        return records

    # ── Open-Meteo (free, no API key) ──────────────────────────────

    def _fetch_open_meteo(self, station: dict) -> Optional[dict]:
        params = {
            "latitude": station["lat"],
            "longitude": station["lon"],
            "current": "temperature_2m,relative_humidity_2m,precipitation,"
                       "cloud_cover,wind_speed_10m,apparent_temperature,uv_index",
            "timezone": "Africa/Nairobi",
            "forecast_days": 1,
        }
        try:
            data = self._http_get(self._meteo_url, params=params, timeout=15.0)
            current = data.get("current", {})
            if not current:
                return None

            temp = current.get("temperature_2m", 0)
            humidity = current.get("relative_humidity_2m", 0)
            apparent_temp = current.get("apparent_temperature", temp)
            uv = current.get("uv_index", 0)

            thermal_stress = self._compute_thermal_stress(temp, humidity, uv)

            return {
                "asset_id": f"WX-{station['id']}",
                "infrastructure_type": "power",
                "ward": station["name"],
                "lat": station["lat"],
                "lon": station["lon"],
                "value": thermal_stress,
                "capacity": 50.0,
                "unit": "thermal_stress_index",
                "timestamp": datetime.now(timezone.utc),
                "source": "open_meteo",
                "is_mock": False,
                "raw_payload": {
                    "temperature_c": temp,
                    "apparent_temperature_c": apparent_temp,
                    "relative_humidity_pct": humidity,
                    "uv_index": uv,
                    "wind_speed_kmh": current.get("wind_speed_10m", 0),
                    "cloud_cover_pct": current.get("cloud_cover", 0),
                    "elevation_m": station["elevation_m"],
                    "provider": "open-meteo.com",
                },
            }
        except Exception as exc:
            logger.warning("Open-Meteo fetch failed for %s: %s", station["id"], exc)
            return None

    # ── OpenWeatherMap (requires API key) ──────────────────────────

    def _fetch_openweather(self, station: dict) -> Optional[dict]:
        if not self._owm_key:
            return None
        params = {
            "lat": station["lat"],
            "lon": station["lon"],
            "appid": self._owm_key,
            "units": "metric",
        }
        try:
            data = self._http_get(_OPENWEATHER_URL, params=params, timeout=10.0)
            main = data.get("main", {})
            temp = main.get("temp", 0)
            humidity = main.get("humidity", 0)
            thermal_stress = self._compute_thermal_stress(temp, humidity, uv=0)

            return {
                "asset_id": f"WX-{station['id']}",
                "infrastructure_type": "power",
                "ward": station["name"],
                "lat": station["lat"],
                "lon": station["lon"],
                "value": thermal_stress,
                "capacity": 50.0,
                "unit": "thermal_stress_index",
                "timestamp": datetime.now(timezone.utc),
                "source": "openweathermap",
                "is_mock": False,
                "raw_payload": {
                    "temperature_c": temp,
                    "humidity_pct": humidity,
                    "pressure_hpa": main.get("pressure", 0),
                    "provider": "openweathermap.org",
                },
            }
        except Exception as exc:
            logger.warning("OpenWeatherMap fetch failed for %s: %s", station["id"], exc)
            return None

    # ── Thermal stress computation ─────────────────────────────────

    @staticmethod
    def _compute_thermal_stress(temp_c: float, humidity_pct: float, uv_index: float) -> float:
        """Compute thermal stress index (0-100) on power infrastructure.

        High temperatures + humidity degrade transformer cooling efficiency
        and transmission line capacity. UV radiation accelerates insulator aging.

        Formula: 0.5*(temp/45) + 0.25*(humidity/100) + 0.15*(uv/11) + 0.10*(apparent_bonus)
        Scaled to 0-100 range.
        """
        if temp_c <= 0 and humidity_pct <= 0:
            return 0.0

        temp_factor = max(0.0, min(1.0, (temp_c - 15.0) / 30.0))  # 15-45°C range
        humidity_factor = max(0.0, min(1.0, humidity_pct / 100.0))
        uv_factor = max(0.0, min(1.0, uv_index / 11.0))

        heat_index = temp_c + (0.33 * humidity_pct * (temp_c - 15.0) / 100.0)
        apparent_bonus = max(0.0, min(1.0, (heat_index - 25.0) / 20.0))

        raw = 0.50 * temp_factor + 0.25 * humidity_factor + 0.15 * uv_factor + 0.10 * apparent_bonus
        return round(raw * 100.0, 1)

    # ── Seasonal fallback (Nairobi climate model) ──────────────────

    def _seasonal_fallback(self, station: dict) -> dict:
        month = datetime.now(timezone.utc).month
        seasonal = {
            1: (25.0, 63.0, 10.0),  2: (26.0, 58.0, 11.0),
            3: (26.5, 62.0, 11.5),  4: (24.0, 73.0, 11.0),
            5: (22.5, 78.0, 10.0),  6: (21.0, 75.0, 9.0),
            7: (20.0, 72.0, 9.0),   8: (21.0, 68.0, 10.0),
            9: (23.0, 62.0, 10.5), 10: (25.0, 60.0, 11.0),
           11: (24.5, 66.0, 10.5), 12: (24.0, 65.0, 10.0),
        }
        temp, humidity, uv = seasonal.get(month, (23.0, 65.0, 10.0))
        elevation_adjust = (station["elevation_m"] - 1624) * -0.0065
        adjusted_temp = temp + elevation_adjust

        return {
            "asset_id": f"WX-{station['id']}",
            "infrastructure_type": "power",
            "ward": station["name"],
            "lat": station["lat"],
            "lon": station["lon"],
            "value": self._compute_thermal_stress(adjusted_temp, humidity, uv),
            "capacity": 50.0,
            "unit": "thermal_stress_index",
            "timestamp": datetime.now(timezone.utc),
            "source": "seasonal_fallback",
            "is_mock": True,
            "raw_payload": {
                "temperature_c": adjusted_temp,
                "humidity_pct": humidity,
                "uv_index": uv,
                "month": month,
                "elevation_m": station["elevation_m"],
                "provider": "nairobi_climate_model",
            },
        }

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
                logger.error("Weather DB insert failed: %s", exc)

        status = "success" if not errors else ("partial" if inserted > 0 else "failed")
        result = FetcherResult(status=status, records=len(records), inserted=inserted, errors=errors, elapsed=elapsed)
        try:
            self._log_run(result)
        except Exception:
            pass
        return result
