"""
Unit tests for the unified monitor stress calculator.
Run with: cd backend/core && poetry run pytest tests/ -v
"""
import numpy as np
import pytest

from app.services.monitor.stress import calculate_stress


class TestPowerStress:
    """Power grid stress: voltage-based with line loading factor."""

    def test_normal_voltage_low_load(self):
        result = calculate_stress(
            infra_type="power",
            telemetry={"voltage_pu": np.array([0.98]), "load_mw": np.array([50.0])},
            config_capacity=200.0,
        )
        stress = result.get("stress", 0)
        assert 0 <= stress <= 50, f"Expected low stress, got {stress}"

    def test_low_voltage_high_load(self):
        result = calculate_stress(
            infra_type="power",
            telemetry={"voltage_pu": np.array([0.85]), "load_mw": np.array([180.0])},
            config_capacity=200.0,
        )
        stress = result.get("stress", 0)
        assert stress > 50, f"Expected high stress, got {stress}"

    def test_stress_bounded_0_100(self):
        for _ in range(20):
            v = np.random.uniform(0.5, 1.1)
            load = np.random.uniform(0, 250)
            result = calculate_stress(
                infra_type="power",
                telemetry={"voltage_pu": np.array([v]), "load_mw": np.array([load])},
                config_capacity=200.0,
            )
            assert 0 <= result.get("stress", 0) <= 100


class TestWaterStress:
    """Water network stress: pressure-based."""

    def test_normal_pressure(self):
        result = calculate_stress(
            infra_type="water",
            telemetry={"pressure_m": np.array([40.0])},
            config_capacity=200.0,
        )
        assert result.get("stress", 100) < 60

    def test_low_pressure(self):
        result = calculate_stress(
            infra_type="water",
            telemetry={"pressure_m": np.array([8.0])},
            config_capacity=200.0,
        )
        assert result.get("stress", 0) > 40

    def test_pressure_zero_max_stress(self):
        result = calculate_stress(
            infra_type="water",
            telemetry={"pressure_m": np.array([0.0])},
            config_capacity=200.0,
        )
        assert result.get("stress", 0) >= 90


class TestRoadStress:
    """Road network stress: density/speed-based."""

    def test_low_congestion(self):
        result = calculate_stress(
            infra_type="roads",
            telemetry={"vehicle_count": np.array([100.0]), "avg_speed_ms": np.array([12.0])},
            config_capacity=200.0,
        )
        assert result.get("stress", 100) < 50

    def test_high_congestion(self):
        result = calculate_stress(
            infra_type="roads",
            telemetry={"vehicle_count": np.array([500.0]), "avg_speed_ms": np.array([2.0])},
            config_capacity=200.0,
        )
        assert result.get("stress", 0) > 50


class TestHeuristicStress:
    """Heuristic stress for types without physics engines (solid_waste, sidewalks, etc.)."""

    def test_heuristic_stress_bounded(self):
        for infra_type in ["solid_waste", "sidewalks", "lrt", "sgr", "airports"]:
            result = calculate_stress(
                infra_type=infra_type,
                telemetry={"load": np.array([50.0])},
                config_capacity=100.0,
            )
            stress = result.get("stress", -1)
            assert 0 <= stress <= 100, f"{infra_type}: expected 0-100, got {stress}"

    def test_heuristic_returns_failure_mode(self):
        result = calculate_stress(
            infra_type="solid_waste",
            telemetry={"fill_level": np.array([95.0])},
            config_capacity=100.0,
        )
        fm = result.get("failure_mode", "")
        assert len(fm) > 0


class TestStressComponents:
    """Verify stress dict contains all expected fields."""

    def test_result_has_required_keys(self):
        result = calculate_stress(
            infra_type="power",
            telemetry={"voltage_pu": np.array([0.95]), "load_mw": np.array([80.0])},
            config_capacity=200.0,
        )
        for key in ["stress", "failure_mode", "time_to_breach_sec", "recommendation"]:
            assert key in result, f"Missing key: {key}"
