import pytest
import numpy as np
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.monitor.registry import (
    InfraConfig, InfraThresholds, InfraSchedule, InfraActions,
    InfraDataSource, PhysicsEngine, get_config,
)
from app.services.monitor.monitor import (
    InfrastructureMonitor, AssetState, MonitorResult, get_all_stressed_assets,
)
from app.services.monitor.stress import StressCalculator
from app.services.monitor.reports import ReportIntegrator


class TestAssetState:
    def test_default_values(self):
        asset = AssetState(asset_id="TEST-001", infrastructure_type="power")
        assert asset.asset_id == "TEST-001"
        assert asset.stress == 0.0
        assert asset.is_mock is False

    def test_full_construction(self):
        asset = AssetState(
            asset_id="PWR-042",
            infrastructure_type="power",
            ward="Central",
            lat=-1.29,
            lon=36.82,
            current_value=85.0,
            capacity=100.0,
            stress=0.85,
            baseline_stress=0.60,
            baseline_deviation=0.25,
            data_source="scada",
            is_mock=False,
            failure_mode="voltage_drop",
            time_to_breach_hours=2.5,
            recommendation="Reroute load",
            confidence=0.92,
        )
        assert asset.stress == 0.85
        assert asset.failure_mode == "voltage_drop"


class TestMonitorResult:
    def test_default_factory(self):
        result = MonitorResult(
            infrastructure_type="power",
            display_name="Power Grid",
            run_timestamp="2024-01-01T00:00:00",
            total_assets=100,
            stressed_assets=20,
            critical_assets=5,
            warning_assets=15,
            healthy_assets=80,
            mock_data_ratio=0.3,
            avg_stress=0.45,
            avg_confidence=0.78,
            avg_baseline_deviation=0.12,
            report_alignment_pct=92.0,
        )
        assert result.assets == []
        assert result.total_assets == 100


class TestInfrastructureMonitor:
    def test_init_with_valid_type(self):
        monitor = InfrastructureMonitor("power")
        assert monitor.infra_type == "power"

    def test_init_with_invalid_type_raises(self):
        with pytest.raises(KeyError):
            InfrastructureMonitor("nonexistent")

    def test_run_returns_monitor_result(self):
        monitor = InfrastructureMonitor("water")
        result = monitor.run(force_mock=True)
        assert isinstance(result, MonitorResult)
        assert result.infrastructure_type == "water"
        assert result.total_assets > 0
        assert len(result.assets) > 0

    def test_run_with_ward_filter(self):
        monitor = InfrastructureMonitor("roads")
        result = monitor.run(ward="Central", force_mock=True)
        assert isinstance(result, MonitorResult)

    def test_run_include_healthy(self):
        monitor = InfrastructureMonitor("power")
        result = monitor.run(force_mock=True, include_healthy=True)
        assert result.healthy_assets >= 0

    def test_all_eight_types_work(self):
        for infra_name in ["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"]:
            monitor = InfrastructureMonitor(infra_name)
            result = monitor.run(force_mock=True)
            assert result.infrastructure_type == infra_name
            assert len(result.assets) > 0


class TestGetAllStressedAssets:
    def test_returns_dict_with_expected_keys(self):
        result = get_all_stressed_assets(force_mock=True, min_stress=0.0)
        assert isinstance(result, dict)
        assert "summary" in result
        assert "stressed_assets" in result
        assert "per_type_summary" in result

    def test_ward_filter(self):
        result = get_all_stressed_assets(ward="Kibera", force_mock=True, min_stress=0.0)
        assert isinstance(result, dict)

    def test_min_stress_filter(self):
        result = get_all_stressed_assets(force_mock=True, min_stress=0.5)
        assert isinstance(result, dict)


class TestStressCalculator:
    def test_power_stress_range(self):
        calc = StressCalculator(get_config("power"))
        stress = calc.compute_stress({"voltage_pu": 0.95, "load_mw": 50}, 50, 200)
        assert 0.0 <= stress <= 100.0

    def test_water_stress_range(self):
        calc = StressCalculator(get_config("water"))
        stress = calc.compute_stress({"pressure_m": 30}, 30, 200)
        assert 0.0 <= stress <= 100.0

    def test_road_stress_range(self):
        calc = StressCalculator(get_config("roads"))
        stress = calc.compute_stress({"vehicle_count": 150, "avg_speed_ms": 10}, 150, 200)
        assert 0.0 <= stress <= 100.0

    def test_heuristic_stress_range(self):
        calc = StressCalculator(get_config("sidewalks"))
        stress = calc.compute_stress({"pedestrian_count": 80}, 80, 200)
        assert 0.0 <= stress <= 100.0

    def test_compute_stress_batch(self):
        calc = StressCalculator(get_config("power"))
        data_points = [
            {"voltage_pu": 0.95, "load_mw": 50, "value": 50, "capacity": 200},
            {"voltage_pu": 0.85, "load_mw": 180, "value": 180, "capacity": 200},
        ]
        stresses = calc.compute_stress_batch(data_points)
        assert len(stresses) == 2
        assert all(0.0 <= s <= 100.0 for s in stresses)

    def test_compute_network_stress(self):
        calc = StressCalculator(get_config("water"))
        result = calc.compute_network_stress([10.0, 30.0, 50.0, 70.0])
        assert "mean_stress" in result
        assert "max_stress" in result
        assert "stressed_fraction" in result


class TestReportIntegrator:
    def test_check_alignment(self):
        integrator = ReportIntegrator(get_config("power"))
        assets = [AssetState(asset_id="PWR-001", infrastructure_type="power", stress=0.5)]
        result = integrator.check_alignment(assets, datetime.now(timezone.utc))
        assert isinstance(result, dict)
        assert "aligned_assets" in result
        assert "total_assets" in result

    def test_get_report_summary(self):
        integrator = ReportIntegrator(get_config("water"))
        summary = integrator.get_report_summary(datetime.now(timezone.utc))
        assert isinstance(summary, dict)
        assert "report_source" in summary
        assert summary["report_source"] == "Nairobi Water & Sewerage Company Report"
