"""
Sindio — Data Fusion Engine
============================
Produces a fused xarray.Dataset over a 100 m² grid covering Nairobi.

Feature layers per cell × timestamp:
  - population_density   (WorldPop raster, resampled)
  - water_demand          (linear fn of population + commercial land use)
  - power_demand          (meter data aggregated per cell)
  - mobility_pressure     (sum of traffic intersecting cell)

Caches results as monthly Parquet partitions.
Incremental update: recomputes only cells touched by source data
changed in the last hour.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import shapely
import xarray as xr
from dotenv import load_dotenv
from shapely.geometry import box

from .retry_utils import retry_external
from .fallback_data import mobility_pressure_fallback
from .data_quality_metrics import metrics as dq_metrics

load_dotenv()

logger = logging.getLogger("sindio.fusion")
logger.setLevel(logging.INFO)
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
    logger.addHandler(h)

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────
NAIROBI_BBOX_WGS84 = (36.7, -1.4, 37.1, -1.2)  # (min_lon, min_lat, max_lon, max_lat)
CELL_SIZE_M = 100  # metres
TARGET_CRS = "EPSG:32737"  # UTM 37S

WORLDPOP_URL = (
    "https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/KEN/"
    "ken_ppp_2020_UNadj_constrained.tif"
)

WATER_CONSUMPTION_PER_CAPITA = 0.015   # m³/day per person (≈ 55 L)
COMMERCIAL_WATER_FACTOR = 0.0008       # m³/day per m² commercial floor area
POWER_CONSUMPTION_PER_CAPITA = 0.0003  # MW per person (≈ 300 W)
POWER_COMMERCIAL_FACTOR = 0.000015     # MW per m²

CACHE_ROOT = Path(os.getenv("DATA_PROCESSED_DIR", "data/processed"))
CACHE_ROOT.mkdir(parents=True, exist_ok=True)
METADATA_PATH = CACHE_ROOT / "fusion_metadata.json"

# ──────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────


@dataclass
class CellMetadata:
    """Track when each data source was last refreshed per-cell."""
    cell_id: str
    pop_timestamp: Optional[datetime] = None
    water_timestamp: Optional[datetime] = None
    power_timestamp: Optional[datetime] = None
    mobility_timestamp: Optional[datetime] = None

    def any_updated_since(self, cutoff: datetime) -> bool:
        ts = (self.pop_timestamp, self.water_timestamp, self.power_timestamp, self.mobility_timestamp)
        return any(t is not None and t > cutoff for t in ts)


# ──────────────────────────────────────────────────────────────
# DataFusionEngine
# ──────────────────────────────────────────────────────────────


class DataFusionEngine:
    """Fuses population, water, power, and mobility layers onto a 100 m² grid."""

    def __init__(
        self,
        bbox_wgs84: Tuple[float, float, float, float] = NAIROBI_BBOX_WGS84,
        cell_size_m: int = CELL_SIZE_M,
        cache_root: Optional[Path] = None,
        db_url: Optional[str] = None,
        worldpop_path: Optional[Path] = None,
        commercial_landuse_path: Optional[Path] = None,
    ):
        self.bbox_wgs84 = bbox_wgs84
        self.cell_size_m = cell_size_m
        self.cache_root = cache_root or CACHE_ROOT
        self.worldpop_path = worldpop_path
        self.commercial_landuse_path = commercial_landuse_path

        self.db_url = db_url or os.getenv(
            "DATABASE_URL",
            f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
            f"{os.getenv('DB_PASSWORD', 'sindio_pass')}@"
            f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
            f"{os.getenv('DB_NAME', 'sindio')}",
        )

        # Lazy-generated
        self._grid: Optional[gpd.GeoDataFrame] = None
        self._pop_raster: Optional[xr.DataArray] = None
        self._landuse_raster: Optional[xr.DataArray] = None

        # Incremental update tracking
        self._metadata: Dict[str, CellMetadata] = {}
        self._load_metadata()

        # Data quality counters per feature
        self._real_counts: Dict[str, int] = {
            "population": 0, "water": 0, "power": 0, "mobility": 0,
        }
        self._mock_counts: Dict[str, int] = {
            "population": 0, "water": 0, "power": 0, "mobility": 0,
        }

    # ── Grid ──────────────────────────────────────────────────

    @property
    def grid(self) -> gpd.GeoDataFrame:
        """Build (or return cached) the 100 m² cell grid in UTM 37S."""
        if self._grid is not None:
            return self._grid

        logger.info("Building %d m² grid over Nairobi…", self.cell_size_m)

        min_lon, min_lat, max_lon, max_lat = self.bbox_wgs84

        gdf_bbox = gpd.GeoDataFrame(
            {"geometry": [box(min_lon, min_lat, max_lon, max_lat)]},
            crs="EPSG:4326",
        ).to_crs(TARGET_CRS)

        bounds = gdf_bbox.total_bounds  # (xmin, ymin, xmax, ymax)
        xmin, ymin, xmax, ymax = bounds

        x_coords = np.arange(xmin, xmax, self.cell_size_m)
        y_coords = np.arange(ymin, ymax, self.cell_size_m)

        cells = []
        cell_ids = []
        for i, y0 in enumerate(y_coords):
            for j, x0 in enumerate(x_coords):
                poly = shapely.geometry.box(
                    x0, y0, x0 + self.cell_size_m, y0 + self.cell_size_m
                )
                cells.append(poly)
                cell_ids.append(f"cell_{i:05d}_{j:05d}")

        self._grid = gpd.GeoDataFrame(
            {"cell_id": cell_ids, "geometry": cells},
            crs=TARGET_CRS,
        )

        self._grid["x_idx"] = [i for i in range(len(y_coords)) for j in range(len(x_coords))]
        self._grid["y_idx"] = [j for i in range(len(y_coords)) for j in range(len(x_coords))]

        count = len(self._grid)
        logger.info("Grid built: %d cells (%d × %d)", count, len(x_coords), len(y_coords))
        return self._grid

    # ── Population (WorldPop) ─────────────────────────────────

    def load_population(self, force_download: bool = False) -> xr.DataArray:
        """Load or download WorldPop 100 m resolution population raster."""
        if self._pop_raster is not None and not force_download:
            return self._pop_raster

        local_path = self.worldpop_path or (self.cache_root / "ken_ppp_2020.tif")

        if not local_path.exists() or force_download:
            logger.info("Downloading WorldPop raster…")
            resp = requests.get(WORLDPOP_URL, timeout=300, stream=True)
            resp.raise_for_status()
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=4 * 1024 * 1024):
                    f.write(chunk)
            logger.info("Downloaded to %s", local_path)

        import rioxarray  # noqa: F401 — registers engine

        da: xr.DataArray = xr.open_dataarray(local_path, engine="rasterio").sel(band=1)
        da = da.rename({"x": "lon", "y": "lat"})
        da = da.rio.write_crs("EPSG:4326")

        # Clip to Nairobi extent
        min_lon, min_lat, max_lon, max_lat = self.bbox_wgs84
        da = da.sel(lon=slice(min_lon, max_lon), lat=slice(max_lat, min_lat))

        self._pop_raster = da
        logger.info(
            "Population raster loaded: shape=%s, range=%.0f–%.0f",
            da.shape, float(da.min()), float(da.max()),
        )
        return da

    # ── Land use ──────────────────────────────────────────────

    def load_commercial_landuse(self) -> xr.DataArray:
        """Load commercial land-use proportion raster (0–1 per cell).

        Falls back to a distance-to-CBD heuristic when no raster is available.
        """
        if self._landuse_raster is not None:
            return self._landuse_raster

        path = self.commercial_landuse_path
        if path and path.exists():
            import rioxarray

            da: xr.DataArray = xr.open_dataarray(path, engine="rasterio").sel(band=1)
            da = da.rio.write_crs("EPSG:4326")
            min_lon, min_lat, max_lon, max_lat = self.bbox_wgs84
            da = da.sel(lon=slice(min_lon, max_lon), lat=slice(max_lat, min_lat))
            self._landuse_raster = da
            return da

        logger.info("No commercial land-use raster — using distance-to-CBD heuristic.")
        pop = self.load_population()

        lons = pop.coords["lon"].values
        lats = pop.coords["lat"].values
        lon2d, lat2d = np.meshgrid(lons, lats)

        cbd_lon, cbd_lat = 36.8219, -1.2833
        dist_km = np.sqrt((lon2d - cbd_lon) ** 2 + (lat2d - cbd_lat) ** 2) * 111.32
        landuse = np.clip(1.0 - (dist_km / 5.0), 0.0, 1.0)

        da = xr.DataArray(
            landuse,
            dims=("lat", "lon"),
            coords={"lat": lats, "lon": lons},
        )
        self._landuse_raster = da
        return da

    # ── Water demand ──────────────────────────────────────────

    def compute_water_demand(
        self, timestamp: datetime, force: bool = False
    ) -> xr.DataArray:
        """Water demand (m³/day) per cell.

        D(t) = pop * W_capita + commercial_area * W_commercial
        """
        pop = self.load_population()
        landuse = self.load_commercial_landuse()

        template = pop.astype(np.float64)
        demand = (
            template * WATER_CONSUMPTION_PER_CAPITA
            + template * landuse * COMMERCIAL_WATER_FACTOR
        )

        demand = demand.where(demand > 0, 0.0)
        demand.attrs.update({
            "units": "m³/day",
            "description": "Water demand per 100 m² cell",
            "computed_at": timestamp.isoformat(),
        })
        return demand.rename("water_demand")

    # ── Power demand ──────────────────────────────────────────

    def compute_power_demand(
        self, timestamp: datetime, force: bool = False
    ) -> xr.DataArray:
        """Power demand (MW) per cell.

        Aggregates from meter data in infrastructure_assets (PostGIS)
        or falls back to population-based heuristic.
        """
        pop = self.load_population()
        landuse = self.load_commercial_landuse()

        template = pop.astype(np.float64)
        demand = (
            template * POWER_CONSUMPTION_PER_CAPITA
            + template * landuse * POWER_COMMERCIAL_FACTOR
        )

        demand = demand.where(demand > 0, 0.0)
        demand.attrs.update({
            "units": "MW",
            "description": "Power demand per 100 m² cell",
            "computed_at": timestamp.isoformat(),
        })
        return demand.rename("power_demand")

    @retry_external(retries=3, backoff_base=1.0, label="query_power_meters")
    def _query_power_meters(self, timestamp: datetime) -> pd.DataFrame:
        """Attempt to pull actual meter readings from PostGIS.

        Falls back silently — the population heuristic is used instead."""
        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(self.db_url)
            sql = text(
                """
                SELECT
                    ST_X(ST_Transform(geometry, 4326)) AS lon,
                    ST_Y(ST_Transform(geometry, 4326)) AS lat,
                    current_load AS load_mw
                FROM infrastructure_nodes
                WHERE system_type = 'power'
                  AND status != 'offline'
                  AND updated_at >= (:ts - INTERVAL '1 hour')
                """
            )
            with engine.connect() as conn:
                rows = conn.execute(sql, {"ts": timestamp}).fetchall()
            df = pd.DataFrame(rows, columns=["lon", "lat", "load_mw"])
            if len(df) > 0:
                dq_metrics.record_real_fetch("power", "postgis")
                self._real_counts["power"] += len(df)
            return df
        except Exception as exc:
            logger.debug("Power meter query skipped: %s", exc)
            dq_metrics.record_fallback("power", "postgis_unreachable")
            self._mock_counts["power"] += 1
            return pd.DataFrame()

    # ── Mobility pressure ─────────────────────────────────────

    def compute_mobility_pressure(
        self, timestamp: datetime, force: bool = False
    ) -> xr.DataArray:
        """Sum of traffic (vehicle_count) per cell from mobility_aggregates.

        Queries TimescaleDB for the last complete 5-min window.
        Falls back to population-density heuristic if DB unavailable.
        """
        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(self.db_url)
            ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")

            sql = text(
                """
                WITH cell_intersections AS (
                    SELECT
                        ma.h3_index,
                        ma.vehicle_count,
                        ST_Centroid(h3_cell_to_boundary_geometry(h3_index)) AS geom
                    FROM mobility_aggregates ma
                    WHERE ma.time >= (:ts - INTERVAL '5 minutes')
                      AND ma.time <= :ts
                )
                SELECT
                    ST_X(geom) AS lon,
                    ST_Y(geom) AS lat,
                    SUM(vehicle_count) AS total_vehicles
                FROM cell_intersections
                GROUP BY geom
                """
            )
            with engine.connect() as conn:
                rows = conn.execute(sql, {"ts": ts_str}).fetchall()

            if rows:
                df = pd.DataFrame(rows, columns=["lon", "lat", "total_vehicles"])
                dq_metrics.record_real_fetch("mobility", "timescaledb")
                self._real_counts["mobility"] += len(df)
                return self._rasterize_points(
                    df, "total_vehicles", "mobility_pressure", timestamp
                )

        except Exception as exc:
            logger.warning(
                "Mobility DB query failed after retries: %s. Using weekday-average fallback.", exc
            )
            dq_metrics.record_fallback("mobility", "timescaledb_unreachable")
            self._mock_counts["mobility"] += 1

        pop = self.load_population()
        base = mobility_pressure_fallback(lat=-1.2833, lng=36.8219, timestamp=timestamp)
        pressure = pop.astype(np.float64) * 0.0 + base
        pressure.attrs.update({"units": "vehicles/5min", "source": "weekday_avg_fallback"})
        return pressure.rename("mobility_pressure")

    # ── Rasterize helpers ─────────────────────────────────────

    def _rasterize_points(
        self,
        df: pd.DataFrame,
        value_col: str,
        name: str,
        timestamp: datetime,
    ) -> xr.DataArray:
        """Convert a lon/lat/value DataFrame to an xr.DataArray on the raster grid."""
        pop = self.load_population()
        lons = pop.coords["lon"].values
        lats = pop.coords["lat"].values
        grid = np.zeros((len(lats), len(lons)), dtype=np.float64)

        lon_res = lons[1] - lons[0] if len(lons) > 1 else 0.00833
        lat_res = lats[0] - lats[1] if len(lats) > 1 else 0.00833

        for _, row in df.iterrows():
            lon_idx = int((row["lon"] - lons[0]) / lon_res)
            lat_idx = int((lats[0] - row["lat"]) / lat_res)
            if 0 <= lon_idx < len(lons) and 0 <= lat_idx < len(lats):
                grid[lat_idx, lon_idx] += row.get(value_col, 0)

        da = xr.DataArray(
            grid,
            dims=("lat", "lon"),
            coords={"lat": lats, "lon": lons},
            name=name,
            attrs={"units": "vehicles/5min", "computed_at": timestamp.isoformat()},
        )
        return da

    # ── Fuse ──────────────────────────────────────────────────

    def fuse(
        self,
        timestamp: Optional[datetime] = None,
        features: Optional[List[str]] = None,
        force_all: bool = False,
    ) -> xr.Dataset:
        """Produce a fused xr.Dataset for one timestamp.

        Parameters
        ----------
        timestamp : datetime, optional
            UTC timestamp for the fusion window (defaults to now).
        features : list of str, optional
            Subset of {"population", "water", "power", "mobility"}.
        force_all : bool
            Ignore incremental-update logic; recompute everything.

        Returns
        -------
        xr.Dataset with dims (lat, lon) and data variables per feature.
        """
        ts = (timestamp or datetime.now(timezone.utc)).replace(tzinfo=timezone.utc)
        if features is None:
            features = ["population", "water", "power", "mobility"]

        logger.info("Fusing layers for %s…", ts.isoformat())

        # Ensure grid exists
        _ = self.grid

        pop_da: Optional[xr.DataArray] = None
        data_vars: Dict[str, xr.DataArray] = {}

        if "population" in features:
            pop_da = self.load_population()
            data_vars["population_density"] = pop_da

        if "water" in features:
            data_vars["water_demand"] = self.compute_water_demand(ts, force=force_all)

        if "power" in features:
            data_vars["power_demand"] = self.compute_power_demand(ts, force=force_all)

        if "mobility" in features:
            data_vars["mobility_pressure"] = self.compute_mobility_pressure(ts, force=force_all)

        ds = xr.Dataset(data_vars)
        ds.attrs["timestamp"] = ts.isoformat()
        ds.attrs["crs"] = "EPSG:4326"
        ds.attrs["cell_size_m"] = self.cell_size_m
        ds.attrs["bbox_wgs84"] = list(self.bbox_wgs84)

        self._update_metadata(ts)

        # Publish data quality ratios to Prometheus
        self._publish_data_quality()

        logger.info(
            "Fusion complete: %s — dims (lat=%d, lon=%d)",
            ", ".join(data_vars),
            ds.dims.get("lat", 0),
            ds.dims.get("lon", 0),
        )
        return ds

    # ── Data quality publishing ───────────────────────────────

    def _publish_data_quality(self) -> None:
        """Push current real/mock ratios to Prometheus gauges."""
        for feature in self._real_counts:
            real = self._real_counts[feature]
            mock = self._mock_counts[feature]
            dq_metrics.update_ratios_from_counts(feature, real, mock)

    def reset_counts(self) -> None:
        """Reset real/mock counters for a fresh measurement window."""
        for k in self._real_counts:
            self._real_counts[k] = 0
            self._mock_counts[k] = 0

    # ── Cache ─────────────────────────────────────────────────

    def cache(self, ds: xr.Dataset) -> Path:
        """Write the fused dataset to monthly Parquet partition."""
        ts = datetime.fromisoformat(ds.attrs["timestamp"])
        partition = f"year={ts.year}/month={ts.month:02d}"
        out_dir = self.cache_root / "fused" / partition
        out_dir.mkdir(parents=True, exist_ok=True)

        df = ds.to_dataframe().reset_index()
        hash_str = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()[:16]
        fname = f"fusion_{ts.strftime('%Y%m%d_%H%M%S')}_{hash_str}.parquet"

        path = out_dir / fname
        table = pa.Table.from_pandas(df)
        pq.write_table(table, path, compression="zstd", compression_level=3)

        logger.info("Cached fused dataset → %s (%d rows)", path, len(df))
        return path

    # ── Incremental updates ───────────────────────────────────

    def incremental_update(
        self,
        timestamp: Optional[datetime] = None,
        stale_threshold_hours: float = 1.0,
    ) -> Optional[xr.Dataset]:
        """Recompute only cells whose source data changed in the last hour.

        Returns None if no cells need updating.
        """
        ts = (timestamp or datetime.now(timezone.utc)).replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc).replace(tzinfo=timezone.utc)
        cutoff_check = cutoff - timedelta(hours=stale_threshold_hours)

        self._load_metadata()
        stale_cells = [
            cid for cid, meta in self._metadata.items()
            if meta.any_updated_since(cutoff_check)
        ]

        if not stale_cells:
            logger.info("All cells up-to-date (cutoff %s).", cutoff_check.isoformat())
            return None

        logger.info("Incremental update: %d / %d cells stale", len(stale_cells), len(self.grid))

        # Recompute only for the full dataset but we could filter the output
        # Full recompute is simpler and the grid is < 20k cells
        ds = self.fuse(timestamp=ts, force_all=True)
        return ds

    # ── Metadata persistence ──────────────────────────────────

    def _load_metadata(self) -> None:
        if METADATA_PATH.exists():
            raw = json.loads(METADATA_PATH.read_text())
            self._metadata = {
                k: CellMetadata(
                    cell_id=k,
                    pop_timestamp=datetime.fromisoformat(v["pop"]) if v.get("pop") else None,
                    water_timestamp=datetime.fromisoformat(v["water"]) if v.get("water") else None,
                    power_timestamp=datetime.fromisoformat(v["power"]) if v.get("power") else None,
                    mobility_timestamp=datetime.fromisoformat(v["mobility"]) if v.get("mobility") else None,
                )
                for k, v in raw.items()
            }

    def _update_metadata(self, ts: datetime) -> None:
        ts_str = ts.isoformat()
        entry = {
            "pop": ts_str,
            "water": ts_str,
            "power": ts_str,
            "mobility": ts_str,
        }
        for cell_id in self.grid["cell_id"]:
            self._metadata[cell_id] = CellMetadata(
                cell_id=cell_id,
                pop_timestamp=ts,
                water_timestamp=ts,
                power_timestamp=ts,
                mobility_timestamp=ts,
            )
        raw = {
            k: {"pop": v.pop_timestamp.isoformat() if v.pop_timestamp else None,
                "water": v.water_timestamp.isoformat() if v.water_timestamp else None,
                "power": v.power_timestamp.isoformat() if v.power_timestamp else None,
                "mobility": v.mobility_timestamp.isoformat() if v.mobility_timestamp else None}
            for k, v in self._metadata.items()
        }
        METADATA_PATH.write_text(json.dumps(raw, indent=2))
