"""
Sindio — Unified Infrastructure Monitor
========================================

Single parameterized class that handles ALL infrastructure types.
Infrastructure type is just a config key read from the registry.

Pipeline:
  1. Real-time data ingestion (DB, Kafka, API, or fallback)
  2. Historical baseline comparison
  3. Official report integration
  4. Stress calculation (physics engine or heuristic)
  5. Asset-level stress scoring + alert generation

Usage:
    from app.services.monitor import InfrastructureMonitor, get_all_stressed_assets

    # Monitor a single type
    mon = InfrastructureMonitor("power")
    results = mon.run()

    # Monitor all types at once
    all_stressed = get_all_stressed_assets()
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .registry import (
    InfraConfig,
    InfraDataSource,
    PhysicsEngine,
    get_all_configs,
    get_config,
)
from .ingestion import DataIngestor
from .baseline import BaselineComparator
from .reports import ReportIntegrator
from .stress import StressCalculator

logger = logging.getLogger("sindio.monitor")


@dataclass
class AssetState:
    """State of a single monitored asset."""
    asset_id: str
    infrastructure_type: str
    ward: str = ""
    lat: float = 0.0
    lon: float = 0.0
    current_value: float = 0.0          # actual measured value
    capacity: float = 100.0              # max capacity
    stress: float = 0.0                  # 0.0–1.0
    baseline_stress: float = 0.0         # historical baseline
    baseline_deviation: float = 0.0      # current - baseline
    data_source: str = "unknown"         # which source provided the data
    data_freshness_sec: float = 0.0      # age of the data
    is_mock: bool = False                # True if data came from fallback
    failure_mode: str = "none"
    time_to_breach_hours: Optional[float] = None
    recommendation: str = ""
    confidence: float = 0.0
    report_aligned: bool = True          # True if consistent with official reports
    report_notes: str = ""
    timestamp: str = ""


@dataclass
class MonitorResult:
    """Result of one monitoring run for a single infrastructure type."""
    infrastructure_type: str
    display_name: str
    run_timestamp: str
    total_assets: int
    stressed_assets: int
    critical_assets: int
    warning_assets: int
    healthy_assets: int
    mock_data_ratio: float               # fraction of assets using mock data
    avg_stress: float
    avg_confidence: float
    avg_baseline_deviation: float
    report_alignment_pct: float
    assets: List[AssetState] = field(default_factory=list)


class InfrastructureMonitor:
    """Unified monitor for one infrastructure type.

    The infrastructure type is just a config key. The same class handles
    power, water, roads, solid_waste, sidewalks, lrt, sgr, and airports
    identically — only the config changes.
    """

    def __init__(self, infra_type: str, db_url: Optional[str] = None):
        self.config = get_config(infra_type)
        self.db_url = db_url
        self.ingestor = DataIngestor(self.config, db_url)
        self.baseline = BaselineComparator(self.config)
        self.reports = ReportIntegrator(self.config)
        self.calculator = StressCalculator(self.config)
        self._last_result: Optional[MonitorResult] = None

    @property
    def infra_type(self) -> str:
        return self.config.name

    def run(
        self,
        ward: Optional[str] = None,
        force_mock: bool = False,
        include_healthy: bool = False,
    ) -> MonitorResult:
        """Execute full monitoring pipeline.

        Args:
            ward: limit to one ward (None = all wards)
            force_mock: use fallback data even if real sources available
            include_healthy: include non-stressed assets in results

        Returns:
            MonitorResult with all asset states and summary stats.
        """
        t_start = time.time()
        now = datetime.now(timezone.utc)
        ts = now.isoformat()

        logger.info(
            "[%s] Starting monitor run (ward=%s, force_mock=%s)",
            self.config.display_name, ward, force_mock,
        )

        # ── Step 1: Ingest real-time data ──────────────────────
        try:
            raw_data = self.ingestor.ingest(force_mock=force_mock)
        except RuntimeError as exc:
            logger.warning("[%s] Ingestion error: %s", self.config.display_name, exc)
            raw_data = []
        logger.info(
            "[%s] Ingested %d data points (%.0f%% mock)",
            self.config.display_name, len(raw_data),
            self.ingestor.mock_ratio * 100,
        )

        # ── Step 2: Build asset states ─────────────────────────
        assets = self._build_assets(raw_data, now)

        # Filter by ward if specified
        if ward:
            assets = [a for a in assets if a.ward.lower() == ward.lower()]

        # ── Step 3: Baseline comparison ────────────────────────
        for asset in assets:
            baseline_stress = self.baseline.get_baseline(
                asset.asset_id, asset.infrastructure_type, now
            )
            asset.baseline_stress = baseline_stress
            asset.baseline_deviation = round(asset.stress - baseline_stress, 4)

        # ── Step 4: Report alignment ───────────────────────────
        report_status = self.reports.check_alignment(assets, now)
        for asset in assets:
            asset.report_aligned = report_status.get(asset.asset_id, True)
            asset.report_notes = report_status.get(f"{asset.asset_id}_notes", "")

        # ── Step 5: Classify and compute recommendations ───────
        for asset in assets:
            self._classify_asset(asset)

        # ── Build result ───────────────────────────────────────
        stressed = [a for a in assets if a.stress >= self.config.thresholds.warning]
        critical = [a for a in assets if a.stress >= self.config.thresholds.critical]
        warning = [a for a in assets if self.config.thresholds.warning <= a.stress < self.config.thresholds.critical]
        healthy = [a for a in assets if a.stress < self.config.thresholds.warning]

        if not include_healthy:
            result_assets = stressed
        else:
            result_assets = assets

        avg_stress = np.mean([a.stress for a in assets]) if assets else 0.0
        avg_confidence = np.mean([a.confidence for a in assets]) if assets else 0.0
        avg_deviation = np.mean([abs(a.baseline_deviation) for a in assets]) if assets else 0.0
        aligned = sum(1 for a in assets if a.report_aligned)
        report_pct = aligned / len(assets) if assets else 1.0

        result = MonitorResult(
            infrastructure_type=self.config.name,
            display_name=self.config.display_name,
            run_timestamp=ts,
            total_assets=len(assets),
            stressed_assets=len(stressed),
            critical_assets=len(critical),
            warning_assets=len(warning),
            healthy_assets=len(healthy),
            mock_data_ratio=self.ingestor.mock_ratio,
            avg_stress=round(float(avg_stress), 4),
            avg_confidence=round(float(avg_confidence), 4),
            avg_baseline_deviation=round(float(avg_deviation), 4),
            report_alignment_pct=round(report_pct, 4),
            assets=result_assets,
        )

        elapsed = time.time() - t_start
        logger.info(
            "[%s] Monitor complete in %.1fs — %d assets, %d stressed (%d critical)",
            self.config.display_name, elapsed,
            len(assets), len(stressed), len(critical),
        )

        self._last_result = result
        return result

    def _build_assets(self, raw_data: List[Dict[str, Any]], now: datetime) -> List[AssetState]:
        """Convert raw ingested data into AssetState objects."""
        assets: List[AssetState] = []

        for point in raw_data:
            asset_id = point.get("asset_id", f"{self.config.name}_{point.get('id', 'unknown')}")
            current_value = point.get("value", 0.0)
            capacity = point.get("capacity", self.config.default_capacity)

            # Calculate stress via the unified calculator
            stress = self.calculator.compute_stress(point, current_value, capacity)

            # Data freshness
            ts = point.get("timestamp")
            if ts:
                try:
                    data_time = datetime.fromisoformat(ts)
                    if data_time.tzinfo is None:
                        data_time = data_time.replace(tzinfo=timezone.utc)
                    freshness = (now - data_time).total_seconds()
                except (ValueError, TypeError):
                    freshness = 0.0
            else:
                freshness = 0.0

            is_mock = point.get("is_mock", False) or point.get("source", "") == "fallback"

            asset = AssetState(
                asset_id=asset_id,
                infrastructure_type=self.config.name,
                ward=point.get("ward", ""),
                lat=point.get("lat", 0.0),
                lon=point.get("lon", 0.0),
                current_value=round(current_value, 4),
                capacity=capacity,
                stress=round(stress, 4),
                data_source=point.get("source", "unknown"),
                data_freshness_sec=round(freshness, 1),
                is_mock=is_mock,
                timestamp=now.isoformat(),
            )
            assets.append(asset)

        # If no real data came in, generate synthetic assets
        if not assets:
            assets = self._generate_synthetic_assets(now)

        return assets

    def _generate_synthetic_assets(self, now: datetime) -> List[AssetState]:
        """Generate synthetic asset states when no data sources are available."""
        assets: List[AssetState] = []
        rng = np.random.RandomState(hash(self.config.name) % (2 ** 31))

        wards = ["Central", "Kilimani", "Westlands", "Kibera", "Embakasi",
                 "Kasarani", "Dagoretti", "Kamukunji", "Starehe", "Mathare"]

        for i in range(self.config.default_asset_count):
            ward = wards[i % len(wards)]
            base = self.config.heuristic_base_stress
            variance = self.config.heuristic_variance
            stress = float(np.clip(base + rng.normal(0, variance), 0.0, 1.0))
            value = stress * self.config.default_capacity

            asset = AssetState(
                asset_id=f"{self.config.name}_asset_{i:05d}",
                infrastructure_type=self.config.name,
                ward=ward,
                lat=-1.29 + rng.uniform(-0.05, 0.05),
                lon=36.82 + rng.uniform(-0.05, 0.05),
                current_value=round(value, 4),
                capacity=self.config.default_capacity,
                stress=round(stress, 4),
                data_source="synthetic",
                is_mock=True,
                timestamp=now.isoformat(),
            )
            assets.append(asset)

        return assets

    def _classify_asset(self, asset: AssetState) -> None:
        """Set failure_mode, time_to_breach, recommendation, confidence."""
        t = self.config.thresholds

        if asset.stress >= t.breach:
            asset.failure_mode = "breach_imminent"
            asset.time_to_breach_hours = max(0.1, (1.0 - asset.stress) * 12)
            asset.recommendation = self.config.actions.high
            asset.confidence = 0.95
        elif asset.stress >= t.critical:
            asset.failure_mode = "critical"
            asset.time_to_breach_hours = max(0.5, (1.0 - asset.stress) * 24)
            asset.recommendation = self.config.actions.medium
            asset.confidence = 0.85
        elif asset.stress >= t.warning:
            asset.failure_mode = "warning"
            asset.time_to_breach_hours = max(2.0, (1.0 - asset.stress) * 72)
            asset.recommendation = self.config.actions.low
            asset.confidence = 0.75
        else:
            asset.failure_mode = "normal"
            asset.time_to_breach_hours = None
            asset.recommendation = "No action required."
            asset.confidence = 0.90

        # Reduce confidence if data is mock or stale
        if asset.is_mock:
            asset.confidence *= 0.72
        if asset.data_freshness_sec > self.config.data_sources[0].freshness_threshold_sec:
            asset.confidence *= 0.85

        asset.confidence = round(min(asset.confidence, 1.0), 4)


# ── Unified API: get all stressed assets across all types ────────

def get_all_stressed_assets(
    ward: Optional[str] = None,
    force_mock: bool = False,
    min_stress: float = 0.0,
) -> Dict[str, Any]:
    """Run monitoring for ALL infrastructure types and return stressed assets.

    This is the single entry point — one call, all types.

    Args:
        ward: filter to one ward (None = all)
        force_mock: use fallback data for all types
        min_stress: minimum stress threshold to include (0.0 = all stressed)

    Returns:
        Dict with summary + per-type results + combined stressed asset list.
    """
    now = datetime.now(timezone.utc)
    all_assets: List[AssetState] = []
    per_type: List[Dict[str, Any]] = []
    total_mock_ratio = 0.0
    type_count = 0

    for cfg in get_all_configs():
        mon = InfrastructureMonitor(cfg.name)
        result = mon.run(ward=ward, force_mock=force_mock, include_healthy=False)

        # Filter by min_stress
        filtered = [a for a in result.assets if a.stress >= min_stress]

        all_assets.extend(filtered)
        per_type.append({
            "infrastructure_type": result.infrastructure_type,
            "display_name": result.display_name,
            "total_assets": result.total_assets,
            "stressed_assets": len(filtered),
            "critical_assets": result.critical_assets,
            "warning_assets": result.warning_assets,
            "avg_stress": result.avg_stress,
            "mock_data_ratio": result.mock_data_ratio,
            "report_alignment_pct": result.report_alignment_pct,
        })
        total_mock_ratio += result.mock_data_ratio
        type_count += 1

    # Sort by stress descending
    all_assets.sort(key=lambda a: a.stress, reverse=True)

    return {
        "timestamp": now.isoformat(),
        "ward_filter": ward,
        "total_infrastructure_types": type_count,
        "total_assets_monitored": sum(p["total_assets"] for p in per_type),
        "total_stressed_assets": len(all_assets),
        "total_critical_assets": sum(p["critical_assets"] for p in per_type),
        "total_warning_assets": sum(p["warning_assets"] for p in per_type),
        "overall_mock_ratio": round(total_mock_ratio / type_count, 4) if type_count else 0.0,
        "per_type_summary": per_type,
        "stressed_assets": [
            {
                "asset_id": a.asset_id,
                "infrastructure_type": a.infrastructure_type,
                "ward": a.ward,
                "lat": a.lat,
                "lon": a.lon,
                "current_value": a.current_value,
                "capacity": a.capacity,
                "stress": a.stress,
                "baseline_stress": a.baseline_stress,
                "baseline_deviation": a.baseline_deviation,
                "failure_mode": a.failure_mode,
                "time_to_breach_hours": a.time_to_breach_hours,
                "recommendation": a.recommendation,
                "confidence": a.confidence,
                "data_source": a.data_source,
                "is_mock": a.is_mock,
                "report_aligned": a.report_aligned,
                "report_notes": a.report_notes,
                "timestamp": a.timestamp,
            }
            for a in all_assets
        ],
    }
