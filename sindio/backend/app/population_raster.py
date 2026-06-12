"""
Download and sample WorldPop population density raster for Nairobi.

Identifies high-density zones (>5000 people/km) for realistic stress-point placement.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

logger = logging.getLogger("sindio.population_raster")

NAIROBI_BBOX = (36.7, -1.4, 37.1, -1.2)  # min_lon, min_lat, max_lon, max_lat
WORLDPOP_URL = (
    "https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/KEN/"
    "ken_ppp_2020.tif"
)
CACHE_DIR = Path(os.getenv("DATA_RAW_DIR", "data/raw"))
RASTER_CACHE_PATH = CACHE_DIR / "ken_ppp_2020.tif"

DENSITY_THRESHOLD = 50  # pixel value (people per ~0.01 km²), ~5000 people/km²
PIXEL_AREA_KM2 = 0.01  # approx area per 3-arcsec pixel at latitude -1.3°

# Set SINDIO_SKIP_RASTER=1 to use hardcoded fallback points instead of downloading
# the 297 MB WorldPop GeoTIFF. Useful for quick frontend development.
SKIP_RASTER = os.getenv("SINDIO_SKIP_RASTER", "").lower() in ("1", "true", "yes")


def _get_raster_path() -> Path:
    """Return the cached raster path, downloading if necessary."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if RASTER_CACHE_PATH.exists():
        return RASTER_CACHE_PATH

    import httpx

    logger.info("Downloading WorldPop raster (%s)", WORLDPOP_URL)
    with httpx.stream("GET", WORLDPOP_URL, timeout=300) as resp:
        resp.raise_for_status()
        with open(str(RASTER_CACHE_PATH), "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=4 * 1024 * 1024):
                f.write(chunk)
    logger.info("Cached raster at %s", RASTER_CACHE_PATH)
    return RASTER_CACHE_PATH


def sample_high_density_points(
    density_threshold: float = DENSITY_THRESHOLD,
    max_points: int = 150,
    random_seed: int = 42,
) -> list[dict]:
    """
    Sample points from the WorldPop raster where population density exceeds
    *density_threshold* (raw pixel value; 50  ~5000 people/km²).

    Returns a list of dicts with ``lat``, ``lng``, ``density`` (people/km²).
    """
    if SKIP_RASTER:
        logger.info("SINDIO_SKIP_RASTER set — using fallback points")
        return _fallback_points(max_points, random_seed)

    try:
        import rasterio
        from rasterio.windows import from_bounds, Window, transform as win_transform_fn
    except ImportError:
        logger.info("rasterio not installed — using fallback points")
        return _fallback_points(max_points, random_seed)

    try:
        path = _get_raster_path()
    except Exception as exc:
        logger.warning("Cannot load population raster (%s) — using fallback points", exc)
        return _fallback_points(max_points, random_seed)

    rng = np.random.RandomState(random_seed)

    try:
        with rasterio.open(path) as src:
            min_lon, min_lat, max_lon, max_lat = NAIROBI_BBOX
            win = from_bounds(min_lon, min_lat, max_lon, max_lat, src.transform)
            win = win.round_lengths(op="ceil").round_offsets()
            win = win.intersection(Window(0, 0, src.width, src.height))
            transform = win_transform_fn(win, src.transform)

            if win.width < 1 or win.height < 1:
                logger.warning("Nairobi bbox lies outside raster extent — using fallback")
                return _fallback_points(max_points, random_seed)

            data = src.read(1, window=win)

            rows, cols = np.where(data > density_threshold)
            count = len(rows)

            if count == 0:
                logger.warning(
                    "No pixels with density > %.0f in Nairobi window — using fallback",
                    density_threshold,
                )
                return _fallback_points(max_points, random_seed)

            if count > max_points:
                indices = rng.choice(count, size=max_points, replace=False)
                rows = rows[indices]
                cols = cols[indices]

            points: list[dict] = []
            for r, c in zip(rows, cols):
                lng, lat = rasterio.transform.xy(transform, r, c, offset="center")
                density_km2 = float(data[r, c]) / PIXEL_AREA_KM2
                points.append({
                    "lat": round(float(lat), 6),
                    "lng": round(float(lng), 6),
                    "density": round(density_km2, 1),
                })

        logger.info("Sampled %d high-density points from WorldPop raster", len(points))
        return points
    except Exception as exc:
        logger.warning("Failed to read population raster (%s) — using fallback points", exc)
        return _fallback_points(max_points, random_seed)


# ---------------------------------------------------------------------------
# Fallback — hardcoded high-density Nairobi coordinates
# ---------------------------------------------------------------------------

_FALLBACK_POINTS: list[dict] = [
    {"lat": -1.2833, "lng": 36.8219, "density": 12500},
    {"lat": -1.2900, "lng": 36.7850, "density": 9800},
    {"lat": -1.2975, "lng": 36.8122, "density": 8600},
    {"lat": -1.2670, "lng": 36.8090, "density": 7200},
    {"lat": -1.3200, "lng": 36.8500, "density": 8800},
    {"lat": -1.2700, "lng": 36.8580, "density": 14400},
    {"lat": -1.3050, "lng": 36.8280, "density": 10500},
    {"lat": -1.2750, "lng": 36.8350, "density": 11200},
    {"lat": -1.3100, "lng": 36.8000, "density": 7600},
    {"lat": -1.2600, "lng": 36.8000, "density": 6800},
    {"lat": -1.2900, "lng": 36.8400, "density": 9200},
    {"lat": -1.3300, "lng": 36.8100, "density": 6400},
    {"lat": -1.2850, "lng": 36.7900, "density": 9100},
    {"lat": -1.2950, "lng": 36.8500, "density": 11500},
    {"lat": -1.2720, "lng": 36.8150, "density": 8300},
    {"lat": -1.3150, "lng": 36.8350, "density": 7100},
    {"lat": -1.2800, "lng": 36.8050, "density": 10200},
    {"lat": -1.3400, "lng": 36.8200, "density": 5900},
    {"lat": -1.2650, "lng": 36.8250, "density": 7800},
    {"lat": -1.3000, "lng": 36.8600, "density": 9700},
]


def _fallback_points(max_points: int, random_seed: int) -> list[dict]:
    """Return a subset of hardcoded high-density Nairobi points."""
    rng = np.random.RandomState(random_seed)
    size = min(max_points, len(_FALLBACK_POINTS))
    indices = rng.choice(len(_FALLBACK_POINTS), size=size, replace=False)
    return [_FALLBACK_POINTS[i] for i in indices]
