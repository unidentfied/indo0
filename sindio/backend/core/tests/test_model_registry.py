import pytest

from app.services.model_registry import ModelRegistry


def test_model_registry_init():
    registry = ModelRegistry()
    assert registry.models == {}
    assert registry.model_path is not None


@pytest.mark.asyncio
async def test_model_registry_loads_unavailable():
    registry = ModelRegistry()
    registry.model_path = "/nonexistent/path"
    await registry.load_models()
    for name in ("urban_stress", "mobility_forecast", "water_demand"):
        assert name in registry.models
        assert registry.models[name]["status"] == "unavailable"


def test_model_registry_get_missing():
    registry = ModelRegistry()
    assert registry.get_model("nonexistent") is None


@pytest.mark.asyncio
async def test_model_registry_unload():
    registry = ModelRegistry()
    registry.models["test"] = {"status": "loaded"}
    await registry.unload_models()
    assert registry.models == {}
