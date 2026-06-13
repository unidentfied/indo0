import pytest
from unittest.mock import patch

from app.services.monitor import get_all_stressed_assets, get_all_configs, get_config
from app.services.monitor.registry import INFRA_REGISTRY


def test_registry_has_eight_types():
    assert len(INFRA_REGISTRY) >= 8
    for name in ("power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"):
        assert name in INFRA_REGISTRY


def test_get_config_valid():
    cfg = get_config("power")
    assert cfg.name == "power"
    assert cfg.display_name == "Power Grid"


def test_get_config_invalid():
    with pytest.raises(KeyError):
        get_config("nonexistent")


def test_get_all_configs():
    configs = get_all_configs()
    assert len(configs) == len(INFRA_REGISTRY)


@patch("app.services.monitor.monitor.InfrastructureMonitor.run")
def test_get_all_stressed_assets_calls_monitor(mock_run):
    from unittest.mock import MagicMock
    mock_result = MagicMock()
    mock_result.summary = {"total": 1}
    mock_result.per_type_summary = []
    mock_result.stressed_assets = []
    mock_result.timestamp = "2024-01-01T00:00:00"
    mock_run.return_value = mock_result

    result = get_all_stressed_assets(ward=None, force_mock=True, min_stress=0.0)
    assert "summary" in result
    assert "stressed_assets" in result
