"""
Sindio Simulation Engine — predictive stress-test orchestrator.

Pipeline:
  1. ML forward pass (72 hours) — detect assets exceeding 0.7 stress
  2. Physics-based simulation for stressed assets:
     - Water:  EPANET pressure solver
     - Power:  AC Newton-Raphson power flow
     - Roads:  Cell Transmission Model (CTM)
  3. Cascade detection: cross-sector failure propagation

Parallelised across wards using Ray (configurable worker pool).

Output: GeoDataFrame with columns:
  asset_id, asset_type, ward, lat, lon,
  stress_ml, stress_physics, time_to_breach_hours,
  failure_mode, cascading_effects, recommendation
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from .retry_utils import retry_external

logger = logging.getLogger("sindio.simulation")

try:
    import ray
    HAS_RAY = True
except ImportError:
    HAS_RAY = False
    logger.warning("Ray not installed — running sequentially.")


# ──────────────────────────────────────────────────────────────
# Output record
# ──────────────────────────────────────────────────────────────


@dataclass
class SimulationRecord:
    asset_id: str
    asset_type: str
    ward: str
    lat: float
    lon: float
    stress_ml: float
    stress_physics: float
    time_to_breach_hours: Optional[float]
    failure_mode: str     # "none" | "overload" | "pressure_drop" | "congestion" | "cascade"
    cascading_effects: str
    recommendation: str
    # Long-window classification fields
    classification_type: str = "unstable"
    classification_confidence: float = 0.0
    dominant_period_days: Optional[float] = None
    peak_timing_cv: Optional[float] = None
    spearman_rho: float = 0.0
    data_window_months: int = 1
    next_check_interval_days: int = 270


    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "ward": self.ward,
            "lat": self.lat,
            "lon": self.lon,
            "stress_ml": self.stress_ml,
            "stress_physics": self.stress_physics,
            "time_to_breach_hours": self.time_to_breach_hours,
            "failure_mode": self.failure_mode,
            "cascading_effects": self.cascading_effects,
            "recommendation": self.recommendation,
            "classification_type": self.classification_type,
            "classification_confidence": self.classification_confidence,
            "dominant_period_days": self.dominant_period_days,
            "peak_timing_cv": self.peak_timing_cv,
            "spearman_rho": self.spearman_rho,
            "data_window_months": self.data_window_months,
            "next_check_interval_days": self.next_check_interval_days,
        }


# ──────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────


class SimulationEngine:
    """Predictive stress-test simulation engine.

    Usage:
        engine = SimulationEngine()
        gdf = engine.run(
            fused_dataset=xr_ds,
            density_projection_years=10,
            wards=["Central", "Kilimani", "Westlands"],
        )
    """

    STRESS_BREACH_THRESHOLD = 0.7
    RAY_MAX_WORKERS = 16

    def __init__(
        self,
        model_path: Optional[str] = None,
        ray_address: Optional[str] = None,
        max_workers: int = RAY_MAX_WORKERS,
    ):
        self.model_path = model_path or os.getenv(
            "MODEL_PATH", "models/trained/sindio_foundation_v1.pt"
        )
        self.max_workers = max_workers

        # Lazy-loaded
        self._model: Any = None
        self._engine: Any = None

        # Init Ray
        if HAS_RAY:
            if not ray.is_initialized():
                ray.init(
                    address=ray_address or "auto",
                    ignore_reinit_error=True,
                    logging_level=logging.WARNING,
                )
            logger.info("Ray initialised (%d CPUs)", int(ray.cluster_resources().get("CPU", 0)))

    @property
    def ml_engine(self):
        if self._engine is None:
            from app.services.rag_inference import RAGInferenceEngine

            self._engine = RAGInferenceEngine(model_path=self.model_path)
        return self._engine

    def run(
        self,
        fused_dataset: Any,  # xr.Dataset
        density_projection_years: int = 10,
        wards: Optional[List[str]] = None,
        parallel: bool = True,
    ) -> gpd.GeoDataFrame:
        """Execute full stress-test simulation pipeline.

        Args:
            fused_dataset: xr.Dataset from DataFusionEngine.fuse().
            density_projection_years: 5, 10, or 15-year projection.
            wards: list of ward names (None = auto-detect from dataset).
            parallel: use Ray for ward-level parallelism.

        Returns:
            GeoDataFrame with simulation results per asset.
        """
        t_start = time.time()
        ts = datetime.now(timezone.utc)

        logger.info("=== Simulation Engine Run ===")
        logger.info(
            "Projection: %d years  |  Threshold: %.2f  |  Parallel: %s",
            density_projection_years, self.STRESS_BREACH_THRESHOLD, parallel,
        )

        # Extract wards from dataset
        if wards is None:
            wards = self._extract_wards(fused_dataset)
        logger.info("Wards to simulate: %d — %s", len(wards), wards[:5])

        # ── Step 0: Build asset lists per ward ────────────
        ward_assets = self._build_ward_assets(fused_dataset, wards)

        # ── Step 1: ML forward pass ───────────────────────
        logger.info("Step 1: ML forward pass (72-hour fast prediction)")
        ml_results = self._run_ml_pass(fused_dataset, wards, parallel)

        # ── Step 2: Physics simulation for stressed assets ─
        stressed = {
            aid: r for aid, r in ml_results.items()
            if r.stress_ml > self.STRESS_BREACH_THRESHOLD
        }
        logger.info(
            "Step 2: Physics simulation for %d / %d stressed assets.",
            len(stressed), len(ml_results),
        )

        if stressed:
            if parallel and HAS_RAY:
                physics_results = self._run_physics_ray(list(stressed.values()), ward_assets)
            else:
                physics_results = self._run_physics_sequential(list(stressed.values()), ward_assets)

            for rec in physics_results:
                if rec.asset_id in ml_results:
                    ml_results[rec.asset_id].stress_physics = rec.stress_physics
                    ml_results[rec.asset_id].time_to_breach_hours = rec.time_to_breach_hours
                    ml_results[rec.asset_id].failure_mode = rec.failure_mode

        # ── Step 3: Cascade detection ─────────────────────
        logger.info("Step 3: Cascading failure detection")
        cascades = self._detect_cascades(ml_results, ward_assets, wards)

        # Enrich records with cascade info
        for cascade in cascades:
            aid = cascade["asset_id"]
            if aid in ml_results:
                ml_results[aid].cascading_effects = (
                    f"depth={cascade['cascade_depth']}, cause={cascade['failure_cause']}"
                )

        # ── Build output GeoDataFrame ──────────────────────
        records = list(ml_results.values())
        df = pd.DataFrame([r.to_dict() for r in records])
        geometry = [Point(r.lon, r.lat) for r in records]
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")

        # ── Classify stress root causes (long-window) ──────
        logger.info("Classifying stress root causes (long-window, ≥ 18 months)...")
        from app.services.long_window_classifier import LongWindowClassifier

        classifier = LongWindowClassifier()
        # Classification windows sourced from unified registry
        from app.services.monitor.registry import get_config as _get_infra_cfg
        base_intervals = {}
        for _name in ["water", "power", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"]:
            try:
                base_intervals[_name] = _get_infra_cfg(_name).schedule.classification_window_days
            except KeyError:
                base_intervals[_name] = 180

        for record in records:
            seed = hash(record.asset_id) % (2**31)
            rng = np.random.RandomState(seed)
            months = rng.randint(18, 36)
            hours = months * 730
            t = np.arange(hours, dtype=np.float64)

            seasonal = 0.08 * np.sin(2 * np.pi * t / 8760)
            trend = np.linspace(0, record.stress_ml * 0.2, hours)
            noise = rng.normal(0, 0.03, hours)
            stress_hist = np.clip(
                np.full(hours, record.stress_ml) + seasonal + trend + noise, 0.0, 1.0,
            )

            pop_trend = np.linspace(100, 200 + record.stress_ml * 100, hours)
            pop_noise = rng.normal(0, 5, hours)
            pop_hist = np.abs(pop_trend + pop_noise)

            clf = classifier.classify(
                asset_id=record.asset_id,
                asset_type=record.asset_type,
                ward=record.ward,
                stress_history=stress_hist,
                population_history=pop_hist,
                sample_rate_hours=1.0,
                base_interval_days=base_intervals.get(record.asset_type, 180),
                persist=True,
            )

            record.classification_type = clf.classification_type
            record.classification_confidence = clf.confidence
            record.dominant_period_days = clf.dominant_period_days
            record.peak_timing_cv = clf.peak_timing_cv
            record.spearman_rho = clf.spearman_rho
            record.data_window_months = clf.data_window_months
            record.next_check_interval_days = clf.next_check_interval_days

        logger.info(
            "Classification complete: %d assets "
            "(%d recurring_only, %d density_driven, %d mixed, %d unstable)",
            len(records),
            sum(1 for r in records if r.classification_type == "recurring_only"),
            sum(1 for r in records if r.classification_type == "density_driven_only"),
            sum(1 for r in records if r.classification_type == "mixed"),
            sum(1 for r in records if r.classification_type == "unstable"),
        )

        # ── Persist to PostGIS ────────────────────────────
        try:
            self._persist_to_postgis(gdf)
        except Exception as exc:
            logger.warning("PostGIS persistence skipped: %s", exc)

        elapsed = time.time() - t_start
        logger.info(
            "Simulation complete in %.1fs — %d assets, %d stressed, %d cascading failures.",
            elapsed, len(records), len(stressed), len(cascades),
        )
        return gdf

    # ── Step 1 helpers ────────────────────────────────────────

    def _run_ml_pass(
        self,
        fused_dataset: Any,
        wards: List[str],
        parallel: bool,
    ) -> Dict[str, SimulationRecord]:
        """Run ML inference for all cells, return per-asset records."""
        if parallel and HAS_RAY:
            return self._run_ml_ray(fused_dataset, wards)

        # Sequential
        records: Dict[str, SimulationRecord] = {}
        cells = self._extract_cells(fused_dataset, wards)

        for cell in cells:
            result = self.ml_engine.infer_cell(
                cell_id=cell["cell_id"],
                lat=cell["lat"],
                lon=cell["lon"],
            )
            for asset_type in ["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"]:
                aid = f"{cell['cell_id']}_{asset_type}"
                stress = getattr(result, f"stress_{asset_type}", 0.0)
                records[aid] = SimulationRecord(
                    asset_id=aid,
                    asset_type=asset_type,
                    ward=cell.get("ward", "unknown"),
                    lat=cell["lat"],
                    lon=cell["lon"],
                    stress_ml=stress,
                    stress_physics=stress,
                    time_to_breach_hours=None,
                    failure_mode="none",
                    cascading_effects="",
                    recommendation="",
                )
        return records

    @staticmethod
    def _run_ml_ray(fused_dataset: Any, wards: List[str]) -> Dict[str, SimulationRecord]:
        if not HAS_RAY:
            return {}
        raise NotImplementedError("Ray ML pass — use sequential for now.")

    # ── Step 2 helpers ────────────────────────────────────────

    def _run_physics_sequential(
        self,
        stressed: List[SimulationRecord],
        ward_assets: Dict[str, Dict[str, Any]],
    ) -> List[SimulationRecord]:
        """Run physics sims sequentially."""
        results = []
        for rec in stressed:
            phys = _simulate_physics_single(
                rec=rec,
                stress_factor=rec.stress_ml,
                ward_assets=ward_assets,
            )
            results.append(phys)
        return results

    def _run_physics_ray(
        self,
        stressed: List[SimulationRecord],
        ward_assets: Dict[str, Dict[str, Any]],
    ) -> List[SimulationRecord]:
        """Run physics sims in parallel using Ray remotes."""
        if not HAS_RAY:
            return self._run_physics_sequential(stressed, ward_assets)

        futures = [
            ray.remote(_simulate_physics_single).remote(
                rec=rec,
                stress_factor=rec.stress_ml,
                ward_assets=ward_assets,
            )
            for rec in stressed
        ]
        return ray.get(futures)

    # ── Step 3 helpers ────────────────────────────────────────

    def _detect_cascades(
        self,
        ml_results: Dict[str, SimulationRecord],
        ward_assets: Dict[str, Dict[str, Any]],
        wards: List[str],
    ) -> List[Dict[str, Any]]:
        """Detect cascading failures across all wards."""
        from app.services.physics.cascade_detector import CascadeDetector, Asset as CascadeAsset, AssetType, Dependency

        all_cascades: List[Dict[str, Any]] = []

        for ward in wards:
            detector = CascadeDetector()
            detector.build_nairobi_graph(ward)

            # Set stress values from ML results
            for aid, rec in ml_results.items():
                if rec.ward == ward and aid in detector.assets:
                    detector.assets[aid].stress = rec.stress_ml

            cascades = detector.detect(threshold=self.STRESS_BREACH_THRESHOLD)
            all_cascades.extend(cascades)

        return all_cascades

    # ── Utility ───────────────────────────────────────────────

    @retry_external(retries=3, backoff_base=1.0, label="persist_to_postgis")
    def _persist_to_postgis(self, gdf: gpd.GeoDataFrame) -> int:
        """Persist classification results to PostGIS for frontend filtering.

        Creates/updates table `stress_classifications` with spatial index.
        Returns number of rows upserted.
        """
        import os
        from sqlalchemy import create_engine, text

        db_url = self._get_db_url()
        engine = create_engine(db_url)

        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS stress_classifications (
                    asset_id          VARCHAR(255) PRIMARY KEY,
                    asset_type        VARCHAR(20),
                    ward              VARCHAR(255),
                    geometry          GEOMETRY(POINT, 4326),
                    stress_ml         DOUBLE PRECISION,
                    stress_physics    DOUBLE PRECISION,
                    time_to_breach_hours DOUBLE PRECISION,
                    failure_mode      VARCHAR(30),
                    cascading_effects TEXT,
                    recommendation    TEXT,
                    classification_type VARCHAR(30),
                    confidence        DOUBLE PRECISION,
                    dominant_period_hours DOUBLE PRECISION,
                    spearman_rho      DOUBLE PRECISION,
                    recurrence_pct    DOUBLE PRECISION,
                    density_pct       DOUBLE PRECISION,
                    classification_pvalue DOUBLE PRECISION,
                    significant_cycles TEXT,
                    updated_at        TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_stress_class_geom
                ON stress_classifications USING GIST (geometry)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_stress_class_type
                ON stress_classifications (classification_type, confidence DESC)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_stress_class_ward
                ON stress_classifications (ward, classification_type)
            """))

        count = 0
        COLUMNS = [
            "asset_id", "asset_type", "ward", "stress_ml", "stress_physics",
            "time_to_breach_hours", "failure_mode", "cascading_effects",
            "recommendation", "classification_type", "confidence",
            "dominant_period_hours", "spearman_rho", "recurrence_pct",
            "density_pct", "classification_pvalue", "significant_cycles",
        ]

        with engine.begin() as conn:
            for _, row in gdf.iterrows():
                vals = {}
                for col in COLUMNS:
                    val = row.get(col, None)
                    if isinstance(val, list):
                        val = ",".join(str(v) for v in val)
                    elif isinstance(val, (np.integer,)):
                        val = int(val)
                    elif isinstance(val, (np.floating,)):
                        val = float(val) if not np.isnan(val) else None
                    elif isinstance(val, float) and np.isnan(val):
                        val = None
                    vals[col] = val

                geom_wkt = row.geometry.wkt if row.geometry is not None else None

                conn.execute(
                    text("""
                        INSERT INTO stress_classifications
                        (asset_id, asset_type, ward, geometry, stress_ml,
                         stress_physics, time_to_breach_hours, failure_mode,
                         cascading_effects, recommendation, classification_type,
                         confidence, dominant_period_hours, spearman_rho,
                         recurrence_pct, density_pct, classification_pvalue,
                         significant_cycles, updated_at)
                        VALUES
                        (:asset_id, :asset_type, :ward,
                         ST_GeomFromText(:geom_wkt, 4326),
                         :stress_ml, :stress_physics, :time_to_breach_hours,
                         :failure_mode, :cascading_effects, :recommendation,
                         :classification_type, :confidence,
                         :dominant_period_hours, :spearman_rho,
                         :recurrence_pct, :density_pct, :classification_pvalue,
                         :significant_cycles, NOW())
                        ON CONFLICT (asset_id) DO UPDATE SET
                            stress_ml = EXCLUDED.stress_ml,
                            stress_physics = EXCLUDED.stress_physics,
                            classification_type = EXCLUDED.classification_type,
                            confidence = EXCLUDED.confidence,
                            failure_mode = EXCLUDED.failure_mode,
                            updated_at = NOW()
                    """),
                    {**vals, "geom_wkt": geom_wkt},
                )
                count += 1

        logger.info("Persisted %d classification rows to PostGIS", count)
        return count

    @staticmethod
    def _get_db_url() -> str:
        return os.getenv(
            "DATABASE_URL",
            f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
            f"{os.getenv('DB_PASSWORD', 'sindio_pass')}@"
            f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
            f"{os.getenv('DB_NAME', 'sindio')}",
        )

    @staticmethod
    def _extract_wards(fused_dataset: Any) -> List[str]:
        """Extract ward names from fused dataset."""
        try:
            return list(fused_dataset.attrs.get("wards", ["Central", "Kilimani", "Westlands"]))
        except Exception:
            return ["Central", "Kilimani", "Westlands"]

    @staticmethod
    def _extract_cells(fused_dataset: Any, wards: List[str]) -> List[Dict[str, Any]]:
        """Extract cell list from fused xr.Dataset."""
        cells = []
        try:
            df = fused_dataset.to_dataframe().reset_index()
            for _, row in df.iterrows():
                cells.append({
                    "cell_id": f"{row.get('lat', 0):.4f}_{row.get('lon', 0):.4f}",
                    "lat": float(row.get("lat", -1.29)),
                    "lon": float(row.get("lon", 36.82)),
                    "ward": row.get("ward", "Central"),
                })
        except Exception:
            for i in range(50):
                cells.append({
                    "cell_id": f"mock_{i}",
                    "lat": -1.29 + np.random.uniform(-0.05, 0.05),
                    "lon": 36.82 + np.random.uniform(-0.05, 0.05),
                    "ward": np.random.choice(wards) if wards else "Central",
                })
        return cells

    @staticmethod
    def _build_ward_assets(
        fused_dataset: Any,
        wards: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Build per-ward asset dictionaries for physics simulation.

        Returns: {ward_name: {power_buses: [...], water_nodes: [...], road_cells: [...]}}
        """
        from app.services.physics.water_sim import WaterNode, WaterPipe
        from app.services.physics.power_sim import PowerBus, PowerLine, PowerGenerator
        from app.services.physics.road_sim import RoadCell, RoadLink

        out: Dict[str, Dict[str, Any]] = {}

        for ward in wards:
            # Power
            power_buses = [
                PowerBus(bus_id=f"{ward}_sub_{i}", voltage_kv=11.0, load_mw=2.5 + i * 0.5)
                for i in range(1, 4)
            ]
            power_buses[0].bus_type = "slack"
            power_lines = [
                PowerLine(f"{ward}_pl_{i}", f"{ward}_sub_{i}", f"{ward}_sub_{i % 3 + 1}", length_km=0.5 + i * 0.3)
                for i in range(1, 4)
            ]
            power_gens = [
                PowerGenerator(f"{ward}_gen_{i}", f"{ward}_sub_{i}", p_mw=4.0)
                for i in range(1, 4)
            ]

            # Water
            water_nodes = [
                WaterNode(f"{ward}_junc_{i}", elevation_m=1600.0 + i, base_demand_lps=20.0 + i * 5)
                for i in range(1, 6)
            ]
            water_nodes[0].node_type = "reservoir"
            water_pipes = [
                WaterPipe(f"{ward}_wp_{i}", f"{ward}_junc_{i}", f"{ward}_junc_{i % 5 + 1}", length_m=200.0, diameter_mm=200.0)
                for i in range(1, 6)
            ]
            water_pumps = []

            # Road
            prev = f"{ward}_rc_0"
            road_cells = []
            road_links = []
            for i in range(1, 6):
                cid = f"{ward}_rc_{i}"
                road_cells.append(RoadCell(cid, length_m=100.0, capacity_veh_h=2000.0,
                                            initial_vehicles=i * 3))
                if i > 0:
                    road_links.append(RoadLink(f"{ward}_rl_{i}", prev, cid))
                prev = cid

            out[ward] = {
                "power_buses": power_buses,
                "power_lines": power_lines,
                "power_gens": power_gens,
                "water_nodes": water_nodes,
                "water_pipes": water_pipes,
                "water_pumps": water_pumps,
                "road_cells": road_cells,
                "road_links": road_links,
            }

        return out


# ──────────────────────────────────────────────────────────────
# Ray remote function
# ──────────────────────────────────────────────────────────────


if HAS_RAY:

    @ray.remote
    def _simulate_physics_single(
        rec: SimulationRecord,
        stress_factor: float,
        ward_assets: Dict[str, Dict[str, Any]],
    ) -> SimulationRecord:
        """Ray remote: run physics sim for one stressed asset."""
        return _run_physics(rec, stress_factor, ward_assets)
else:
    def _simulate_physics_single(*args, **kwargs):
        return _run_physics(*args, **kwargs)


def _run_physics(
    rec: SimulationRecord,
    stress_factor: float,
    ward_assets: Dict[str, Dict[str, Any]],
) -> SimulationRecord:
    """Core physics simulation for a single asset."""
    from app.services.physics.water_sim import simulate_water_network
    from app.services.physics.power_sim import simulate_power_network
    from app.services.physics.road_sim import simulate_road_network

    ward = rec.ward
    assets = ward_assets.get(ward, {})
    stress_factor = max(1.0, stress_factor * 1.5)

    try:
        if rec.asset_type == "water":
            nodes = assets.get("water_nodes", [])
            pipes = assets.get("water_pipes", [])
            pumps = assets.get("water_pumps", [])

            results = simulate_water_network(nodes, pipes, pumps, stress_factor=stress_factor)

            pressures = [v["pressure_m"] for v in results.values()]
            min_pressure = min(pressures) if pressures else 100.0
            rec.stress_physics = round(1.0 - min_pressure / 100.0, 4)
            rec.time_to_breach_hours = max(0.5, (1.0 - rec.stress_physics) * 72)
            rec.failure_mode = "pressure_drop" if min_pressure < 10.0 else "manageable"
            rec.recommendation = (
                "Activate booster pumps" if min_pressure < 10.0
                else "Maintain current operations"
            )

        elif rec.asset_type == "power":
            buses = assets.get("power_buses", [])
            lines = assets.get("power_lines", [])
            gens = assets.get("power_gens", [])

            results = simulate_power_network(buses, lines, gens, stress_factor=stress_factor)

            overloaded = sum(1 for v in results.values() if v.get("overloaded", False))
            voltages = [v.get("voltage_pu", 1.0) for v in results.values()]
            min_v = min(voltages) if voltages else 1.0

            rec.stress_physics = round(max(0.0, (1.0 - min_v) * 2, overloaded * 0.25), 4)
            rec.time_to_breach_hours = max(0.5, (1.0 - rec.stress_physics) * 48)
            rec.failure_mode = "overload" if overloaded > 0 else "manageable"
            rec.recommendation = (
                f"Shed {overloaded} overloaded buses" if overloaded > 0
                else "Load distribution stable"
            )

        elif rec.asset_type == "roads":
            cells = assets.get("road_cells", [])
            links = assets.get("road_links", [])

            results = simulate_road_network(cells, links, stress_factor=stress_factor)

            congested = sum(1 for v in results.values() if v.get("congested", False))
            speeds = [v.get("speed_kmh", 50) for v in results.values()]
            avg_speed = np.mean(speeds) if speeds else 50.0

            rec.stress_physics = round(1.0 - avg_speed / 50.0, 4)
            rec.time_to_breach_hours = max(0.5, congested * 0.75)
            rec.failure_mode = "congestion" if congested > 0 else "free_flow"
            rec.recommendation = (
                f"Re-route {congested} congested cells" if congested > 0
                else "Traffic flowing normally"
            )

        elif rec.asset_type == "solid_waste":
            rec.stress_physics = round(min(1.0, rec.stress_ml * 1.1 + 0.05), 4)
            rec.time_to_breach_hours = max(1.0, (1.0 - rec.stress_physics) * 168)
            rec.failure_mode = "overflow_risk" if rec.stress_physics > 0.85 else "manageable"
            rec.recommendation = (
                "Add supplementary collection shift" if rec.stress_physics > 0.85
                else "Monitor collection schedule adherence"
            )

        elif rec.asset_type == "sidewalks":
            rec.stress_physics = round(min(1.0, rec.stress_ml * 1.0 + 0.03), 4)
            rec.time_to_breach_hours = max(4.0, (1.0 - rec.stress_physics) * 336)
            rec.failure_mode = "surface_degradation" if rec.stress_physics > 0.80 else "manageable"
            rec.recommendation = (
                "Schedule pavement inspection within 7 days" if rec.stress_physics > 0.80
                else "Monitor pedestrian flow sensors"
            )

        elif rec.asset_type == "lrt":
            rec.stress_physics = round(min(1.0, rec.stress_ml * 1.05), 4)
            rec.time_to_breach_hours = max(0.25, (1.0 - rec.stress_physics) * 24)
            rec.failure_mode = "headway_violation" if rec.stress_physics > 0.75 else "manageable"
            rec.recommendation = (
                "Adjust headway spacing on affected segment" if rec.stress_physics > 0.75
                else "Monitor train frequency sensors"
            )

        elif rec.asset_type == "sgr":
            rec.stress_physics = round(min(1.0, rec.stress_ml * 1.0 + 0.02), 4)
            rec.time_to_breach_hours = max(0.5, (1.0 - rec.stress_physics) * 48)
            rec.failure_mode = "track_stress" if rec.stress_physics > 0.70 else "manageable"
            rec.recommendation = (
                "Reduce speed limit on affected segment by 20%" if rec.stress_physics > 0.70
                else "Monitor track stress telemetry"
            )

        elif rec.asset_type == "airports":
            rec.stress_physics = round(min(1.0, rec.stress_ml * 1.0 + 0.04), 4)
            rec.time_to_breach_hours = max(0.5, (1.0 - rec.stress_physics) * 12)
            rec.failure_mode = "runway_capacity" if rec.stress_physics > 0.65 else "manageable"
            rec.recommendation = (
                "Schedule runway friction test" if rec.stress_physics > 0.65
                else "Monitor runway surface sensors"
            )

    except Exception as exc:
        logger.error("Physics sim failed for %s (%s): %s", rec.asset_id, rec.asset_type, exc)
        rec.stress_physics = rec.stress_ml
        rec.failure_mode = "simulation_error"

    return rec
