"""Sindio — HERE Traffic Fetcher (real-time road traffic flow for Nairobi).

HERE Technologies provides real-time traffic data via their Traffic API.
Free tier: 250,000 requests/month (sufficient for hourly polling of ~50 road segments).

API: https://developer.here.com/products/traffic
Endpoints:
  - Flow: GET https://traffic.ls.hereapi.com/traffic/6.2/flow.json
  - Incidents: GET https://traffic.ls.hereapi.com/traffic/6.2/incidents.json

Requires HERE_API_KEY environment variable.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..base import BaseFetcher, FetcherResult

logger = logging.getLogger("sindio.ingestion.here_traffic")

_HERE_FLOW_URL = "https://traffic.ls.hereapi.com/traffic/6.2/flow.json"
_HERE_INCIDENTS_URL = "https://traffic.ls.hereapi.com/traffic/6.2/incidents.json"

# Nairobi major road segments (TMC codes or lat/lon bounding boxes)
# Using lat/lon boxes for major arterials
_NAIROBI_ROAD_SEGMENTS: list[dict[str, Any]] = [
    {"id": "MOM-001", "name": "Mombasa Road (CBD → JKIA)", "bbox": "36.82,-1.30,36.95,-1.32", "type": "primary"},
    {"id": "THK-001", "name": "Thika Road (CBD → Kasarani)", "bbox": "36.82,-1.27,36.93,-1.20", "type": "primary"},
    {"id": "WYK-001", "name": "Waiyaki Way (CBD → Westlands)", "bbox": "36.78,-1.27,36.70,-1.25", "type": "primary"},
    {"id": "NGG-001", "name": "Ngong Road (CBD → Karen)", "bbox": "36.77,-1.30,36.73,-1.38", "type": "primary"},
    {"id": "JGO-001", "name": "Jogoo Road (CBD → Buruburu)", "bbox": "36.85,-1.30,36.90,-1.28", "type": "primary"},
    {"id": "LNG-001", "name": "Langata Road (CBD → Langata)", "bbox": "36.80,-1.30,36.73,-1.38", "type": "primary"},
    {"id": "KRB-001", "name": "Kiambu Road (Parklands → Kiambu)", "bbox": "36.82,-1.27,36.83,-1.20", "type": "primary"},
    {"id": "ELD-001", "name": "Eldoret Road (Industrial Area)", "bbox": "36.84,-1.31,36.87,-1.32", "type": "secondary"},
    {"id": "NGR-001", "name": "Ngara Road (CBD → Parklands)", "bbox": "36.81,-1.28,36.80,-1.26", "type": "secondary"},
    {"id": "OUT-001", "name": "Outer Ring Road (Eastlands loop)", "bbox": "36.87,-1.30,36.90,-1.25", "type": "primary"},
    {"id": "MBA-001", "name": "Mbagathi Way (CBD → Rongai)", "bbox": "36.77,-1.30,36.74,-1.40", "type": "secondary"},
    {"id": "KBS-001", "name": "Kibera Drive (Ngong Rd → Kibera)", "bbox": "36.77,-1.30,36.78,-1.32", "type": "tertiary"},
]


class HERE_TrafficFetcher(BaseFetcher):
    """Fetches real-time traffic flow data from HERE Technologies.

    Data returned per road segment:
      - Speed: current average speed (km/h)
      - FreeFlow: typical uncongested speed (km/h)
      - JamFactor: 0-10 congestion scale
      - Confidence: data quality (0.0-1.0)
      - RoadClosure: boolean

    Authentication: HERE_API_KEY environment variable (free tier available).
    """

    source_name = "HERE Traffic"
    infrastructure_type = "roads"
    default_capacity = 80.0
    default_unit = "km/h"

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)
        self._api_key = os.getenv("HERE_API_KEY", "")
        if not self._api_key:
            logger.warning("HERE_API_KEY not set — traffic fetcher will use fallback data")

    def fetch(self) -> list[dict[str, Any]]:
        if not self._api_key:
            return self._fallback_data()

        records: list[dict] = []
        for segment in _NAIROBI_ROAD_SEGMENTS:
            flow = self._fetch_flow(segment)
            if flow:
                records.extend(flow)
            incidents = self._fetch_incidents(segment)
            if incidents:
                records.extend(incidents)
            time.sleep(0.2)  # Rate limit: 5 req/sec

        logger.info("HERE: %d traffic records", len(records))
        return records if records else self._fallback_data()

    def _fetch_flow(self, segment: dict) -> list[dict]:
        params = {
            "apiKey": self._api_key,
            "bbox": segment["bbox"],
            "responseattributes": "sh,fc",
        }
        resp = self._http_get(_HERE_FLOW_URL, params=params, timeout=15.0)
        if resp is None:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        records: list[dict] = []
        for rsi in data.get("RWS", []):
            for rw in rsi.get("RW", []):
                for fis in rw.get("FIS", []):
                    for fi in fis.get("FI", []):
                        # Extract current and free-flow speeds
                        cf = fi.get("CF", [])
                        current_speed = 0
                        free_flow = 0
                        jam_factor = 0
                        confidence = 0
                        for c in cf:
                            if c.get("TY") == "FF":
                                free_flow = c.get("SP", 0)
                            elif c.get("TY") == "SU":
                                current_speed = c.get("SP", 0)
                                jam_factor = c.get("JF", 0)
                                confidence = c.get("CN", 0)

                        # Parse shape points for centroid
                        shp = fi.get("SHP", [])
                        if shp:
                            coords = shp[0].get("value", [])
                            if coords:
                                lat_lon = coords[0].split(",")
                                lat = float(lat_lon[0])
                                lon = float(lat_lon[1])
                            else:
                                lat, lon = 0, 0
                        else:
                            # Use bbox center
                            bbox_parts = segment["bbox"].split(",")
                            lon = (float(bbox_parts[0]) + float(bbox_parts[2])) / 2
                            lat = (float(bbox_parts[1]) + float(bbox_parts[3])) / 2

                        # Compute congestion as inverse of speed ratio
                        congestion = 0.0
                        if free_flow > 0:
                            congestion = max(0, min(1, 1.0 - (current_speed / free_flow)))

                        records.append({
                            "asset_id": f"HERE-{segment['id']}",
                            "infrastructure_type": "roads",
                            "ward": segment["name"],
                            "lat": lat,
                            "lon": lon,
                            "value": round(congestion * 100, 1),
                            "capacity": free_flow if free_flow else 80,
                            "unit": "congestion_pct",
                            "timestamp": datetime.now(timezone.utc),
                            "source": "here_traffic_flow",
                            "is_mock": False,
                            "raw_payload": {
                                "road_name": segment["name"],
                                "current_speed_kmh": current_speed,
                                "free_flow_speed_kmh": free_flow,
                                "jam_factor": jam_factor,
                                "confidence": confidence,
                                "road_type": segment["type"],
                            },
                        })
        return records

    def _fetch_incidents(self, segment: dict) -> list[dict]:
        params = {
            "apiKey": self._api_key,
            "bbox": segment["bbox"],
        }
        resp = self._http_get(_HERE_INCIDENTS_URL, params=params, timeout=15.0)
        if resp is None:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        records: list[dict] = []
        for inc in data.get("TIM", {}).get("TI", []):
            lat = inc.get("LT", 0)
            lon = inc.get("LN", 0)
            desc = inc.get("DE", "")
            severity = inc.get("SU", 0)  # severity 0-4

            records.append({
                "asset_id": f"HERE-INC-{segment['id']}-{hash(desc) % 10000:04d}",
                "infrastructure_type": "roads",
                "ward": segment["name"],
                "lat": lat,
                "lon": lon,
                "value": severity,
                "capacity": 4,
                "unit": "incident_severity",
                "timestamp": datetime.now(timezone.utc),
                "source": "here_traffic_incidents",
                "is_mock": False,
                "raw_payload": {
                    "road_name": segment["name"],
                    "description": desc,
                    "severity": severity,
                },
            })
        return records

    def _fallback_data(self) -> list[dict]:
        """Generate realistic Nairobi traffic patterns when HERE API unavailable."""
        records: list[dict] = []
        import random
        hour = datetime.now(timezone.utc).hour + 3  # EAT

        for segment in _NAIROBI_ROAD_SEGMENTS:
            # Time-of-day congestion model for Nairobi
            base_congestion = 30.0
            if segment["type"] == "primary":
                if hour in (7, 8, 17, 18, 19):
                    base_congestion = 75.0
                elif hour in (9, 16):
                    base_congestion = 55.0
                elif hour in (12, 13):
                    base_congestion = 45.0
                else:
                    base_congestion = 25.0
            else:
                base_congestion = 20.0

            congestion = base_congestion + random.uniform(-5, 5)
            congestion = max(0, min(100, congestion))

            bbox_parts = segment["bbox"].split(",")
            lon = (float(bbox_parts[0]) + float(bbox_parts[2])) / 2
            lat = (float(bbox_parts[1]) + float(bbox_parts[3])) / 2

            records.append({
                "asset_id": f"HERE-{segment['id']}",
                "infrastructure_type": "roads",
                "ward": segment["name"],
                "lat": lat,
                "lon": lon,
                "value": round(congestion, 1),
                "capacity": 80.0,
                "unit": "congestion_pct",
                "timestamp": datetime.now(timezone.utc),
                "source": "here_traffic_fallback",
                "is_mock": True,
                "raw_payload": {
                    "road_name": segment["name"],
                    "estimated_congestion_pct": round(congestion, 1),
                    "time_of_day_eat": hour,
                    "method": "nairobi_traffic_model",
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
