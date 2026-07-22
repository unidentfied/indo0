"""Sindio — OpenStreetMap Overpass API Fetcher (roads, sidewalks, buildings, POIs)."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseFetcher, FetcherResult

logger = logging.getLogger("sindio.ingestion.osm")

_NAIROBI_BBOX_OSM = "-1.45,36.65,-1.15,37.00"
_OVERPASS_URL = os.getenv("OVERPASS_API_URL", "https://overpass-api.de/api/interpreter")
_OVERPASS_KUMI = os.getenv("OVERPASS_KUMI_URL", "https://overpass.kumi.systems/api/interpreter")

_ROAD_QUERIES: dict[str, str] = {
    "roads_primary": f'way["highway"="primary"]({_NAIROBI_BBOX_OSM});(._;>;);',
    "roads_secondary": f'way["highway"="secondary"]({_NAIROBI_BBOX_OSM});(._;>;);',
    "roads_tertiary": f'way["highway"="tertiary"]({_NAIROBI_BBOX_OSM});(._;>;);',
    "roads_residential": f'way["highway"="residential"]({_NAIROBI_BBOX_OSM});(._;>;);',
    "sidewalks": f'way["highway"="footway"]{_NAIROBI_BBOX_OSM};way["sidewalk"]{_NAIROBI_BBOX_OSM};(._;>;);',
    "power_lines": f'way["power"="line"]{_NAIROBI_BBOX_OSM};way["power"="minor_line"]{_NAIROBI_BBOX_OSM};(._;>;);',
    "power_substations": f'node["power"="substation"]{_NAIROBI_BBOX_OSM};node["power"="transformer"]{_NAIROBI_BBOX_OSM};',
    "water_pipes": f'way["man_made"="pipeline"]{_NAIROBI_BBOX_OSM};way["pipeline"]{_NAIROBI_BBOX_OSM};(._;>;);',
    "water_towers": f'node["man_made"="water_tower"]{_NAIROBI_BBOX_OSM};node["water_tower"]{_NAIROBI_BBOX_OSM};',
    "waste_facilities": f'node["amenity"="waste_disposal"]{_NAIROBI_BBOX_OSM};node["amenity"="recycling"]{_NAIROBI_BBOX_OSM};',
    "rail_lines": f'way["railway"="rail"]{_NAIROBI_BBOX_OSM};way["railway"="light_rail"]{_NAIROBI_BBOX_OSM};(._;>;);',
    "rail_stations": f'node["railway"="station"]{_NAIROBI_BBOX_OSM};node["railway"="halt"]{_NAIROBI_BBOX_OSM};node["public_transport"="station"]{_NAIROBI_BBOX_OSM};',
    "airport_infra": f'way["aeroway"]{_NAIROBI_BBOX_OSM};node["aeroway"]{_NAIROBI_BBOX_OSM};(._;>;);',
    "buildings": f'way["building"]{_NAIROBI_BBOX_OSM};relation["building"]{_NAIROBI_BBOX_OSM};',
}

_OSM_TO_INFRA_TYPE: dict[str, str] = {
    "roads_primary": "roads",
    "roads_secondary": "roads",
    "roads_tertiary": "roads",
    "roads_residential": "roads",
    "sidewalks": "sidewalks",
    "power_lines": "power",
    "power_substations": "power",
    "water_pipes": "water",
    "water_towers": "water",
    "waste_facilities": "solid_waste",
    "rail_lines": "lrt",
    "rail_stations": "lrt",
    "airport_infra": "airports",
    "buildings": "roads",
}

_NAIROBI_WARDS_OSM = [
    "Kilimani", "Upper Hill", "CBD", "Westlands", "Industrial Area",
    "Eastleigh", "Karen", "Parklands", "Langata", "Ngong Road",
    "Kibera", "South B", "South C", "Donholm", "Embakasi",
    "Ruaraka", "Kasarani", "Dagoretti", "Mathare", "Huruma",
]


class OSMFetcher(BaseFetcher):
    """Fetches real Nairobi infrastructure data from OpenStreetMap Overpass API.

    Maps OSM tags to Sindio infrastructure types and generates asset asset
    records suitable for the monitor/ingestion pipeline.

    Caches responses locally in /tmp/osm_cache/ for 24 hours.
    """

    source_name = "OpenStreetMap"
    infrastructure_type = "roads"
    default_capacity = 100.0
    default_unit = "count"

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)
        self._cache_dir = "/tmp/osm_cache"
        self._overpass_url = os.getenv("OVERPASS_API_URL", _OVERPASS_URL)
        self._overpass_fallback = _OVERPASS_KUMI
        os.makedirs(self._cache_dir, exist_ok=True)

    def fetch(self) -> list[dict[str, Any]]:
        records: list[dict] = []
        for query_key, query_str in _ROAD_QUERIES.items():
            infra_type = _OSM_TO_INFRA_TYPE.get(query_key, "roads")
            elements = self._fetch_cached(query_key, query_str)
            parsed = self._parse_elements(elements, query_key, infra_type)
            records.extend(parsed)
            if parsed:
                logger.info("OSM %s: %d elements parsed → %d records", query_key, len(elements), len(parsed))
            time.sleep(0.3)  # Rate limit: respect Overpass fair-use (~3 req/s)

        logger.info("OSM total: %d records across %d queries", len(records), len(_ROAD_QUERIES))
        return records

    # ── Cache layer (24h TTL) ─────────────────────────────────────

    def _fetch_cached(self, key: str, query: str) -> list[dict]:
        import json as _json
        cache_path = f"{self._cache_dir}/{key}.json"
        if os.path.exists(cache_path):
            try:
                mtime = os.path.getmtime(cache_path)
                if time.time() - mtime < 86400:
                    with open(cache_path) as f:
                        cached = _json.load(f)
                    if isinstance(cached, list):
                        logger.debug("OSM cache hit: %s (%d elements)", key, len(cached))
                        return cached
            except Exception:
                pass

        elements = self._fetch_overpass(query)
        if elements:
            try:
                with open(cache_path, "w") as f:
                    _json.dump(elements, f)
            except Exception:
                pass
        return elements

    # ── Overpass API ───────────────────────────────────────────────

    def _fetch_overpass(self, query: str) -> list[dict]:
        full_query = f"[out:json][timeout:60];({query})out geom;"
        for url in (self._overpass_url, self._overpass_fallback):
            try:
                resp = self._http_post(url, body=full_query, timeout=90.0)
                elements = resp.get("elements", [])
                if elements:
                    logger.debug("Overpass response: %d elements from %s", len(elements), url)
                    return elements
            except Exception as exc:
                logger.warning("Overpass %s failed: %s", url, exc)
                time.sleep(1.0)

        logger.warning("All Overpass endpoints failed for query")
        return []

    # ── Parse elements → Sindio records ────────────────────────────

    def _parse_elements(self, elements: list[dict], query_key: str, infra_type: str) -> list[dict]:
        if not elements:
            return []

        records: list[dict] = []
        for elem in elements:
            etype = elem.get("type", "")
            if etype == "node":
                lat = elem.get("lat", 0.0)
                lon = elem.get("lon", 0.0)
                node_id = elem.get("id", 0)
            elif etype == "way" and elem.get("center"):
                lat = elem["center"]["lat"]
                lon = elem["center"]["lon"]
                node_id = elem.get("id", 0)
            else:
                continue

            tags = elem.get("tags", {})
            capacity = self._estimate_capacity(elem, infra_type)
            ward = self._nearest_ward(lat, lon)

            records.append({
                "asset_id": f"OSM-{etype}-{node_id}",
                "infrastructure_type": infra_type,
                "ward": ward,
                "lat": lat,
                "lon": lon,
                "value": 0.0,
                "capacity": capacity,
                "unit": self.default_unit,
                "timestamp": datetime.now(timezone.utc),
                "source": f"osm_{query_key}",
                "is_mock": False,
                "raw_payload": {
                    "osm_id": node_id,
                    "osm_type": etype,
                    "tags": tags,
                    "length_m": self._way_length(elem),
                    "name": tags.get("name", ""),
                },
            })
        return records

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _way_length(elem: dict) -> float:
        """Approximate way length from geometry nodes (meters)."""
        geom = elem.get("geometry", [])
        if len(geom) < 2:
            return 0.0
        import math
        total = 0.0
        for i in range(len(geom) - 1):
            lat1, lon1 = math.radians(geom[i]["lat"]), math.radians(geom[i]["lon"])
            lat2, lon2 = math.radians(geom[i + 1]["lat"]), math.radians(geom[i + 1]["lon"])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            total += 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return total

    @staticmethod
    def _estimate_capacity(elem: dict, infra_type: str) -> float:
        tags = elem.get("tags", {})
        if infra_type == "power":
            return 50.0
        elif infra_type == "water":
            return 100.0
        elif infra_type == "roads":
            lanes = int(tags.get("lanes", 2))
            hwy = tags.get("highway", "")
            multiplier = {"motorway": 3.0, "trunk": 2.5, "primary": 2.0, "secondary": 1.5, "tertiary": 1.0, "residential": 0.5}.get(hwy, 0.3)
            return max(10.0, lanes * multiplier * 1000.0)
        elif infra_type == "lrt":
            return 24.0
        elif infra_type == "airports":
            return 100.0
        return 10.0

    @staticmethod
    def _nearest_ward(lat: float, lon: float) -> str:
        """Assign OSM element to nearest Nairobi ward by proximity heuristic."""
        _WARD_CENTROIDS = {
            "Kilimani": (-1.286, 36.787),
            "Upper Hill": (-1.296, 36.812),
            "CBD": (-1.286, 36.823),
            "Westlands": (-1.267, 36.804),
            "Industrial Area": (-1.313, 36.847),
            "Eastleigh": (-1.268, 36.850),
            "Karen": (-1.378, 36.726),
            "Parklands": (-1.258, 36.818),
            "Langata": (-1.368, 36.746),
            "Ngong Road": (-1.302, 36.774),
            "Kibera": (-1.313, 36.780),
            "South B": (-1.316, 36.838),
            "South C": (-1.327, 36.832),
            "Donholm": (-1.294, 36.887),
            "Embakasi": (-1.315, 36.900),
        }
        import math
        best_ward = "Unknown"
        best_dist = float("inf")
        for name, (wlat, wlon) in _WARD_CENTROIDS.items():
            d = math.sqrt((lat - wlat) ** 2 + (lon - wlon) ** 2)
            if d < best_dist:
                best_dist = d
                best_ward = name
        return best_ward

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
                logger.error("OSM DB insert failed: %s", exc)

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
