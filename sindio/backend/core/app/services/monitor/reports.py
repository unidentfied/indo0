"""
Sindio — Official Report Integration
======================================

Checks monitored asset states against official published reports
to detect discrepancies between real-time monitoring and official data.

For each infrastructure type, the config specifies:
  - report_source: name of the official report
  - report_frequency: how often reports are published

This module:
  1. Fetches the latest official report metrics (from DB cache or API)
  2. Compares real-time asset states against report values
  3. Flags assets where real-time data diverges significantly from reports
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from .registry import InfraConfig

logger = logging.getLogger("sindio.reports")


class ReportIntegrator:
    """Official report integration for one infrastructure type."""

    def __init__(self, config: InfraConfig, db_url: Optional[str] = None):
        self.config = config
        self.db_url = db_url or os.getenv(
            "DATABASE_URL",
            f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
            f"{os.getenv('DB_PASSWORD', '')}@"
            f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
            f"{os.getenv('DB_NAME', 'sindio')}",
        )
        self._report_cache: Optional[Dict[str, Any]] = None
        self._cache_time: Optional[datetime] = None

    def check_alignment(
        self, assets: List["AssetState"], now: datetime
    ) -> Dict[str, Any]:
        """Check if asset states align with official reports.

        Returns a dict with:
          - ``aligned_assets``: count of assets that align
          - ``total_assets``: total number of assets inspected
        """
        report_data = self._get_report_data(now)
        total = len(assets)
        aligned = 0
        if not report_data:
            # No report data – assume everything aligns
            aligned = total
            return {"aligned_assets": aligned, "total_assets": total}

        report_metrics = report_data.get("metrics", {})
        report_thresholds = report_data.get("thresholds", {})
        report_date = report_data.get("report_date", "")

        for asset in assets:
            is_aligned, _ = self._check_single_asset(
                asset, report_metrics, report_thresholds, report_date
            )
            if is_aligned:
                aligned += 1
        return {"aligned_assets": aligned, "total_assets": total}

    def _get_report_data(self, now: datetime) -> Optional[Dict[str, Any]]:
        """Fetch the latest official report data.

        Tries:
          1. PostGIS ``report_cache`` table
          2. Falls back to config defaults
        """
        # Use cache if fresh (< 1 hour for daily, < 1 day for monthly)
        if self._cache_time and self._report_cache:
            age = (now - self._cache_time).total_seconds()
            max_age = 3600 if self.config.report_frequency == "daily" else 86400
            if age < max_age:
                return self._report_cache

        # Try PostGIS
        report_data = self._query_report_cache()
        if report_data:
            self._report_cache = report_data
            self._cache_time = now
            return report_data

        # Fallback: generate from config defaults
        logger.info(
            "[%s] No official report data — using config defaults",
            self.config.display_name,
        )
        report_data = {
            "source": self.config.report_source,
            "report_date": now.isoformat(),
            "frequency": self.config.report_frequency,
            "metrics": {
                "avg_stress": self.config.heuristic_base_stress,
                "max_stress": self.config.heuristic_base_stress + self.config.heuristic_variance,
                "asset_count": self.config.default_asset_count,
                "capacity": self.config.default_capacity,
            },
            "thresholds": {
                "warning": self.config.thresholds.warning,
                "critical": self.config.thresholds.critical,
                "breach": self.config.thresholds.breach,
            },
        }
        self._report_cache = report_data
        self._cache_time = now
        return report_data

    def _query_report_cache(self) -> Optional[Dict[str, Any]]:
        """Query the report_cache table from PostGIS."""
        try:
            from sqlalchemy import create_engine, text
            import json

            global _GLOBAL_ENGINES
            if "_GLOBAL_ENGINES" not in globals():
                globals()["_GLOBAL_ENGINES"] = {}

            if self.db_url not in globals()["_GLOBAL_ENGINES"]:
                globals()["_GLOBAL_ENGINES"][self.db_url] = create_engine(
                    self.db_url,
                    pool_size=3,
                    max_overflow=5,
                    pool_timeout=10,
                    pool_recycle=1800
                )

            engine = globals()["_GLOBAL_ENGINES"][self.db_url]
            sql = text(
                """
                SELECT report_data
                FROM report_cache
                WHERE infrastructure_type = :infra_type
                  AND created_at >= NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            with engine.connect() as conn:
                row = conn.execute(sql, {"infra_type": self.config.name}).fetchone()
                if row and row[0]:
                    return json.loads(row[0])
            return None
        except Exception as e:
            logger.debug("Report cache query failed: %s", e)
            return None

    def _check_single_asset(
        self,
        asset: "AssetState",
        report_metrics: Dict[str, Any],
        report_thresholds: Dict[str, Any],
        report_date: str,
    ) -> tuple[bool, str]:
        """Check if one asset aligns with official report data.

        Returns (aligned, notes).
        """
        report_avg = report_metrics.get("avg_stress", 0.5)
        report_max = report_metrics.get("max_stress", 0.8)
        report_warning = report_thresholds.get("warning", 0.6)

        # Asset stress significantly above report max — likely divergent
        if asset.stress > report_max * 1.3:
            return False, (
                f"Stress {asset.stress:.2f} exceeds report max {report_max:.2f} "
                f"by >30%. Report date: {report_date}"
            )

        # Asset is critical but report shows no issues
        if asset.stress >= report_thresholds.get("critical", 0.8):
            if report_avg < report_warning:
                return False, (
                    f"Asset is critical ({asset.stress:.2f}) but report "
                    f"avg is {report_avg:.2f} (below warning). "
                    f"Possible data discrepancy. Report date: {report_date}"
                )

        # Asset stress within expected range
        if asset.stress <= report_max:
            return True, f"Within report range (max={report_max:.2f})"

        # Slightly elevated but not alarming
        return True, (
            f"Slightly above report max ({asset.stress:.2f} vs {report_max:.2f}) "
            f"but within acceptable variance"
        )

    def get_report_summary(self, now: datetime) -> Dict[str, Any]:
        """Get a summary of the latest official report."""
        data = self._get_report_data(now)
        if not data:
            return {
                "report_source": self.config.report_source,
                "available": False,
                "message": "No official report data available",
            }
        return {
            "report_source": data.get("source", self.config.report_source),
            "report_date": data.get("report_date", ""),
            "frequency": data.get("frequency", self.config.report_frequency),
            "available": True,
            "metrics": data.get("metrics", {}),
        }
