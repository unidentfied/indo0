"""
Sindio — Historical Baseline Comparison
=========================================

Compares current stress values against historical baselines.
Baselines are computed from:
  1. PostGIS stored classifications (if available)
  2. Cached parquet files from data fusion
  3. Rolling window averages computed on the fly
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

import numpy as np

from .registry import InfraConfig

logger = logging.getLogger("sindio.baseline")


class BaselineComparator:
    """Historical baseline comparison for one infrastructure type."""

    def __init__(self, config: InfraConfig, db_url: Optional[str] = None):
        self.config = config
        self.db_url = db_url or os.getenv(
            "DATABASE_URL",
            f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
            f"{os.getenv('DB_PASSWORD', '')}@"
            f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
            f"{os.getenv('DB_NAME', 'sindio')}",
        )
        self._baseline_cache: Dict[str, float] = {}

    def get_baseline(
        self, asset_id: str, infra_type: str, now: datetime
    ) -> float:
        """Get the historical baseline stress for an asset.

        Returns a float 0.0–1.0 representing the expected stress level
        based on historical data.
        """
        cache_key = f"{infra_type}:{asset_id}"
        if cache_key in self._baseline_cache:
            return self._baseline_cache[cache_key]

        # Try PostGIS first
        baseline = self._query_postgis_baseline(asset_id, infra_type)
        if baseline is not None:
            self._baseline_cache[cache_key] = baseline
            return baseline

        # Fallback: compute from date-based heuristic
        baseline = self._compute_heuristic_baseline(now, infra_type)
        self._baseline_cache[cache_key] = baseline
        return baseline

    def _query_postgis_baseline(
        self, asset_id: str, infra_type: str
    ) -> Optional[float]:
        """Query stored baseline from PostGIS stress_classifications table."""
        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(self.db_url)
            sql = text(
                """
                SELECT AVG(stress_ml) as avg_stress
                FROM stress_classifications
                WHERE asset_id = :asset_id
                  AND asset_type = :infra_type
                  AND updated_at >= NOW() - INTERVAL '30 days'
                """
            )
            with engine.connect() as conn:
                row = conn.execute(
                    sql, {"asset_id": asset_id, "infra_type": infra_type}
                ).fetchone()

            if row is None:
                return None
            val = row[0] if hasattr(row, "__getitem__") else getattr(row, "avg_stress", None)
            if val is not None:
                return float(val)
            return None

        except Exception:
            return None

    def _compute_heuristic_baseline(
        self, now: datetime, infra_type: str
    ) -> float:
        """Compute a heuristic baseline based on time-of-day and day-of-week.

        Different infrastructure types have different stress patterns:
          - Power: peaks at 6–9 AM and 6–9 PM
          - Water: peaks at 6–8 AM and 5–7 PM
          - Roads: peaks at 7–9 AM and 5–7 PM
          - Others: relatively flat with slight weekday increase
        """
        hour = now.hour
        weekday = now.weekday()  # 0=Mon, 6=Sun

        # Base stress per type
        base_stress = self.config.heuristic_base_stress

        # Hour-of-day factor
        hour_factor = self._hour_factor(hour, infra_type)

        # Day-of-week factor (weekdays higher)
        day_factor = 1.0 + (0.15 if weekday < 5 else -0.10)

        baseline = base_stress * hour_factor * day_factor
        return round(float(np.clip(baseline, 0.0, 1.0)), 4)

    def _hour_factor(self, hour: int, infra_type: str) -> float:
        """Return stress multiplier based on hour of day."""
        if infra_type == "power":
            # Dual peak: morning and evening
            if 6 <= hour <= 9:
                return 1.3
            elif 18 <= hour <= 21:
                return 1.25
            elif 0 <= hour <= 5:
                return 0.6
            else:
                return 1.0
        elif infra_type == "water":
            # Morning and evening peaks
            if 6 <= hour <= 8:
                return 1.2
            elif 17 <= hour <= 19:
                return 1.15
            elif 1 <= hour <= 5:
                return 0.5
            else:
                return 1.0
        elif infra_type == "roads":
            # Rush hour peaks
            if 7 <= hour <= 9:
                return 1.4
            elif 17 <= hour <= 19:
                return 1.35
            elif 0 <= hour <= 5:
                return 0.4
            else:
                return 0.9
        elif infra_type in ("lrt", "sgr"):
            # Transit peaks
            if 7 <= hour <= 9:
                return 1.3
            elif 17 <= hour <= 19:
                return 1.2
            elif 0 <= hour <= 5:
                return 0.3
            else:
                return 0.8
        elif infra_type == "airports":
            # Flight peaks
            if 6 <= hour <= 10:
                return 1.2
            elif 15 <= hour <= 18:
                return 1.15
            elif 0 <= hour <= 5:
                return 0.5
            else:
                return 1.0
        else:
            # Flat with slight midday increase
            if 10 <= hour <= 16:
                return 1.1
            elif 0 <= hour <= 5:
                return 0.7
            else:
                return 1.0

    def compute_deviation(self, current: float, baseline: float) -> float:
        """Compute deviation from baseline as a ratio.

        Returns:
            > 1.0: current stress is above baseline
            < 1.0: current stress is below baseline
            = 1.0: current matches baseline
        """
        if baseline == 0:
            return current
        return current / baseline

    def is_anomalous(
        self, current: float, baseline: float, threshold: float = 1.5
    ) -> bool:
        """Check if current stress is anomalously high compared to baseline."""
        return self.compute_deviation(current, baseline) > threshold
