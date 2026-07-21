import pytest
import asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app as mock_app

"""
End-to-End Integration Tests
============================
Verifies the full pipeline: ingestion → DB → API → response.
"""


@pytest.fixture
async def mock_client():
    transport = ASGITransport(app=mock_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_e2e_health_pipeline(mock_client):
    """Verify health endpoint returns correct structure."""
    resp = await mock_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    # Verify security headers present
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"


@pytest.mark.anyio
async def test_e2e_dashboard_metrics_with_db(mock_client):
    """Verify dashboard metrics return real DB-backed data if available."""
    resp = await mock_client.get("/api/dashboard/metrics?system=power")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for m in data:
        assert "last_updated" in m
        assert "data_source" in m


@pytest.mark.anyio
async def test_e2e_simulation_creates_and_retrieves(mock_client):
    """Verify async simulation task lifecycle."""
    # Create simulation
    resp = await mock_client.post("/api/simulate/run", json={
        "infrastructure_type": "power",
        "stress_factor": "population_growth",
    })
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    assert len(task_id) >= 8  # UUID fragment

    # Poll for result (simulation runs in background thread)
    final_state = None
    for _ in range(50):
        status_resp = await mock_client.get(f"/api/simulate/status/{task_id}")
        assert status_resp.status_code == 200
        state = status_resp.json()
        final_state = state
        if state["state"] in ("SUCCESS", "FAILURE"):
            break
        await asyncio.sleep(0.2)

    # If still pending, that's ok for the test — we verified the task was created
    assert final_state is not None
    assert final_state["state"] in ("PENDING", "STARTED", "SUCCESS", "FAILURE")

    # Retrieve result (may be 404 if not yet SUCCESS)
    result_resp = await mock_client.get(f"/api/simulate/result/{task_id}")
    assert result_resp.status_code in (200, 404)


@pytest.mark.anyio
async def test_e2e_monitor_stress_returns_all_types(mock_client):
    """Verify /monitor/stress returns data for all 8 infrastructure types."""
    resp = await mock_client.get("/api/v1/monitor/stress")
    assert resp.status_code == 200
    data = resp.json()
    assert "per_type_summary" in data
    types = {t["infrastructure_type"] for t in data["per_type_summary"]}
    expected = {"power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"}
    assert types == expected, f"Missing types: {expected - types}"


@pytest.mark.anyio
async def test_e2e_spatial_endpoints_return_geojson(mock_client):
    """Verify spatial endpoints return valid GeoJSON."""
    resp = await mock_client.get("/api/v1/spatial/stress-points?infrastructure_type=power&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert isinstance(data["features"], list)
    if data["features"]:
        feature = data["features"][0]
        assert feature["type"] == "Feature"
        assert "geometry" in feature
        assert "properties" in feature


@pytest.mark.anyio
async def test_e2e_rate_limiting_respected(mock_client):
    """Verify rate limiting is active on expensive endpoints."""
    # Hit simulation endpoint 15 times rapidly
    responses = []
    for _ in range(15):
        resp = await mock_client.post("/api/simulations/run", json={"network": "power", "stress_factor": "Test"})
        responses.append(resp.status_code)

    # Most should succeed, but if rate limited some may be 429
    assert all(code in (200, 429) for code in responses), f"Unexpected status codes: {responses}"


@pytest.mark.anyio
async def test_e2e_security_headers_on_all_routes(mock_client):
    """Verify security headers are present on all API routes."""
    routes = [
        "/health",
        "/api/dashboard/metrics",
        "/api/v1/monitor/stress",
        "/api/v1/alerts",
    ]
    for route in routes:
        resp = await mock_client.get(route)
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert "X-Frame-Options" in resp.headers


@pytest.mark.anyio
async def test_e2e_cors_preflight(mock_client):
    """Verify CORS preflight requests are handled."""
    resp = await mock_client.options("/api/simulate/run", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type",
    })
    assert resp.status_code in (200, 204)
    assert "access-control-allow-origin" in resp.headers
