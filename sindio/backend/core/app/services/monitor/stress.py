"""
Sindio — Unified Stress Calculator
====================================

Dispatches to the correct physics engine based on config.
For types with physics sims (power, water, roads), uses the real solver.
For heuristic types, uses configurable base_stress + variance.

All engines produce the same output: a stress score 0.0–1.0.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .registry import InfraConfig, PhysicsEngine

logger = logging.getLogger("sindio.stress")


class StressCalculator:
    """Unified stress calculator for one infrastructure type."""

    def __init__(self, config: InfraConfig):
        self.config = config

    def compute_stress(
        self,
        data_point: Dict[str, Any],
        current_value: float,
        capacity: float,
    ) -> float:
        """Compute stress score (0.0–1.0) for one data point.

        Dispatches to the appropriate engine based on config.physics_engine.
        """
        engine = self.config.physics_engine

        if engine == PhysicsEngine.POWER:
            return self._compute_power_stress(data_point, current_value, capacity)
        elif engine == PhysicsEngine.WATER:
            return self._compute_water_stress(data_point, current_value, capacity)
        elif engine == PhysicsEngine.ROAD:
            return self._compute_road_stress(data_point, current_value, capacity)
        else:
            return self._compute_heuristic_stress(data_point, current_value, capacity)

    def compute_stress_batch(
        self,
        data_points: List[Dict[str, Any]],
    ) -> List[float]:
        """Compute stress scores for a batch of data points."""
        return [
            self.compute_stress(
                dp,
                dp.get("value", 0.0),
                dp.get("capacity", self.config.default_capacity),
            )
            for dp in data_points
        ]

    # ── Physics engine: Power ──────────────────────────────────────

    def _compute_power_stress(
        self, dp: Dict[str, Any], value: float, capacity: float
    ) -> float:
        """Power stress: based on line loading and voltage.

        stress = max(line_loading_pct / 100, 1.0 - voltage_pu)
        """
        line_loading = dp.get("line_loading_pct", 0.0)
        voltage_pu = dp.get("voltage_pu", 1.0)

        # If we have raw MW value, compute loading ratio
        if value > 0 and capacity > 0:
            load_ratio = value / capacity
        else:
            load_ratio = line_loading / 100.0

        voltage_drop = max(0.0, 1.0 - voltage_pu)
        stress = max(load_ratio, voltage_drop * 2)

        return float(min(stress, 1.0))

    # ── Physics engine: Water ──────────────────────────────────────

    def _compute_water_stress(
        self, dp: Dict[str, Any], value: float, capacity: float
    ) -> float:
        """Water stress: based on pressure.

        stress = 1.0 - (pressure_m / nominal_pressure)
        Nominal pressure ≈ 40m (4 bar). Below 10m = failure.
        """
        pressure_m = dp.get("pressure_m", value if value > 0 else 30.0)
        nominal_pressure = 40.0

        if pressure_m <= 0:
            return 1.0

        # Invert: low pressure = high stress
        stress = 1.0 - (pressure_m / nominal_pressure)

        # If pressure is below failure threshold, max stress
        if pressure_m < self.config.thresholds.failure_value:
            return 1.0

        return float(max(0.0, min(stress, 1.0)))

    # ── Physics engine: Road ───────────────────────────────────────

    def _compute_road_stress(
        self, dp: Dict[str, Any], value: float, capacity: float
    ) -> float:
        """Road stress: based on density and speed.

        stress = density / jam_density
        Or from speed: stress = 1.0 - (speed / freeflow_speed)
        """
        density = dp.get("density_veh_km", 0.0)
        jam_density = dp.get("jam_density_veh_km", 150.0)
        speed = dp.get("speed_kmh", 0.0)
        freeflow_speed = dp.get("freeflow_speed_kmh", 50.0)

        if jam_density > 0 and density > 0:
            stress_density = density / jam_density
        else:
            stress_density = 0.0

        if freeflow_speed > 0 and speed >= 0:
            stress_speed = 1.0 - (speed / freeflow_speed)
        else:
            stress_speed = 0.0

        # Use the higher of density-based and speed-based stress
        stress = max(stress_density, stress_speed)

        # If we have raw vehicle count, also consider capacity ratio
        if value > 0 and capacity > 0:
            load_ratio = value / capacity
            stress = max(stress, load_ratio * 0.8)

        return float(max(0.0, min(stress, 1.0)))

    # ── Heuristic engine ───────────────────────────────────────────

    def _compute_heuristic_stress(
        self, dp: Dict[str, Any], value: float, capacity: float
    ) -> float:
        """Heuristic stress: based on value/capacity ratio with config params.

        stress = (value / capacity) * scaling_factor
        Clamped to [0, 1].
        """
        if capacity > 0 and value >= 0:
            ratio = value / capacity
        else:
            ratio = self.config.heuristic_base_stress

        # Scale by config base stress
        stress = ratio * (self.config.heuristic_base_stress / 0.5)

        # Add variance if fill_level or similar metric is present
        fill_level = dp.get("fill_level", dp.get("stress_level", None))
        if fill_level is not None:
            stress = float(fill_level)

        return float(max(0.0, min(stress, 1.0)))

    # ── Network-level stress ───────────────────────────────────────

    def compute_network_stress(self, stresses: List[float]) -> Dict[str, float]:
        """Compute aggregate network-level stress metrics.

        Returns:
            Dict with avg, p50, p90, p95, p99, max, critical_count
        """
        if not stresses:
            return {
                "avg": 0.0, "p50": 0.0, "p90": 0.0,
                "p95": 0.0, "p99": 0.0, "max": 0.0,
                "critical_count": 0,
            }

        import numpy as np

        arr = np.array(stresses)
        t = self.config.thresholds

        return {
            "avg": round(float(np.mean(arr)), 4),
            "p50": round(float(np.percentile(arr, 50)), 4),
            "p90": round(float(np.percentile(arr, 90)), 4),
            "p95": round(float(np.percentile(arr, 95)), 4),
            "p99": round(float(np.percentile(arr, 99)), 4),
            "max": round(float(np.max(arr)), 4),
            "critical_count": int(np.sum(arr >= t.critical)),
            "warning_count": int(np.sum((arr >= t.warning) & (arr < t.critical))),
            "healthy_count": int(np.sum(arr < t.warning)),
        }
