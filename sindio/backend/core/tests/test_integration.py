import pytest
from fastapi.testclient import TestClient
from app.main import app
import os

os.environ["JWT_SECRET"] = "testsecret"
os.environ["DB_PASSWORD"] = "testpassword"

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200

def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
