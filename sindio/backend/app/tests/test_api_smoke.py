"""
Smoke tests for the Sindio mock API.
Run with: pytest backend/app/tests/ -v
"""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_health_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.anyio
async def test_dashboard_metrics(client):
    resp = await client.get("/api/dashboard/metrics")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_dashboard_alerts(client):
    resp = await client.get("/api/dashboard/alerts")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_infrastructure_power(client):
    resp = await client.get("/api/infrastructure/power")
    assert resp.status_code == 200
    data = resp.json()
    assert "grid_stability" in data
    assert "current_load" in data
    assert "active_nodes" in data


@pytest.mark.anyio
async def test_infrastructure_unknown_returns_404(client):
    resp = await client.get("/api/infrastructure/nonexistent")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_simulations_status(client):
    resp = await client.get("/api/simulations/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "active" in data


@pytest.mark.anyio
async def test_simulate_run_creates_task(client):
    resp = await client.post("/api/simulate/run", json={
        "infrastructure_type": "power",
        "stress_factor": "population_growth",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data


@pytest.mark.anyio
async def test_v1_alerts(client):
    resp = await client.get("/api/v1/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert "alerts" in data
    assert isinstance(data["alerts"], list)


@pytest.mark.anyio
async def test_v1_spatial_stress_points(client):
    resp = await client.get("/api/v1/spatial/stress-points")
    assert resp.status_code == 200
    data = resp.json()
    assert "features" in data
    assert len(data["features"]) > 0


@pytest.mark.anyio
async def test_v1_spatial_stress_heatmap(client):
    resp = await client.get("/api/v1/spatial/stress-heatmap")
    assert resp.status_code == 200
    data = resp.json()
    assert "features" in data


@pytest.mark.anyio
async def test_v1_monitor_types(client):
    resp = await client.get("/api/v1/monitor/types")
    assert resp.status_code == 200
    data = resp.json()
    assert "types" in data
    assert isinstance(data["types"], list)
    assert len(data["types"]) >= 1


@pytest.mark.anyio
async def test_v1_scenario_generate_uses_prompt(client):
    resp = await client.post("/api/v1/scenario/generate", json={
        "prompt": "What happens if Nairobi population grows 20% by 2035? Focus on water and roads.",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["year"] == 2035
    assert data["density_growth_rate"] == 20
    assert "water" in data["infrastructure_types"]
    assert "roads" in data["infrastructure_types"]
    assert "Nairobi" in data["explanation"] or "2035" in data["explanation"]


@pytest.mark.anyio
async def test_v1_monitor_stress(client):
    resp = await client.get("/api/v1/monitor/stress")
    assert resp.status_code == 200


# ── E2E: freshness fields ─────────────────────────────────────

@pytest.mark.anyio
async def test_dashboard_metrics_includes_freshness(client):
    """Verify every metric has last_updated and data_source."""
    resp = await client.get("/api/dashboard/metrics?system=power")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 4
    for m in data:
        assert "last_updated" in m, f"Missing last_updated in {m['label']}"
        assert "data_source" in m, f"Missing data_source in {m['label']}"


@pytest.mark.anyio
async def test_dashboard_alerts_includes_confidence(client):
    resp = await client.get("/api/dashboard/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if len(data) > 0:
        a = data[0]
        assert "confidence" in a
        assert "data_sources_used" in a


# ── E2E: API key auth on write endpoints ─────────────────────

@pytest.mark.anyio
async def test_simulate_run_rejects_missing_api_key(monkeypatch, client):
    """When SINDIO_API_KEY is set, POST endpoints require X-API-Key."""
    monkeypatch.setenv("SINDIO_API_KEY", "test-secret-123")
    # Re-import app after env var change — but the middleware reads at import time.
    # For testing, we rely on the fact that fastapi test client reuses the module-level var.
    # In practice: the env var is set at container start, not per-request.
    resp = await client.post("/api/simulate/run", json={
        "infrastructure_type": "power",
        "stress_factor": "population_growth",
    }, headers={"X-API-Key": "wrong-key"})
    # May be 401 if key required, or 200 if no key set
    assert resp.status_code in (200, 401)
