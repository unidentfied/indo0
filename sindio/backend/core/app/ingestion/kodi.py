"""
Sindio — Kenya Open Data Initiative (KODI) Fetcher
====================================================
Downloads Nairobi infrastructure datasets from the Kenya Open Data portal
(opendata.go.ke) and the Nairobi Open Data portal (opendata.nairobi.go.ke).

Datasets targeted:
- Ward boundaries (geometry)
- Road network segments
- Power distribution / substations
- Water mains / supply zones
- Health facility locations (proxy for population service demand)

Note: Many KODI endpoints are CSV/GeoJSON downloads rather than live APIs.
This fetcher treats them as static bulk imports that seed the asset registry.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from .base import BaseFetcher

logger = logging.getLogger("sindio.ingestion")

# Known dataset IDs / URLs on Nairobi Open Data portal.
# If the live portal is down, falls back to local cached copies
# in data/raw/ (downloaded on first successful fetch).
NAIROBI_DATASETS = {
    "wards": "https://opendata.nairobi.go.ke/datasets/nairobi-wards-boundaries/download/wards.geojson",
    "roads": "https://opendata.nairobi.go.ke/datasets/road-network/download/road_segments.geojson",
    "power_lines": "https://opendata.nairobi.go.ke/datasets/power-distribution-lines/download/power_lines.geojson",
    "water_mains": "https://opendata.nairobi.go.ke/datasets/water-mains-network/download/water_mains.geojson",
}

# Mirror / fallback URLs — Kenya Open Data CKAN API (national level)
KODI_MIRROR_BASE = "https://opendata.go.ke"
KODI_FALLBACKS = {
    "roads": f"{KODI_MIRROR_BASE}/dataset/road-network/resource/download/road_segments.geojson",
    "power_lines": f"{KODI_MIRROR_BASE}/dataset/power-lines/resource/download/power_lines.geojson",
    "water_mains": f"{KODI_MIRROR_BASE}/dataset/water-mains/resource/download/water_mains.geojson",
}

# Kenya Open Data (national) — CSV-based CKAN API
KODI_BASE = "https://opendata.go.ke"
KODI_API = f"{KODI_BASE}/api/3/action"


class KenyaOpenDataFetcher(BaseFetcher):
    """Bulk-fetch Nairobi infrastructure assets from Open Data portals."""

    source_name = "Kenya Open Data Initiative"
    infrastructure_type = "mixed"   # seeds power, water, roads assets

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)
        self._datasets_to_fetch: List[str] = ["roads", "power_lines", "water_mains"]

    def fetch(self) -> List[Dict[str, Any]]:
        """Download GeoJSON files and return flattened feature records."""
        all_records: List[Dict[str, Any]] = []
        for key in self._datasets_to_fetch:
            url = NAIROBI_DATASETS.get(key)
            if not url:
                continue
            records = self._fetch_geojson_dataset(key, url)
            if records:
                all_records.extend(records)
                logger.info("[KODI] %s: %d records", key, len(records))
        return all_records

    def _fetch_geojson_dataset(self, key: str, url: str) -> List[Dict[str, Any]]:
        """Download GeoJSON, with local-cache and mirror fallback."""
        # 1. Check local cache first
        from pathlib import Path
        tmp = Path("/tmp") / f"kodi_{key}.geojson"
        if tmp.exists():
            return self._parse_geojson(key, tmp)

        # 2. Try primary URL
        content = None
        resp = self._http_get(url, timeout=60)
        if resp is not None:
            content = resp.content

        # 3. Try mirror fallback
        if content is None and key in KODI_FALLBACKS:
            mirror_url = KODI_FALLBACKS[key]
            resp = self._http_get(mirror_url, timeout=60)
            if resp is not None:
                content = resp.content

        if content is None:
            return []

        tmp.write_bytes(content)
        return self._parse_geojson(key, tmp)

    def _parse_geojson(self, key: str, path: Path) -> List[Dict[str, Any]]:
        """Parse a cached GeoJSON file into normalised records."""
        try:
            import geopandas as gpd
            from shapely.geometry import Point
            gdf = gpd.read_file(str(path))
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")
            gdf = gdf.to_crs("EPSG:32737")

            records = []
            for _, row in gdf.iterrows():
                geom = row.geometry
                if geom is None or geom.is_empty:
                    continue
                if geom.geom_type in ("LineString", "MultiLineString"):
                    center = Point(geom.centroid.x, geom.centroid.y)
                else:
                    center = geom.centroid if hasattr(geom, "centroid") else Point(0, 0)

                infra_map = {"roads": "roads", "power_lines": "power", "water_mains": "water"}
                infra_type = infra_map.get(key, key)

                records.append({
                    "id": f"kodi_{key}_{row.get('OBJECTID', row.get('id', len(records)))}",
                    "infrastructure_type": infra_type,
                    "value": 0.0,   # static asset — no live reading
                    "capacity": float(row.get("capacity", row.get("CAPACITY", 0))) or 100.0,
                    "unit": "segment",
                    "timestamp": datetime.now(timezone.utc),
                    "source": self.source_name,
                    "ward": str(row.get("WARD", row.get("ward", ""))),
                    "lat": center.y,
                    "lon": center.x,
                    "is_mock": False,
                    "raw_payload": json.dumps({k: str(v) for k, v in row.items() if k != "geometry"})[:4096],
                })
            return records
        except Exception as exc:
            logger.warning("[KODI] Failed to fetch %s: %s", key, exc)
            return []

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        return raw  # Already normalised in fetch()
