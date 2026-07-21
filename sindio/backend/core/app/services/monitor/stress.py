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


class StressResult(dict):
    """Result object for stress calculation that functions as a dictionary
    (with keys 'stress', 'failure_mode', 'time_to_breach_sec', 'recommendation')
    and also supports numeric/float operations seamlessly."""

    def __init__(self, stress: float, failure_mode: str = "", time_to_breach_sec: Optional[float] = None, recommendation: Optional[str] = None):
        super().__init__({
            "stress": float(stress),
            "failure_mode": failure_mode or "",
            "time_to_breach_sec": time_to_breach_sec,
            "recommendation": recommendation or "",
        })

    @property
    def stress_val(self) -> float:
        return float(self.get("stress", 0.0))

    def __float__(self) -> float:
        return self.stress_val

    def __int__(self) -> int:
        return int(self.stress_val)

    def __round__(self, n: int = 0) -> float:
        return round(self.stress_val, n)

    def _val(self, other: Any) -> float:
        if isinstance(other, dict) and "stress" in other:
            return float(other["stress"])
        return float(other)

    def __lt__(self, other: Any) -> bool:
        return self.stress_val < self._val(other)

    def __le__(self, other: Any) -> bool:
        return self.stress_val <= self._val(other)

    def __gt__(self, other: Any) -> bool:
        return self.stress_val > self._val(other)

    def __ge__(self, other: Any) -> bool:
        return self.stress_val >= self._val(other)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, dict) and not isinstance(other, StressResult):
            return super().__eq__(other)
        try:
            return self.stress_val == self._val(other)
        except (ValueError, TypeError):
            return super().__eq__(other)

    def __add__(self, other: Any) -> float:
        return self.stress_val + self._val(other)

    def __radd__(self, other: Any) -> float:
        return self._val(other) + self.stress_val

    def __sub__(self, other: Any) -> float:
        return self.stress_val - self._val(other)

    def __rsub__(self, other: Any) -> float:
        return self._val(other) - self.stress_val

    def __mul__(self, other: Any) -> float:
        return self.stress_val * self._val(other)

    def __rmul__(self, other: Any) -> float:
        return self._val(other) * self.stress_val

    def __truediv__(self, other: Any) -> float:
        return self.stress_val / self._val(other)

    def __rtruediv__(self, other: Any) -> float:
        return self._val(other) / self.stress_val


class StressCalculator:
    """Unified stress calculator for one infrastructure type."""

    def __init__(self, config: InfraConfig = None):
        self.config = config

    def compute_stress(self, *args) -> StressResult:
        """Compute stress for a telemetry point.

        Supports two call signatures:
        1. compute_stress(config: InfraConfig, telemetry: Dict[str, Any], capacity: float)
        2. compute_stress(telemetry: Dict[str, Any], current_value: float, capacity: float)  # when instance was initialized with a config

        Returns a StressResult (dict subclass with float behavior) containing stress (0-100),
        failure_mode, time_to_breach_sec, recommendation.
        """
        # Resolve arguments based on their types
        if len(args) != 3:
            raise ValueError("compute_stress expects exactly three arguments")
        first, second, third = args
        # Signature 1: first is InfraConfig
        if isinstance(first, InfraConfig):
            cfg = first
            telemetry = second
            capacity = third
            current_value = 0.0
            if isinstance(telemetry, dict) and "value" in telemetry:
                try:
                    val = telemetry["value"]
                    current_value = float(val[0]) if hasattr(val, "__getitem__") and not isinstance(val, (str, bytes)) else float(val)
                except Exception:
                    current_value = 0.0
        else:
            # Signature 2: instance already has config
            cfg = self.config
            if cfg is None:
                raise ValueError("InfraConfig must be provided either via instance or as first argument")
            telemetry = first
            current_value = second
            capacity = third

        self.config = cfg
        engine = cfg.physics_engine
        if engine == PhysicsEngine.POWER:
            stress = self._compute_power_stress(telemetry, current_value, capacity)
        elif engine == PhysicsEngine.WATER:
            stress = self._compute_water_stress(telemetry, current_value, capacity)
        elif engine == PhysicsEngine.ROAD:
            stress = self._compute_road_stress(telemetry, current_value, capacity)
        else:
            stress = self._compute_heuristic_stress(telemetry, current_value, capacity)

        scaled_stress = float(stress * 100.0)

        # Determine failure_mode
        failure_mode = ""
        if isinstance(telemetry, dict):
            fill = telemetry.get("fill_level") or telemetry.get("load") or telemetry.get("stress_level")
            if fill is not None:
                try:
                    fill_val = float(fill[0]) if hasattr(fill, "__getitem__") and not isinstance(fill, (str, bytes)) else float(fill)
                    if fill_val >= 80.0:
                        failure_mode = "overflow"
                    elif fill_val >= 50.0:
                        failure_mode = "high_load"
                except Exception:
                    pass
        if not failure_mode and scaled_stress >= 80.0:
            failure_mode = "critical_stress"
        elif not failure_mode and scaled_stress >= 50.0:
            failure_mode = "warning_stress"

        return StressResult(
            stress=scaled_stress,
            failure_mode=failure_mode,
            time_to_breach_sec=None,
            recommendation=None,
        )

    def compute_stress_batch(
        self,
        data_points: List[Dict[str, Any]],
    ) -> List[float]:
        """Compute stress scores for a batch of data points. Returns list of floats in [0, 100]."""
        return [
            float(self.compute_stress(
                dp,
                dp.get("value", 0.0),
                dp.get("capacity", self.config.default_capacity),
            ))
            for dp in data_points
        ]

    # ── Physics engine: Power ──────────────────────────────────────

    def _compute_power_stress(
        self, dp: Dict[str, Any], value: float, capacity: float
    ) -> float:
        """Power stress: based on line loading and voltage.

        stress = max(line_loading_pct / 100, 1.0 - voltage_pu)
        """
        def _get_num(k: str, default: float) -> float:
            v = dp.get(k, default)
            if v is None:
                return default
            try:
                return float(v[0]) if hasattr(v, "__getitem__") and not isinstance(v, (str, bytes)) else float(v)
            except Exception:
                return default

        line_loading = _get_num("line_loading_pct", 0.0)
        voltage_pu = _get_num("voltage_pu", 1.0)
        load_mw = _get_num("load_mw", value)

        current_val = load_mw if load_mw > 0 else value
        if current_val > 0 and capacity > 0:
            load_ratio = current_val / capacity
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
        def _get_num(k: str, default: float) -> float:
            v = dp.get(k, default)
            if v is None:
                return default
            try:
                return float(v[0]) if hasattr(v, "__getitem__") and not isinstance(v, (str, bytes)) else float(v)
            except Exception:
                return default

        pressure_m = _get_num("pressure_m", value if value > 0 else 40.0)
        nominal_pressure = 40.0

        if pressure_m <= 0:
            return 1.0

        stress = 1.0 - (pressure_m / nominal_pressure)

        failure_val = self.config.thresholds.failure_value if self.config and self.config.thresholds else 10.0
        if pressure_m < failure_val:
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
        def _get_num(k: str, default: float) -> float:
            v = dp.get(k, default)
            if v is None:
                return default
            try:
                return float(v[0]) if hasattr(v, "__getitem__") and not isinstance(v, (str, bytes)) else float(v)
            except Exception:
                return default

        density = _get_num("density_veh_km", 0.0)
        jam_density = _get_num("jam_density_veh_km", 150.0)

        speed = 0.0
        if "speed_kmh" in dp:
            speed = _get_num("speed_kmh", 0.0)
        elif "avg_speed_ms" in dp:
            speed = _get_num("avg_speed_ms", 0.0) * 3.6  # m/s to km/h

        freeflow_speed = _get_num("freeflow_speed_kmh", 50.0)
        vehicle_count = _get_num("vehicle_count", value)

        if jam_density > 0 and density > 0:
            stress_density = density / jam_density
        else:
            stress_density = 0.0

        if freeflow_speed > 0 and speed > 0:
            stress_speed = max(0.0, 1.0 - (speed / freeflow_speed))
        else:
            stress_speed = 0.0

        stress = max(stress_density, stress_speed)

        if vehicle_count > 0 and capacity > 0:
            load_ratio = vehicle_count / capacity
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

        Returns a dictionary containing average stress, mean stress (same as avg),
        percentile values, maximum stress, counts of critical/warning/healthy nodes,
        and the fraction of stressed (critical) nodes.
        """
        if not stresses:
            return {
                "avg": 0.0,
                "mean_stress": 0.0,
                "p50": 0.0,
                "p90": 0.0,
                "p95": 0.0,
                "p99": 0.0,
                "max_stress": 0.0,
                "critical_count": 0,
                "warning_count": 0,
                "healthy_count": 0,
                "stressed_fraction": 0.0,
            }

        import numpy as np

        arr = np.array(stresses)
        t = self.config.thresholds

        avg = round(float(np.mean(arr)), 4)
        p50 = round(float(np.percentile(arr, 50)), 4)
        p90 = round(float(np.percentile(arr, 90)), 4)
        p95 = round(float(np.percentile(arr, 95)), 4)
        p99 = round(float(np.percentile(arr, 99)), 4)
        max_stress = round(float(np.max(arr)), 4)

        critical_count = int(np.sum(arr >= t.critical))
        warning_count = int(np.sum((arr >= t.warning) & (arr < t.critical)))
        healthy_count = int(np.sum(arr < t.warning))

        stressed_fraction = round(critical_count / len(arr) if len(arr) > 0 else 0.0, 4)

        return {
            "avg": avg,
            "mean_stress": avg,
            "p50": p50,
            "p90": p90,
            "p95": p95,
            "p99": p99,
            "max_stress": max_stress,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "healthy_count": healthy_count,
            "stressed_fraction": stressed_fraction,
        }
