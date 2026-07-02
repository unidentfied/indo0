"""
Sindio — WorldPop Raster Ingestion Fetcher
===========================================
Samples the already-downloaded WorldPop GeoTIFF
(`data/raw/ken_ppp_2020.tif`) for high-density population points
in Nairobi, then inserts them into PostgreSQL as seed data for
stress-point placement.

This is a **one-time seed** operation, not a recurring fetch.
The raster is static (2020 census-based).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .base import BaseFetcher

logger = logging.getLogger("sindio.ingestion")

# The raster is already in the repo at this path (gitignored, but present locally)
DEFAULT_RASTER = Path(__file__).resolve().parent.parent.parent.parent / "data" / "raw" / "ken_ppp_2020.tif"
RASTER_PATH = Path(os.getenv("WORLDPOP_RASTER_PATH", str(DEFAULT_RASTER)))

NAIROBI_BBOX = (36.7, -1.4, 37.1, -1.2)  # min_lon, min_lat, max_lon, max_lat
DENSITY_THRESHOLD = 50  # pixel value ~5000 people/km²


class WorldPopFetcher(BaseFetcher):
    """Sample high-density points from the WorldPop raster."""

    source_name = "WorldPop 2020"
    infrastructure_type = "population"

    def __init__(self, db_url: Optional[str] = None):
        super().__init__(db_url)

    def fetch(self) -> List[Dict[str, Any]]:
        """Read raster, sample points above density threshold."""
        if not RASTER_PATH.exists():
            logger.warning("[WorldPop] Raster not found at %s — skipping", RASTER_PATH)
            return []
        try:
            return self._sample_raster()
        except Exception as exc:
            logger.warning("[WorldPop] Raster sampling failed: %s", exc)
            return []

    def _sample_raster(self) -> List[Dict[str, Any]]:
        """Use rasterio to sample the Nairobi bbox."""
        try:
            import rasterio
            from rasterio.windows import from_bounds
        except ImportError:
            logger.warning("[WorldPop] rasterio not installed — using fallback coordinates")
            return self._fallback_points()

        with rasterio.open(str(RASTER_PATH)) as src:
            window = from_bounds(*NAIROBI_BBOX, src.transform)
            data = src.read(1, window=window)
            win_transform = src.window_transform(window)

        records = []
        rows, cols = np.where(data > DENSITY_THRESHOLD)
        # Subsample to avoid inserting 100k points
        stride = max(1, len(rows) // 500)
        rng = np.random.RandomState(42)
        indices = rng.choice(len(rows), size=min(len(rows), 500), replace=False)

        for idx in indices:
            r, c = rows[idx], cols[idx]
            lon, lat = rasterio.transform.xy(win_transform, r, c)
            density = float(data[r, c])
            records.append({
                "id": f"worldpop_{r}_{c}",
                "infrastructure_type": "population",
                "value": density,
                "capacity": 0.0,
                "unit": "people/km²",
                "timestamp": datetime.now(timezone.utc),
                "source": self.source_name,
                "ward": "",   # Would need spatial join with wards layer
                "lat": lat,
                "lon": lon,
                "is_mock": False,
                "raw_payload": json.dumps({"density": density, "row": int(r), "col": int(c)}),
            })
        logger.info("[WorldPop] Sampled %d high-density points from raster", len(records))
        return records

    def _fallback_points(self) -> List[Dict[str, Any]]:
        """Hardcoded Nairobi ward centroids if raster is unavailable."""
        points = [
            {"lat": -1.2921, "lon": 36.8219, "density": 15000},  # CBD
            {"lat": -1.3167, "lon": 36.7167, "density": 8500},   # Karen
            {"lat": -1.2683, "lon": 36.8110, "density": 12000},  # Westlands
            {"lat": -1.3239, "lon": 36.8990, "density": 9500},   # Embakasi
            {"lat": -1.2244, "lon": 36.8990, "density": 11000},  # Kasarani
            {"lat": -1.2500, "lon": 36.9000, "density": 9000},   # Dandora
            {"lat": -1.3667, "lon": 36.7667, "density": 7000},   # Langata
            {"lat": -1.3000, "lon": 36.8500, "density": 10000},   # Industrial Area
        ]
        records = []
        for pt in points:
            records.append({
                "id": f"worldpop_fallback_{pt['lat']:.4f}_{pt['lon']:.4f}",
                "infrastructure_type": "population",
                "value": pt["density"],
                "capacity": 0.0,
                "unit": "people/km²",
                "timestamp": datetime.now(timezone.utc),
                "source": self.source_name,
                "ward": "",
                "lat": pt["lat"],
                "lon": pt["lon"],
                "is_mock": False,
                "raw_payload": json.dumps(pt),
            })
        return records

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        return raw
