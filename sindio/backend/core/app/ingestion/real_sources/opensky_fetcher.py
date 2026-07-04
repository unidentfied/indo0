"""Sindio — OpenSky Network Aviation Fetcher (JKIA real-time flight data).

OpenSky Network is a free, community-driven flight tracking network.
No API key required for basic queries. Data is delayed ~5-10 seconds.

API: https://opensky-network.org/apidoc/rest.html
Endpoint: GET /api/states/all?lamin={}&lomin={}&lamax={}&lomax={}

Coverage: All ADS-B transponder-equipped aircraft within Nairobi FIR.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..base import BaseFetcher, FetcherResult

logger = logging.getLogger("sindio.ingestion.opensky")

# Nairobi FIR bounding box (approximate)
_NAIROBI_FIR_BBOX = {"lamin": -4.5, "lomin": 33.0, "lamax": 5.5, "lomax": 43.0}
# JKIA focused box
_JKIA_BBOX = {"lamin": -1.5, "lomin": 36.5, "lamax": -1.0, "lomax": 37.2}

_OSM_API_URL = "https://opensky-network.org/api/states/all"

# Real airports in Kenya with ICAO codes
_KENYA_AIRPORTS = {
    "HKJK": {"name": "Jomo Kenyatta International", "lat": -1.3192, "lon": 36.9278, "city": "Nairobi"},
    "HKMO": {"name": "Moi International", "lat": -4.0348, "lon": 39.5942, "city": "Mombasa"},
    "HKNW": {"name": "Wilson Airport", "lat": -1.3217, "lon": 36.8148, "city": "Nairobi"},
    "HKEL": {"name": "Eldoret International", "lat": 0.4046, "lon": 35.2380, "city": "Eldoret"},
    "HKKR": {"name": "Kisumu International", "lat": -0.0861, "lon": 34.7289, "city": "Kisumu"},
    "HKML": {"name": "Malindi Airport", "lat": -3.2290, "lon": 40.1017, "city": "Malindi"},
}

# Aircraft categories from ICAO type designators
_AIRCRAFT_CATEGORIES = {
    # Commercial jets
    "A319": "narrow_body", "A320": "narrow_body", "A321": "narrow_body",
    "A330": "wide_body", "A350": "wide_body", "A380": "wide_body",
    "B737": "narrow_body", "B738": "narrow_body", "B739": "narrow_body",
    "B744": "wide_body", "B748": "wide_body", "B777": "wide_body", "B787": "wide_body",
    # Regional
    "ATR7": "regional", "ATR4": "regional", "DH8D": "regional", "E190": "regional",
    # Cargo
    "B74F": "cargo", "B77F": "cargo", "A30F": "cargo",
    # General aviation
    "C172": "ga", "C208": "ga",
}


class OpenSkyFetcher(BaseFetcher):
    """Fetches real-time aircraft positions from OpenSky Network.

    Data fields per aircraft:
      - icao24: transponder hex code
      - callsign: flight identifier
      - origin_country: country of registration
      - longitude, latitude, altitude, velocity
      - on_ground: boolean
      - heading: track angle
      - vertical_rate: climb/descent rate
      - sensors: list of receiving ground stations
      - geo_altitude, baro_altitude

    Rate limit: ~10 req/min for unauthenticated users.
    """

    source_name = "OpenSky Network"
    infrastructure_type = "airports"
    default_capacity = 100.0
    default_unit = "flights"

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)
        self._username = os.getenv("OPENSKY_USERNAME", "")
        self._password = os.getenv("OPENSKY_PASSWORD", "")
        self._use_auth = bool(self._username and self._password)

    def fetch(self) -> list[dict[str, Any]]:
        records: list[dict] = []

        # Fetch full Nairobi FIR
        raw = self._fetch_bbox(_NAIROBI_FIR_BBOX)
        if not raw:
            logger.warning("OpenSky: no data returned, using fallback")
            return self._fallback_data()

        states = raw.get("states", [])
        if not states:
            return self._fallback_data()

        # Count flights by airport proximity
        airport_counts = {icao: {"arrivals": 0, "departures": 0, "overflights": 0} for icao in _KENYA_AIRPORTS}

        for state in states:
            # OpenSky state vector format (17 fields)
            # [icao24, callsign, origin_country, time_position, last_contact,
            #  longitude, latitude, baro_altitude, on_ground, velocity,
            #  true_track, vertical_rate, sensors, geo_altitude, squawk,
            #  spi, position_source]
            if len(state) < 17:
                continue

            icao24 = state[0]
            callsign = (state[1] or "").strip()
            origin_country = state[2]
            lat = state[6]
            lon = state[5]
            altitude = state[7] or 0
            velocity = state[9] or 0
            heading = state[10] or 0
            vertical_rate = state[11] or 0
            on_ground = state[8] if state[8] is not None else False

            if lat is None or lon is None:
                continue

            # Determine nearest airport
            nearest_icao, nearest_dist = self._nearest_airport(lat, lon)

            # Classify flight phase
            if nearest_dist < 10.0 and altitude < 1500 and on_ground:
                phase = "ground"
            elif nearest_dist < 15.0 and altitude < 3000 and vertical_rate < -500:
                phase = "approach"
            elif nearest_dist < 15.0 and altitude < 3000 and vertical_rate > 500:
                phase = "departure"
            elif altitude > 8000:
                phase = "cruise"
            else:
                phase = "maneuver"

            if nearest_icao and nearest_icao in airport_counts:
                if phase in ("approach",):
                    airport_counts[nearest_icao]["arrivals"] += 1
                elif phase in ("departure",):
                    airport_counts[nearest_icao]["departures"] += 1
                elif phase == "cruise":
                    airport_counts[nearest_icao]["overflights"] += 1

            records.append({
                "asset_id": f"ADS-B-{icao24}",
                "infrastructure_type": "airports",
                "ward": nearest_icao or "unknown",
                "lat": lat,
                "lon": lon,
                "value": float(altitude) if altitude else 0,
                "capacity": 45000,  # FL450
                "unit": "ft",
                "timestamp": datetime.now(timezone.utc),
                "source": "opensky_adsb",
                "is_mock": False,
                "raw_payload": {
                    "icao24": icao24,
                    "callsign": callsign,
                    "origin_country": origin_country,
                    "velocity_ms": velocity,
                    "heading_deg": heading,
                    "vertical_rate": vertical_rate,
                    "on_ground": on_ground,
                    "phase": phase,
                    "nearest_airport_icao": nearest_icao,
                    "nearest_airport_dist_km": round(nearest_dist, 1),
                },
            })

        # Add airport-level summary records
        for icao, info in _KENYA_AIRPORTS.items():
            counts = airport_counts.get(icao, {"arrivals": 0, "departures": 0, "overflights": 0})
            total = counts["arrivals"] + counts["departures"]
            records.append({
                "asset_id": f"APT-{icao}",
                "infrastructure_type": "airports",
                "ward": info["city"],
                "lat": info["lat"],
                "lon": info["lon"],
                "value": total,
                "capacity": 50,  # approximate hourly capacity
                "unit": "flights_per_hour",
                "timestamp": datetime.now(timezone.utc),
                "source": "opensky_airport_summary",
                "is_mock": False,
                "raw_payload": {
                    "airport_icao": icao,
                    "airport_name": info["name"],
                    "arrivals": counts["arrivals"],
                    "departures": counts["departures"],
                    "overflights": counts["overflights"],
                    "total_active": total,
                },
            })

        logger.info("OpenSky: %d aircraft tracked, %d airport summaries", len(states), len(_KENYA_AIRPORTS))
        return records

    def _fetch_bbox(self, bbox: dict) -> Optional[dict]:
        url = (
            f"{_OSM_API_URL}"
            f"?lamin={bbox['lamin']}&lomin={bbox['lomin']}"
            f"&lamax={bbox['lamax']}&lomax={bbox['lomax']}"
        )
        headers = {"Accept": "application/json"}
        if self._use_auth:
            import base64
            creds = base64.b64encode(f"{self._username}:{self._password}".encode()).decode()
            headers["Authorization"] = f"Basic {creds}"

        resp = self._http_get(url, headers=headers, timeout=25.0)
        if resp is None:
            return None
        try:
            return resp.json()
        except Exception as exc:
            logger.warning("OpenSky JSON parse failed: %s", exc)
            return None

    @staticmethod
    def _nearest_airport(lat: float, lon: float) -> tuple[Optional[str], float]:
        import math
        best_icao = None
        best_dist = float("inf")
        for icao, info in _KENYA_AIRPORTS.items():
            dlat = math.radians(lat - info["lat"])
            dlon = math.radians(lon - info["lon"])
            a = (math.sin(dlat / 2) ** 2 +
                 math.cos(math.radians(info["lat"])) * math.cos(math.radians(lat)) *
                 math.sin(dlon / 2) ** 2)
            dist = 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            if dist < best_dist:
                best_dist = dist
                best_icao = icao
        return best_icao, best_dist

    def _fallback_data(self) -> list[dict]:
        """Return static airport records when OpenSky is unreachable."""
        records: list[dict] = []
        for icao, info in _KENYA_AIRPORTS.items():
            records.append({
                "asset_id": f"APT-{icao}",
                "infrastructure_type": "airports",
                "ward": info["city"],
                "lat": info["lat"],
                "lon": info["lon"],
                "value": 0,
                "capacity": 50,
                "unit": "flights_per_hour",
                "timestamp": datetime.now(timezone.utc),
                "source": "opensky_fallback",
                "is_mock": True,
                "raw_payload": {"airport_icao": icao, "airport_name": info["name"], "reason": "opensky_unavailable"},
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
                logger.error("OpenSky DB insert failed: %s", exc)

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
