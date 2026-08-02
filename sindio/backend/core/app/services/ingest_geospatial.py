# -*- coding: utf-8 -*-
"""
Sindio — Geospatial Ingestion Pipeline
=====================================
Downloads / loads Nairobi infrastructure shapefiles (water mains, power lines, road segments),
normalises to EPSG:32737, validates geometries, and upserts into PostGIS `infrastructure_assets`.

Features added:
- Async download via aiohttp with retry/backoff (configurable).
- YAML configuration (`config/ingest.yaml`).
- Structured JSON logging using structlog (logs also to rotating file).
- Optional parallel ingestion of asset types via `--parallel` flag.
- Keeps original JSON hash store for idempotency.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import logging.handlers
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

import httpx
import yaml
import structlog
import pandas as pd
# Import retry decorator for DB operations
from backend.core.app.services.retry_decorator import retry_if_enabled
# Optional third‑party helpers – imported lazily to avoid hard dependency failures
try:
    from tenacity import retry, stop_after_attempt, wait_exponential, RetryError
    # Import Prometheus metrics
    from backend.core.app.services.metrics import INGEST_DURATION, ROWS_PROCESSED, UPSERT_SUCCESS, UPSERT_FAILURE
except ImportError:  # pragma: no cover
    retry = lambda *a, **kw: (lambda f: f)  # no‑op decorator
    stop_after_attempt = lambda n: None
    wait_exponential = lambda multiplier=1, min=0, max=None: None
    RetryError = Exception

try:
    import pandera as pa
    from pandera import DataFrameSchema, Column, Check
except ImportError:  # pragma: no cover
    pa = None

try:
    import ijson
except ImportError:  # pragma: no cover
    ijson = None

# Lazy imports for heavy GIS libraries
def _import_geopandas():
    try:
        import geopandas as gpd
        return gpd
    except Exception as exc:
        logger.warning("geopandas_import_failed", error=str(exc))
        return None

def _import_shapely():
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import linemerge
    from shapely.validation import make_valid
    return LineString, MultiLineString, linemerge, make_valid

# -----------------------------------------------------------------------------
# Configuration loading (YAML)
# -----------------------------------------------------------------------------
CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "ingest.yaml"
if not CONFIG_PATH.exists():
    raise FileNotFoundError(f"Ingestion config not found at {CONFIG_PATH}")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    _cfg = yaml.safe_load(f)

DOWNLOAD_CFG = _cfg.get("download", {})
CAPACITY_MAP_CFG = _cfg.get("capacity_map", {})
DB_CFG = _cfg.get("db", {})
LOGGING_CFG = _cfg.get("logging", {})

# -----------------------------------------------------------------------------
# Logging – structlog + rotating file (retains original behaviour)
# -----------------------------------------------------------------------------
LOG_DIR = Path("./logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "ingestion.log"

from backend.core.app.logging import logger

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
TARGET_CRS = "EPSG:32737"  # UTM zone 37S (Nairobi)
DEFAULT_CACHE_DIR = Path(os.getenv("DATA_RAW_DIR", "data/raw"))
HASH_STORE = DEFAULT_CACHE_DIR / ".ingestion_hashes.json"
OPEN_NAIROBI_BASE = "https://opendata.nairobi.go.ke"
FALLBACK_URLS: Dict[str, List[str]] = {
    "water": [f"{OPEN_NAIROBI_BASE}/datasets/water-mains-network/download/water_mains.geojson"],
    "power": [f"{OPEN_NAIROBI_BASE}/datasets/power-distribution-lines/download/power_lines.geojson"],
    "roads": [f"{OPEN_NAIROBI_BASE}/datasets/road-network/download/road_segments.geojson"],
}
NAIROBI_WARDS_URL = f"{OPEN_NAIROBI_BASE}/datasets/nairobi-wards-boundaries/download/wards.geojson"

# -----------------------------------------------------------------------------
# Helper functions (hash handling)
# -----------------------------------------------------------------------------
def _load_hashes() -> Dict[str, Any]:
    """Load hash metadata (hash string + optional timestamp).
    Stale cache entries older than 30 days are pruned automatically.
    """
    if not HASH_STORE.exists():
        return {}
    try:
        data = json.loads(HASH_STORE.read_text())
    except json.JSONDecodeError:
        return {}
    # Prune entries older than 30 days based on file modification time
    now = datetime.now(timezone.utc)
    prune_keys = []
    for key, val in data.items():
        if isinstance(val, dict) and "timestamp" in val:
            ts = datetime.fromisoformat(val["timestamp"]).replace(tzinfo=timezone.utc)
            if (now - ts).days > 30:
                prune_keys.append(key)
    for k in prune_keys:
        data.pop(k, None)
        # also delete the cached file if present
        cached_path = DEFAULT_CACHE_DIR / f"{k}_network.geojson"
        if cached_path.exists():
            cached_path.unlink(missing_ok=True)
    return data

def _save_hashes(data: Dict[str, Any]) -> None:
    # Store hash together with a timestamp for cache‑expiry logic
    for k, v in data.items():
        if isinstance(v, str):
            data[k] = {"hash": v, "timestamp": datetime.now(timezone.utc).isoformat()}
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

# -----------------------------------------------------------------------------
# Async download with retry/backoff
# -----------------------------------------------------------------------------
@retry(stop=stop_after_attempt(DOWNLOAD_CFG.get("retries", 3)), wait=wait_exponential(multiplier=DOWNLOAD_CFG.get("backoff_factor", 0.5)))
async def _download_file_async(url: str, dest: Path) -> Optional[Path]:
    timeout = DOWNLOAD_CFG.get("timeout", 120)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            logger.info(
                "downloaded",
                url=url,
                dest=str(dest),
                size=len(resp.content),
                attempt=1,
            )
            return dest
    except httpx.ConnectError as exc:
        logger.warning(
            "download_connect_error",
            url=url,
            error=str(exc),
            note="Check network/DNS or provide alternative URL",
        )
        raise
    except Exception as exc:
        logger.warning(
            "download_failed",
            url=url,
            error=str(exc),
        )
        raise
    # The tenacity decorator will retry automatically

# -----------------------------------------------------------------------------
# Geometry repair (lazy import of shapely)
# -----------------------------------------------------------------------------
def _repair_geometry(geom: Any) -> Optional[LineString]:
    if geom is None or getattr(geom, "is_empty", True):
        return None
    LineString, MultiLineString, linemerge, make_valid = _import_shapely()
    validated = make_valid(geom)
    if isinstance(validated, LineString):
        return validated
    if isinstance(validated, MultiLineString):
        merged = linemerge(validated)
        if isinstance(merged, LineString):
            return merged
        if isinstance(merged, MultiLineString):
            return merged.geoms[0]
    return None

# -----------------------------------------------------------------------------
# Resolve source (now async)
# -----------------------------------------------------------------------------
async def _discover_latest_url(asset_type: str) -> Optional[str]:
    ckan_endpoint = _cfg.get("ckan_endpoint")
    if not ckan_endpoint:
        return None
    try:
        resp = httpx.get(ckan_endpoint, params={"id": asset_type}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # Expect CKAN package dict with resources list – pick first downloadable URL
        resources = data.get("result", {}).get("resources", [])
        for res in resources:
            url = res.get("url")
            if url:
                return url
    except Exception as exc:
        logger.warning("ckan_discovery_failed", asset_type=asset_type, error=str(exc))
    return None

async def _resolve_source(asset_type: str, local_cache: Optional[Path] = None) -> Optional[Path]:
    if local_cache and local_cache.exists():
        return local_cache
    cached = DEFAULT_CACHE_DIR / f"{asset_type}_network.geojson"
    if cached.exists():
        return cached
    # Try dynamic discovery via CKAN if configured
    dynamic_url = await _discover_latest_url(asset_type)
    if dynamic_url:
        try:
            result = await _download_file_async(dynamic_url, cached)
            if result:
                return result
        except RetryError:
            return None
    # Fallback to static URLs list
    for url in FALLBACK_URLS.get(asset_type, []):
        try:
            result = await _download_file_async(url, cached)
            if result:
                return result
        except RetryError:
            continue
    logger.error("no_source", asset_type=asset_type)
    return None

# -----------------------------------------------------------------------------
# Load GeoDataFrame (lazy import of geopandas)
# -----------------------------------------------------------------------------
def load_gdf(asset_type: str, path: Path, force: bool = False):
    gpd = _import_geopandas()
    if gpd is None:
        logger.warning("geopandas_unavailable", asset_type=asset_type)
        return None
    stored_hashes = _load_hashes()
    file_hash = _sha256_of_file(path)
    if not force and stored_hashes.get(asset_type) == file_hash:
        logger.info("skip_source", asset_type=asset_type, hash=file_hash[:12])
        return None
    stored_hashes[asset_type] = file_hash
    _save_hashes(stored_hashes)
    logger.info("load_gdf", asset_type=asset_type, path=str(path))
    try:
        gdf = gpd.read_file(path)
    except Exception as exc:
        logger.warning("gdf_read_failed", asset_type=asset_type, error=str(exc))
        # Fallback: attempt to load GeoJSON manually using json and shapely
        try:
            import json
            from shapely.geometry import shape
            import pandas as pd
            import yaml

# Feature toggles – loaded from config/features.yaml (if present)
def _load_feature_flags() -> dict:
    """Load optional feature flags.
    Returns a dict with defaults if the file does not exist.
    """
    default = {
        "parallel": False,
        "max_workers": 4,
        "enable_metrics": True,
        "enable_retry": True,
    }
    cfg_path = Path(__file__).resolve().parents[4] / "config" / "features.yaml"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            default.update(data)
        except Exception as exc:
            logger.warning("feature_flags_load_failed", error=str(exc))
    return default
            with open(path, "r", encoding="utf-8") as f:
                geojson = json.load(f)
            features = geojson.get("features", [])
            if not features:
                logger.warning("empty_geojson", asset_type=asset_type)
                return None
            # Extract properties and geometry
            records = []
            for feat in features:
                props = feat.get("properties", {})
                geom = shape(feat.get("geometry", {}))
                props["geometry"] = geom
                records.append(props)
            gdf = pd.GeoDataFrame(records, geometry="geometry")
        except Exception as fallback_exc:
            logger.error("fallback_geojson_load_failed", asset_type=asset_type, error=str(fallback_exc))
            return None
    if gdf.crs is None:
        logger.warning("missing_crs", asset_type=asset_type)
        gdf.set_crs("EPSG:4326", inplace=True)
    if gdf.crs != TARGET_CRS:
        gdf = gdf.to_crs(TARGET_CRS)
    gdf["geometry"] = gdf["geometry"].apply(_repair_geometry)
    gdf = gdf[gdf["geometry"].notna()].copy()
    if gdf.empty:
        logger.warning("no_valid_geometries", asset_type=asset_type)
        return None
    # Load validation config (defaults to original strict behavior)
    VALIDATION_CFG = _cfg.get("validation", {})
    ENFORCE_LENGTH = VALIDATION_CFG.get("enforce_length", True)
    EXCLUDE_RINGS = VALIDATION_CFG.get("exclude_ring_geometries", True)

    @app.get("/metrics")
    async def metrics(request: Request):
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    def _geom_is_valid(g):
        if g is None:
            return False
        if not g.is_valid:
            return False
        if ENFORCE_LENGTH and g.length <= 0:
            return False
        if EXCLUDE_RINGS and getattr(g, "is_ring", False):
            return False
        return True

    gdf["is_valid"] = gdf.geometry.apply(_geom_is_valid)
    invalid = (~gdf["is_valid"]).sum()
    if invalid:
        logger.warning("drop_invalid", asset_type=asset_type, count=invalid)
    gdf = gdf[gdf["is_valid"]].drop(columns=["is_valid"])

    # Capacity handling from YAML config
    cap_cfg = CAPACITY_MAP_CFG.get(asset_type, {"unit": "unknown", "default": 0.0})
    default_unit = cap_cfg.get("unit", "unknown")
    default_value = cap_cfg.get("default", 0.0)
    cap_series = (
        gdf.get("capacity_value")
        or gdf.get("capacity")
        or gdf.get("CAPACITY")
    )
    if cap_series is not None:
        gdf["capacity_value"] = (
            pd.to_numeric(cap_series, errors="coerce").fillna(default_value)
        )
    else:
        gdf["capacity_value"] = default_value
    unit_series = gdf.get("capacity_unit") or gdf.get("UNIT")
    if unit_series is not None:
        gdf["capacity_unit"] = unit_series.fillna(default_unit)
    else:
        gdf["capacity_unit"] = default_unit

    # Year constructed handling (same as original)
    gdf["year_constructed"] = (
        pd.to_numeric(
            gdf["year_constructed"]
            if "year_constructed" in gdf.columns
            else (
                gdf["YR_BLT"]
                if "YR_BLT" in gdf.columns
                else (
                    gdf["YEAR_CONST"]
                    if "YEAR_CONST" in gdf.columns
                    else pd.Series([2005] * len(gdf))
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
    logger.info("gdf_ready", asset_type=asset_type, rows=len(gdf))
    return gdf

# -----------------------------------------------------------------------------
# Database engine (lazy import sqlalchemy)
# -----------------------------------------------------------------------------
def _get_db_engine():
    from sqlalchemy import create_engine
    from backend.core.app.config import config
    return create_engine(config.database_url)

# -----------------------------------------------------------------------------
# Upsert – retains original INSERT method (COPY could be added later)
# -----------------------------------------------------------------------------
@retry_if_enabled
def _upsert_gdf(gdf, asset_type: str, enable_validation: bool = True) -> int:
    from sqlalchemy import text
    import pandas as pd
    from pandera import DataFrameSchema, Column, Check
    import pandera as pa
    import json
    
    engine = _get_db_engine()
    # Prepare geometry WKT and optional simplification for overly long strings
    gdf["geometry_wkt"] = gdf.geometry.to_wkt()
    long_mask = gdf["geometry_wkt"].str.len() > 4096
    if long_mask.any():
        logger.info(
            "simplify_long_wkt",
            asset_type=asset_type,
            count=long_mask.sum(),
        )
        gdf.loc[long_mask, "geometry"] = gdf.loc[long_mask, "geometry"].simplify(
            2.0, preserve_topology=True
        )
        gdf.loc[long_mask, "geometry_wkt"] = gdf.loc[long_mask, "geometry"].to_wkt()
        # Second pass for very long geometries
        still_long = long_mask & (gdf["geometry_wkt"].str.len() > 4096)
        if still_long.any():
            gdf.loc[still_long, "geometry"] = gdf.loc[still_long, "geometry"].simplify(
                10.0, preserve_topology=True
            )
            gdf.loc[still_long, "geometry_wkt"] = gdf.loc[still_long, "geometry"].to_wkt()
            final_long = still_long & (gdf["geometry_wkt"].str.len() > 4096)
            if final_long.any():
                logger.warning(
                    "skip_too_long",
                    asset_type=asset_type,
                    count=final_long.sum(),
                )
                gdf = gdf[~final_long].copy()
    # Normalise auxiliary columns
    gdf["last_maintenance_date"] = pd.to_datetime(gdf["last_maintenance"]).dt.date
    gdf["capacity_value"] = gdf["capacity_value"].fillna(0.0)
    gdf["capacity_unit"] = gdf["capacity_unit"].fillna("unknown")
    gdf["year_constructed"] = gdf["year_constructed"].fillna(2005).astype(int)

    # OPTIONAL: schema validation via pandera (if available)
    if enable_validation and pa is not None:
        try:
            schema = DataFrameSchema({
                "source_name": Column(pa.String, nullable=False),
                "geometry_wkt": Column(pa.String, nullable=False),
                "capacity_value": Column(pa.Float, nullable=False),
                "capacity_unit": Column(pa.String, nullable=False),
                "year_constructed": Column(pa.Int, Check.ge(1900), Check.le(2100)),
                "last_maintenance_date": Column(pa.Date, nullable=False),
            })
            schema.validate(gdf, lazy=True)
        except Exception as exc:
            logger.warning("schema_validation_failed", asset_type=asset_type, error=str(exc))

    rows = gdf[[
        "source_name",
        "geometry_wkt",
        "capacity_value",
        "capacity_unit",
        "year_constructed",
        "last_maintenance_date",
    ]].to_dict("records")
    for r in rows:
        r["asset_type"] = asset_type
        r["last_maintenance"] = r.pop("last_maintenance_date")
        r["source_name"] = str(r["source_name"])
    source_hash = _sha256_of_bytes(json.dumps([r["source_name"] for r in rows]).encode())
    params_list = [{**r, "source_hash": source_hash} for r in rows]
    batch_size = DB_CFG.get("batch_size", 2000)
    count = 0
    use_copy = DB_CFG.get("use_copy", False)
    for idx in range(0, len(params_list), batch_size):
        batch = params_list[idx : idx + batch_size]
        if use_copy:
            # Build a CSV‑like string for COPY
            csv_rows = []
            for r in batch:
                csv_rows.append(
                    f"{r['asset_type']}\t{r['source_name']}\t{r['geometry_wkt']}\t{r['capacity_value']}\t{r['capacity_unit']}\t{r['year_constructed']}\t{r['last_maintenance']}\t{r['source_hash']}"
                )
            copy_data = "\n".join(csv_rows) + "\n"
            copy_sql = text(
                "COPY infrastructure_assets (asset_type, source_name, geometry_wkt, capacity_value, capacity_unit, year_constructed, last_maintenance, source_hash) FROM STDIN WITH (FORMAT csv, DELIMITER '\t', NULL '')"
            )
            with engine.begin() as conn:
                conn.connection.cursor().copy_expert(copy_sql.text, copy_data)
        else:
            # Fallback to INSERT … ON CONFLICT
            values_clauses = []
            params = {}
            for i, r in enumerate(batch):
                values_clauses.append(
                    f"""
                    (:asset_type_{i}, :source_name_{i}, :geometry_wkt_{i},
                     :capacity_value_{i}, :capacity_unit_{i}, :year_constructed_{i},
                     :last_maintenance_{i}, :source_hash_{i})
                    """
                )
                params.update(
                    {
                        f"asset_type_{i}": r["asset_type"],
                        f"source_name_{i}": r["source_name"],
                        f"geometry_wkt_{i}": r["geometry_wkt"],
                        f"capacity_value_{i}": r["capacity_value"],
                        f"capacity_unit_{i}": r["capacity_unit"],
                        f"year_constructed_{i}": r["year_constructed"],
                        f"last_maintenance_{i}": r["last_maintenance"],
                        f"source_hash_{i}": r["source_hash"],
                    }
                )
            upsert_sql = text(
                f"""
                INSERT INTO infrastructure_assets
                    (asset_type, source_name, geometry_wkt, capacity_value, capacity_unit,
                     year_constructed, last_maintenance, source_hash)
                VALUES {', '.join(values_clauses)}
                ON CONFLICT (asset_type, source_name) DO NOTHING
                """
            )
            with engine.begin() as conn:
                conn.execute(upsert_sql, params)
        count += len(batch)
        logger.info("batch_upsert", asset_type=asset_type, inserted=count)
    logger.info("upsert_complete", asset_type=asset_type, total=count)
    return count

# -----------------------------------------------------------------------------
# Ward loading and per‑ward counting (unchanged logic)
# -----------------------------------------------------------------------------
def _download_file_sync(url: str, dest: Path) -> Optional[Path]:
    """Synchronous download used for small auxiliary files (e.g., ward boundaries)."""
    timeout = DOWNLOAD_CFG.get("timeout", 120)
    retries = DOWNLOAD_CFG.get("retries", 3)
    backoff = DOWNLOAD_CFG.get("backoff_factor", 0.5)
    for attempt in range(1, retries + 1):
        try:
            resp = httpx.get(url, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            logger.info(
                "downloaded_sync",
                url=url,
                dest=str(dest),
                size=len(resp.content),
                attempt=attempt,
            )
            return dest
        except Exception as exc:
            logger.warning(
                "download_sync_failed",
                url=url,
                attempt=attempt,
                error=str(exc),
            )
            if attempt < retries:
                import time
                time.sleep(backoff * attempt)
    return None

def _load_wards() -> Optional["gpd.GeoDataFrame"]:
    gpd = _import_geopandas()
    cached = DEFAULT_CACHE_DIR / "nairobi_wards.geojson"
    if not cached.exists():
        _download_file_sync(NAIROBI_WARDS_URL, cached)
    if not cached.exists():
        logger.warning("wards_missing")
        return None
    wards = gpd.read_file(cached)
    if wards.crs != TARGET_CRS:
        wards = wards.to_crs(TARGET_CRS)
    return wards

def _count_per_ward(gdf, wards, asset_type: str) -> None:
    try:
        joined = gpd.sjoin(gdf, wards, how="left", predicate="intersects")
        ward_col = next(
            (c for c in ("WARD", "WARD_NAME", "ward", "ward_name", "name") if c in joined.columns),
            None,
        )
        if not ward_col:
            logger.info("no_ward_column", asset_type=asset_type)
            return
        counts = joined.groupby(ward_col).size()
        logger.info("per_ward_counts", asset_type=asset_type, counts=counts.to_dict())
    except Exception as exc:
        logger.warning("ward_join_failed", asset_type=asset_type, error=str(exc))

# -----------------------------------------------------------------------------
# Main processing for a single asset
# -----------------------------------------------------------------------------
async def _process_asset(asset_type: str, local_path: Optional[Path], force: bool, upsert: bool, wards) -> int:
    path = await _resolve_source(asset_type, local_path)
    if not path:
        logger.warning("no_source_available", asset_type=asset_type)
        return 0
    gdf = load_gdf(asset_type, path, force=force)
    if gdf is None:
        return 0
    if wards is not None:
        _count_per_ward(gdf, wards, asset_type)
    if upsert:
        return _upsert_gdf(gdf, asset_type, enable_validation=enable_validation)
    return len(gdf)

# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def run(
    asset_types: Optional[List[str]] = None,
    force: bool = False,
    local_paths: Optional[Dict[str, Path]] = None,
    upsert: bool = True,
    parallel: bool = False,
    feature_flags: Optional[dict] = None,
) -> Dict[str, int]:
    """Main entry point — idempotent ingestion pipeline.

    Parameters
    ----------
    asset_types: list of asset types to ingest.
    force: ingest even if source hash unchanged.
    local_paths: optional mapping of asset_type → Path for local cache.
    upsert: write to DB when True.
    parallel: request parallel processing (overridden by feature flag).
    feature_flags: runtime toggles loaded from ``features.yaml``; can override ``parallel`` and ``validation``.
    """
    if asset_types is None:
        asset_types = ["water", "power", "roads"]
    # Load feature flags (may override CLI parallel flag)
    flags = feature_flags or _load_feature_flags()
    effective_parallel = parallel or flags.get("parallel", False)
    max_workers = flags.get("max_workers", 4)
    enable_validation = flags.get("validation", True)
    run_id = str(uuid.uuid4())
    logger.info(
        "pipeline_start",
        run_id=run_id,
        asset_types=asset_types,
        force=force,
        parallel=effective_parallel,
    )
    wards = _load_wards()
    counts: Dict[str, int] = {}
    local_paths = local_paths or {}

    if not effective_parallel:
        # Sequential processing
        for at in asset_types:
            with INGEST_DURATION.labels(asset_type=at).time():
                try:
                    cnt = asyncio.run(_process_asset(at, local_paths.get(at), force, upsert, wards, enable_validation))
                    counts[at] = cnt
                    ROWS_PROCESSED.labels(asset_type=at).inc(cnt)
                    if upsert:
                        if cnt > 0:
                            UPSERT_SUCCESS.labels(asset_type=at).inc(cnt)
                        else:
                            UPSERT_FAILURE.labels(asset_type=at).inc(1)
                except Exception as exc:
                    logger.error("ingest_asset_error", asset_type=at, error=str(exc))
                    UPSERT_FAILURE.labels(asset_type=at).inc(1)
                    counts[at] = 0
    else:
        # Parallel processing using asyncio.gather (respecting max_workers via semaphore)
        logger.info("parallel_ingest_start", asset_types=asset_types, max_workers=max_workers)
        semaphore = asyncio.Semaphore(max_workers)

        async def _bounded_process(at: str):
            async with semaphore:
                # Increment gauge for this asset type
                from backend.core.app.services.metrics import PARALLEL_WORKERS_ACTIVE
                PARALLEL_WORKERS_ACTIVE.labels(asset_type=at).inc()
                try:
                    return await _process_asset(at, local_paths.get(at), force, upsert, wards, enable_validation)
                finally:
                    # Decrement gauge after processing
                    PARALLEL_WORKERS_ACTIVE.labels(asset_type=at).dec()

        async def _run_parallel():
            tasks = [_bounded_process(at) for at in asset_types]
            return await asyncio.gather(*tasks, return_exceptions=True)

        results = asyncio.run(_run_parallel())
        for at, result in zip(asset_types, results):
            if isinstance(result, Exception):
                logger.error("parallel_ingest_error", asset_type=at, error=str(result))
                UPSERT_FAILURE.labels(asset_type=at).inc(1)
                counts[at] = 0
            else:
                counts[at] = result
                ROWS_PROCESSED.labels(asset_type=at).inc(result)
                if upsert:
                    if result > 0:
                        UPSERT_SUCCESS.labels(asset_type=at).inc(result)
                    else:
                        UPSERT_FAILURE.labels(asset_type=at).inc(1)
        logger.info("parallel_ingest_complete", asset_types=asset_types, results=counts)
    logger.info("pipeline_complete", run_id=run_id, counts=counts)
    return counts

# -----------------------------------------------------------------------------
# CLI entry point (preserves original interface, adds --parallel)
# -----------------------------------------------------------------------------
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
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Ingest asset types in parallel (async).",
    )
    args = parser.parse_args()
    logger.info("cli_start", args=args)
    run(
        asset_types=args.assets,
        force=args.force,
        upsert=args.upsert,
        parallel=args.parallel,
    )
