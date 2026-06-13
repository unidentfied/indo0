import os

import pytest
from fastapi.testclient import TestClient

os.environ["DB_PASSWORD"] = "test123"
os.environ["DB_HOST"] = "localhost"
os.environ["DB_PORT"] = "5432"
os.environ["DB_NAME"] = "sindio_test"
os.environ["DB_USER"] = "sindio_user"

import app.main  # noqa: E402

client = TestClient(app.main.app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_health_ready():
    response = client.get("/health/ready")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "dependencies" in data


def test_metrics_endpoint():
    response = client.get("/metrics")
    assert response.status_code == 200


def test_simulations_status():
    response = client.get("/api/simulations/status")
    assert response.status_code == 200
    data = response.json()
    assert data["active"] is True
    assert "nodes_scanned" in data


def test_simulations_run():
    response = client.post("/api/simulations/run", json={"network": "power", "stress_factor": "Test"})
    assert response.status_code == 200
    data = response.json()
    assert data["network"] == "power"
    assert "id" in data
    assert "failure_risk" in data


def test_simulations_run_invalid_network():
    response = client.post("/api/simulations/run", json={"network": "nonexistent", "stress_factor": "Test"})
    assert response.status_code == 400


def test_infrastructure_get_all():
    response = client.get("/api/infrastructure")
    assert response.status_code == 200


def test_infrastructure_get_by_system():
    response = client.get("/api/infrastructure/power")
    assert response.status_code == 200


def test_infrastructure_invalid_system():
    response = client.get("/api/infrastructure/nonexistent")
    assert response.status_code == 200
    data = response.json()
    assert "error" in data


def test_dashboard_metrics():
    response = client.get("/api/dashboard/metrics")
    assert response.status_code == 200


def test_dashboard_alerts():
    response = client.get("/api/dashboard/alerts")
    assert response.status_code == 200


def test_schedule_next_updates():
    response = client.get("/api/v1/next_updates")
    assert response.status_code == 200


def test_monitor_stress():
    response = client.get("/api/v1/monitor/stress?min_stress=0.3")
    assert response.status_code == 200
    data = response.json()
    assert "stressed_assets" in data


def test_monitor_types():
    response = client.get("/api/v1/monitor/types")
    assert response.status_code == 200
    data = response.json()
    assert "types" in data
    assert len(data["types"]) >= 8


def test_monitor_classification():
    response = client.get("/api/v1/monitor/classification")
    assert response.status_code == 200
    data = response.json()
    for summary in data["summaries"]:
        dist = summary["classification_distribution"]
        total = sum(v["percentage"] for v in dist.values())
        assert abs(total - 100.0) < 1.0


def test_request_id_header():
    response = client.get("/health", headers={"X-Request-ID": "test-id-123"})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "test-id-123"
