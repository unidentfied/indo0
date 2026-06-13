"""
Sindio — Geospatial Ingestion Pipeline
=======================================
Downloads / loads Nairobi infrastructure shapefiles (water mains, power
lines, road segments), normalises to EPSG:32737, validates geometries,
and upserts into PostGIS `infrastructure_assets`.

Idempotent: skips sources whose SHA-256 hash is unchanged since last
ingestion.

Usage:  python -m app.services.ingest_geospatial [--force]
"""

from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import geopandas as gpd
import httpx
import pandas as pd
from dotenv import load_dotenv
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge
from shapely.validation import make_valid

load_dotenv()

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────
TARGET_CRS = "EPSG:32737"  # UTM zone 37S (Nairobi)
LOG_DIR = Path("/var/log/sindio")
LOG_PATH = LOG_DIR / "ingestion.log"
DEFAULT_CACHE_DIR = Path(os.getenv("DATA_RAW_DIR", "data/raw"))
HASH_STORE = DEFAULT_CACHE_DIR / ".ingestion_hashes.json"

# Open Nairobi / Kenya open-data portal base URLs
OPEN_NAIROBI_BASE = "https://opendata.nairobi.go.ke"
FALLBACK_URLS: Dict[str, List[str]] = {
    "water": [
        f"{OPEN_NAIROBI_BASE}/datasets/water-mains-network/download/water_mains.geojson",
    ],
    "power": [
        f"{OPEN_NAIROBI_BASE}/datasets/power-distribution-lines/download/power_lines.geojson",
    ],
    "roads": [
        f"{OPEN_NAIROBI_BASE}/datasets/road-network/download/road_segments.geojson",
    ],
}

# Wards dataset (for logging per-ward counts)
NAIROBI_WARDS_URL = (
    f"{OPEN_NAIROBI_BASE}/datasets/nairobi-wards-boundaries/download/wards.geojson"
)

# DB connection string (postgresql://user:pass@host:port/db)
DB_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
    f"{os.getenv('DB_PASSWORD', '')}@"
    f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
    f"{os.getenv('DB_NAME', 'sindio')}",
)

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("sindio.ingestion")
logger.setLevel(logging.INFO)

file_handler = logging.handlers.RotatingFileHandler(
    LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=5
)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")
)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def _load_hashes() -> Dict[str, str]:
    if HASH_STORE.exists():
        try:
            return json.loads(HASH_STORE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_hashes(data: Dict[str, str]) -> None:
    HASH_STORE.parent.mkdir(parents=True, exist_ok=True)
    HASH_STORE.write_text(json.dumps(data, indent=2))


def _sha256_of_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_file(url: str, dest: Path, timeout: int = 120) -> Optional[Path]:
    """Download `url` → `dest`, return path on success or None."""
    try:
        with httpx.Client(
            follow_redirects=True, timeout=timeout, verify=True
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            logger.info("Downloaded %s → %s (%d bytes)", url, dest, len(resp.content))
            return dest
    except Exception as exc:
        logger.warning("Download failed for %s: %s", url, exc)
        return None


def _repair_geometry(geom: Any) -> Optional[LineString]:
    """Make geometry valid; return a LineString or None."""
    if geom is None or getattr(geom, "is_empty", True):
        return None

    validated = make_valid(geom)

    if isinstance(validated, (LineString,)):
        return validated
    if isinstance(validated, (MultiLineString,)):
        merged = linemerge(validated)
        if isinstance(merged, (LineString,)):
            return merged
        if isinstance(merged, (MultiLineString,)):
            return merged.geoms[0]
    return None


# ──────────────────────────────────────────────────────────────
# Download / local fallback
# ──────────────────────────────────────────────────────────────


def _resolve_source(
    asset_type: str,
    local_cache: Optional[Path] = None,
) -> Optional[Path]:
    """Return a Path to a local GeoJSON for `asset_type`.

    Strategy: local_cache → FALLBACK_URLS → default cache dir.
    """
    # 1. Explicit local path
    if local_cache and local_cache.exists():
        return local_cache

    # 2. Check default cache
    cached = DEFAULT_CACHE_DIR / f"{asset_type}_network.geojson"
    if cached.exists():
        return cached

    # 3. Download from Open Nairobi
    urls = FALLBACK_URLS.get(asset_type, [])
    for url in urls:
        result = _download_file(url, cached)
        if result:
            return result

    logger.error("No source available for asset_type=%s", asset_type)
    return None


# ──────────────────────────────────────────────────────────────
# Core ingestion
# ──────────────────────────────────────────────────────────────


def load_gdf(asset_type: str, path: Path, force: bool = False) -> Optional[gpd.GeoDataFrame]:
    """Load and normalise a single asset type GeoDataFrame."""
    stored_hashes = _load_hashes()
    file_hash = _sha256_of_file(path)

    if not force and stored_hashes.get(asset_type) == file_hash:
        logger.info("[%s] Source unchanged (hash=%s…), skipped.", asset_type, file_hash[:12])
        return None

    stored_hashes[asset_type] = file_hash
    _save_hashes(stored_hashes)

    logger.info("[%s] Loading %s", asset_type, path)

    gdf = gpd.read_file(path)
    crs = gdf.crs
    if crs is None:
        logger.warning("[%s] CRS missing — assuming EPSG:4326", asset_type)
        gdf.set_crs("EPSG:4326", inplace=True)

    # Normalise to UTM 37S
    if gdf.crs != TARGET_CRS:
        gdf = gdf.to_crs(TARGET_CRS)

    # --- Geometry validation & repair ---
    gdf["geometry"] = gdf["geometry"].apply(_repair_geometry)
    gdf = gdf[gdf["geometry"].notna()].copy()

    if gdf.empty:
        logger.warning("[%s] No valid geometries after repair.", asset_type)
        return None

    # Drop self-intersecting / zero-length segments
    gdf["is_valid"] = gdf.geometry.apply(
        lambda g: g is not None and g.is_valid and g.length > 0 and not g.is_ring
    )
    invalid_count = (~gdf["is_valid"]).sum()
    if invalid_count > 0:
        logger.warning("[%s] Dropping %d invalid / zero-length segments.", asset_type, invalid_count)
    gdf = gdf[gdf["is_valid"]].drop(columns=["is_valid"])

    # --- Standardise columns ---
    capacity_map = {
        "water": ("L/s", 120.0),
        "power": ("kVA", 250.0),
        "roads":  ("veh/hr", 2000.0),
    }
    default_unit, default_value = capacity_map.get(asset_type, ("unknown", 0.0))

    gdf["capacity_value"] = (
        pd.to_numeric(gdf.get("capacity_value", gdf.get("capacity", gdf.get("CAPACITY", None))), errors="coerce")
        .fillna(default_value)
    )
    gdf["capacity_unit"] = gdf.get("capacity_unit", gdf.get("UNIT", default_unit)).fillna(default_unit)
    gdf["year_constructed"] = (
        pd.to_numeric(
            gdf.get("year_constructed", gdf.get("YR_BLT", gdf.get("YEAR_CONST", None))),
            errors="coerce",
        )
        .fillna(2005)
        .clip(1900, 2100)
        .astype(int)
    )
    gdf["last_maintenance"] = pd.to_datetime(
        gdf.get("last_maintenance", gdf.get("LAST_MAINT", gdf.get("LST_MTNC", None))),
        errors="coerce",
    )
    gdf["last_maintenance"] = gdf["last_maintenance"].fillna(
        pd.Timestamp.today().normalize() - pd.Timedelta(days=365)
    )
    gdf["source_name"] = gdf.get(
        "source_name",
        gdf.get("SOURCE", gdf.get("FULL_NAME", gdf.get("NAME", None))),
    ).fillna(f"{asset_type}_segment")

    logger.info("[%s] %d valid rows ready for upsert.", asset_type, len(gdf))
    return gdf


def _get_db_engine():
    """Lazy import + create SQLAlchemy engine."""
    try:
        from sqlalchemy import create_engine

        return create_engine(DB_URL)
    except Exception as exc:
        logger.error("Cannot connect to PostgreSQL: %s", exc)
        raise


def _upsert_gdf(gdf: gpd.GeoDataFrame, asset_type: str) -> int:
    """INSERT … ON CONFLICT DO NOTHING for Geometry rows.

    Uses the composite key (asset_type, source_name) UNIQUE index."""
    from sqlalchemy import text

    engine = _get_db_engine()

    rows = []
    for _, row in gdf.iterrows():
        rows.append({
            "asset_type": asset_type,
            "source_name": str(row.get("source_name", "")),
            "geometry_wkt": row.geometry.wkt,
            "capacity_value": row.get("capacity_value"),
            "capacity_unit": row.get("capacity_unit"),
            "year_constructed": int(row.get("year_constructed", 2005)),
            "last_maintenance": (
                row["last_maintenance"].date()
                if isinstance(row.get("last_maintenance"), (pd.Timestamp, datetime))
                else date.today()
            ),
        })

    count = 0
    upsert_sql = text("""
        INSERT INTO infrastructure_assets
            (asset_type, source_name, geometry, capacity_value, capacity_unit,
             year_constructed, last_maintenance, source_hash)
        VALUES
            (:asset_type, :source_name, ST_GeomFromText(:geometry_wkt, 32737),
             :capacity_value, :capacity_unit, :year_constructed,
             :last_maintenance, :source_hash)
        ON CONFLICT (asset_type, source_name) DO NOTHING
    """)

    with engine.begin() as conn:
        source_hash = _sha256_of_bytes(
            json.dumps([r["source_name"] for r in rows]).encode()
        )
        for r in rows:
            params = {**r, "source_hash": source_hash}
            result = conn.execute(upsert_sql, params)
            count += result.rowcount if result.rowcount else 0

    logger.info("[%s] Upserted %d / %d rows.", asset_type, count, len(rows))
    return count


# ──────────────────────────────────────────────────────────────
# Per-ward logging
# ──────────────────────────────────────────────────────────────


def _load_wards() -> Optional[gpd.GeoDataFrame]:
    cached = DEFAULT_CACHE_DIR / "nairobi_wards.geojson"
    if not cached.exists():
        _download_file(NAIROBI_WARDS_URL, cached)
    if not cached.exists():
        logger.warning("Wards file not available; per-ward counts skipped.")
        return None

    wards = gpd.read_file(cached)
    if wards.crs != TARGET_CRS:
        wards = wards.to_crs(TARGET_CRS)
    return wards


def _count_per_ward(
    gdf: gpd.GeoDataFrame, wards: gpd.GeoDataFrame, asset_type: str
) -> None:
    """Spatial join: log current asset count per ward."""
    try:
        joined = gpd.sjoin(gdf, wards, how="left", predicate="intersects")
        ward_col = next(
            (c for c in ("WARD", "WARD_NAME", "ward", "ward_name", "name") if c in joined.columns),
            None,
        )
        if ward_col is None:
            logger.info("[%s] Ward column not found; skipping per-ward breakdown.", asset_type)
            return

        counts = joined.groupby(ward_col).size()
        logger.info("[%s] Per-ward counts:\n%s", asset_type, counts.to_string())
    except Exception as exc:
        logger.warning("[%s] Ward join failed: %s", asset_type, exc)


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────


def run(
    asset_types: Optional[List[str]] = None,
    force: bool = False,
    local_paths: Optional[Dict[str, Path]] = None,
    upsert: bool = True,
) -> Dict[str, int]:
    """Main entry point — idempotent ingestion pipeline.

    Returns
    -------
        dict  asset_type → row count (0 if skipped or no source).
    """
    if asset_types is None:
        asset_types = ["water", "power", "roads"]

    logger.info("=== Sindio Geospatial Ingestion ===")
    logger.info("Target CRS: %s  |  Force: %s  |  Upsert: %s", TARGET_CRS, force, upsert)
    logger.info("Assets: %s", asset_types)

    local_paths = local_paths or {}
    wards = _load_wards()
    counts: Dict[str, int] = {}

    for at in asset_types:
        path = _resolve_source(at, local_paths.get(at))
        if path is None:
            logger.warning("[%s] No source available.", at)
            counts[at] = 0
            continue

        gdf = load_gdf(at, path, force=force)
        if gdf is None:
            counts[at] = 0
            continue

        if wards is not None:
            _count_per_ward(gdf, wards, at)

        if upsert:
            n = _upsert_gdf(gdf, at)
            counts[at] = n
        else:
            counts[at] = len(gdf)

    logger.info("=== Ingestion complete ===")
    return counts


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sindio Geospatial Ingestion")
    parser.add_argument(
        "--assets",
        nargs="+",
        choices=["water", "power", "roads"],
        default=["water", "power", "roads"],
        help="Which asset types to ingest.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ingest even if source hash is unchanged.",
    )
    parser.add_argument(
        "--no-upsert",
        dest="upsert",
        action="store_false",
        help="Validate and log only — do not write to DB.",
    )
    args = parser.parse_args()

    logger.addHandler(console_handler)
    run(asset_types=args.assets, force=args.force, upsert=args.upsert)
