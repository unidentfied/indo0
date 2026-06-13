import pytest
import numpy as np

from app.services.temporal_spacing import (
    compute_interval,
    schedule_batch,
    SpacingResult,
    AssetSchedule,
    BASE_MINIMUM_DAYS,
    ABSOLUTE_FLOOR_DAYS,
)


class TestComputeInterval:
    def test_returns_spacing_result(self):
        result = compute_interval("power", stress=0.5)
        assert isinstance(result, SpacingResult)
        assert result.infrastructure_type == "power"
        assert result.final_interval_days >= ABSOLUTE_FLOOR_DAYS

    def test_all_types_return_valid(self):
        for infra_type in BASE_MINIMUM_DAYS:
            result = compute_interval(infra_type, stress=0.5)
            assert result.final_interval_days >= ABSOLUTE_FLOOR_DAYS

    def test_high_stress_reduces_interval(self):
        low = compute_interval("water", stress=0.2)
        high = compute_interval("water", stress=0.9)
        assert high.final_interval_days <= low.final_interval_days

    def test_density_driven_classification(self):
        result = compute_interval("power", stress=0.6, density_rho=0.8, classification="density_driven_only")
        assert isinstance(result, SpacingResult)

    def test_recurring_classification(self):
        result = compute_interval("water", stress=0.6, density_rho=0.2, classification="recurring_only")
        assert isinstance(result, SpacingResult)

    def test_reasoning_present(self):
        result = compute_interval("roads", stress=0.7)
        assert len(result.reasoning) > 0

    def test_deterministic_with_seed(self):
        r1 = compute_interval("power", stress=0.5, random_seed=42)
        r2 = compute_interval("power", stress=0.5, random_seed=42)
        assert r1.final_interval_days == r2.final_interval_days


class TestScheduleBatch:
    def test_returns_list_of_asset_schedules(self):
        assets = [
            {"asset_id": "PWR-001", "infrastructure_type": "power", "stress": 0.5},
            {"asset_id": "WTR-001", "infrastructure_type": "water", "stress": 0.6},
        ]
        schedules = schedule_batch(assets)
        assert len(schedules) == 2
        assert all(isinstance(s, AssetSchedule) for s in schedules)
        assert schedules[0].asset_id == "PWR-001"

    def test_empty_assets_returns_empty(self):
        assert schedule_batch([]) == []

    def test_respects_infra_type(self):
        assets = [{"asset_id": "RD-001", "infrastructure_type": "roads", "stress": 0.4}]
        schedules = schedule_batch(assets)
        assert schedules[0].infrastructure_type == "roads"
