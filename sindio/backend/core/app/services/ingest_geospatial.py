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
LOG_DIR = Path("./logs")
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
DB_URL = os.getenv("DATABASE_URL")

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

    # Safely handle capacity columns that may be missing
    cap_series = gdf.get("capacity_value") if "capacity_value" in gdf else gdf.get("capacity") if "capacity" in gdf else gdf.get("CAPACITY")
    if cap_series is not None:
        gdf["capacity_value"] = (
            pd.to_numeric(cap_series, errors="coerce").fillna(default_value)
        )
    else:
        gdf["capacity_value"] = default_value

    # Capacity unit – fallback to default if column missing
    unit_series = gdf.get("capacity_unit") if "capacity_unit" in gdf else gdf.get("UNIT")
    if unit_series is not None:
        gdf["capacity_unit"] = unit_series.fillna(default_unit)
    else:
        gdf["capacity_unit"] = default_unit

    gdf["year_constructed"] = (
        pd.to_numeric(
            gdf["year_constructed"] if "year_constructed" in gdf.columns else (
                gdf["YR_BLT"] if "YR_BLT" in gdf.columns else (
                    gdf["YEAR_CONST"] if "YEAR_CONST" in gdf.columns else pd.Series([2005]*len(gdf))
                )
            ),
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
    # Source name – fallback to asset_type if no column present
    source_series = (
        gdf.get("source_name")
        or gdf.get("SOURCE")
        or gdf.get("FULL_NAME")
        or gdf.get("NAME")
    )
    if source_series is not None:
        gdf["source_name"] = source_series.fillna(f"{asset_type}_segment")
    else:
        gdf["source_name"] = f"{asset_type}_segment"


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

    # Convert geometries to WKT in a vectorized manner
    gdf["geometry_wkt"] = gdf.geometry.to_wkt()

    # Find rows where WKT string is too long (> 4096 characters)
    long_mask = gdf["geometry_wkt"].str.len() > 4096
    if long_mask.any():
        logger.info("[%s] Simplifying %d geometries with WKT length > 4096", asset_type, long_mask.sum())
        gdf.loc[long_mask, "geometry"] = gdf.loc[long_mask, "geometry"].simplify(2.0, preserve_topology=True)
        gdf.loc[long_mask, "geometry_wkt"] = gdf.loc[long_mask, "geometry"].to_wkt()

        # Check again
        still_long_mask = long_mask & (gdf["geometry_wkt"].str.len() > 4096)
        if still_long_mask.any():
            gdf.loc[still_long_mask, "geometry"] = gdf.loc[still_long_mask, "geometry"].simplify(10.0, preserve_topology=True)
            gdf.loc[still_long_mask, "geometry_wkt"] = gdf.loc[still_long_mask, "geometry"].to_wkt()

            # Final check - drop if still too long
            final_long_mask = still_long_mask & (gdf["geometry_wkt"].str.len() > 4096)
            if final_long_mask.any():
                logger.warning("[%s] Skipping %d rows whose geometry WKT is still too long (> 4096 chars)", asset_type, final_long_mask.sum())
                gdf = gdf[~final_long_mask].copy()

    # Vectorized datetime format/defaulting
    gdf["last_maintenance_date"] = pd.to_datetime(gdf["last_maintenance"]).dt.date
    # Fill NAs for capacity and year_constructed
    gdf["capacity_value"] = gdf["capacity_value"].fillna(0.0)
    gdf["capacity_unit"] = gdf["capacity_unit"].fillna("unknown")
    gdf["year_constructed"] = gdf["year_constructed"].fillna(2005).astype(int)

    # Convert to dict records instantaneously
    rows = gdf[[
        "source_name", "geometry_wkt", "capacity_value", "capacity_unit",
        "year_constructed", "last_maintenance_date"
    ]].to_dict("records")

    # Rename last_maintenance_date and add asset_type key
    for r in rows:
        r["asset_type"] = asset_type
        r["last_maintenance"] = r.pop("last_maintenance_date")
        r["source_name"] = str(r["source_name"])

    source_hash = _sha256_of_bytes(
        json.dumps([r["source_name"] for r in rows]).encode()
    )
    params_list = [{**r, "source_hash": source_hash} for r in rows]
    batch_size = 2000
    count = 0

    for idx in range(0, len(params_list), batch_size):
        batch = params_list[idx : idx + batch_size]
        
        # Dynamically build a single parameterized multi-row insert query
        values_clauses = []
        params = {}
        for i, r in enumerate(batch):
            values_clauses.append(f"""
                (:asset_type_{i}, :source_name_{i}, :geometry_wkt_{i},
                 :capacity_value_{i}, :capacity_unit_{i}, :year_constructed_{i},
                 :last_maintenance_{i}, :source_hash_{i})
            """)
            params.update({
                f"asset_type_{i}": r["asset_type"],
                f"source_name_{i}": r["source_name"],
                f"geometry_wkt_{i}": r["geometry_wkt"],
                f"capacity_value_{i}": r["capacity_value"],
                f"capacity_unit_{i}": r["capacity_unit"],
                f"year_constructed_{i}": r["year_constructed"],
                f"last_maintenance_{i}": r["last_maintenance"],
                f"source_hash_{i}": r["source_hash"],
            })
            
        upsert_sql = text(f"""
            INSERT INTO infrastructure_assets
                (asset_type, source_name, geometry_wkt, capacity_value, capacity_unit,
                 year_constructed, last_maintenance, source_hash)
            VALUES {','.join(values_clauses)}
            ON CONFLICT (asset_type, source_name) DO NOTHING
        """)

        with engine.begin() as conn:
            conn.execute(upsert_sql, params)
        count += len(batch)
        if idx % 10000 == 0 or idx == len(params_list) - len(batch):
            logger.info("[%s] Ingested %d / %d rows...", asset_type, count, len(rows))

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
