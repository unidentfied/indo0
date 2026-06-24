"""
Unit tests for mock_simulation module.
Run with: pytest backend/app/tests/test_mock_simulation.py -v
"""
import pytest
from app import mock_simulation


def test_ward_list_has_entries():
    assert len(mock_simulation.NAIROBI_WARDS) >= 10


def test_categories_include_all_infra_types():
    expected = {"power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"}
    assert set(mock_simulation.CATEGORIES) == expected


def test_levels_supported():
    assert set(mock_simulation.LEVELS) == {"critical", "warning", "advisory"}


def test_data_sources_include_all_categories():
    for infra_type in mock_simulation.CATEGORIES:
        assert infra_type in mock_simulation._DATA_SOURCES
        assert len(mock_simulation._DATA_SOURCES[infra_type]) >= 1


def test_generate_infrastructure_status_power():
    status = mock_simulation.generate_infrastructure_status("power")
    assert isinstance(status, dict)
    assert "grid_stability" in status
    assert "current_load" in status


def test_generate_infrastructure_status_unknown_defaults():
    status = mock_simulation.generate_infrastructure_status("nonexistent")
    assert isinstance(status, dict)


def test_generate_alerts_returns_list():
    alerts = mock_simulation.generate_alerts(count=5)
    assert isinstance(alerts, list)
    assert len(alerts) == 5
    for alert in alerts:
        assert "id" in alert
        assert "level" in alert
        assert "title" in alert


def test_generate_stress_points_returns_geojson():
    points = mock_simulation.generate_stress_points(infra_type="power", max_points=3)
    assert "features" in points
    assert len(points["features"]) == 3


def test_start_simulation_returns_task():
    task = mock_simulation.start_simulation(
        params={"infrastructure_type": "power", "stress_factor": "peak"},
        infra_types=["power"],
    )
    assert "task_id" in task
    assert task["status"] == "queued"
