"""Sindio — Locust Load Testing Configuration
Runs API load tests against the mock API or ML Core.

Usage:
  cd tests/load && locust -f locustfile.py --host http://localhost:8080
  # Open http://localhost:8089 to configure and run
"""
from __future__ import annotations

import random
import time

from locust import HttpUser, between, task


class SindioUser(HttpUser):
    """Simulates a typical dashboard user interacting with Sindio APIs."""

    wait_time = between(1, 5)  # Think time between requests
    weight = 1

    @task(10)
    def health_check(self) -> None:
        self.client.get("/health")

    @task(8)
    def dashboard_metrics(self) -> None:
        system = random.choice(["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"])
        self.client.get(f"/api/dashboard/metrics?system={system}")

    @task(7)
    def dashboard_alerts(self) -> None:
        self.client.get("/api/dashboard/alerts?limit=5")

    @task(5)
    def infrastructure_status(self) -> None:
        system = random.choice(["power", "water", "roads"])
        self.client.get(f"/api/infrastructure/{system}")

    @task(4)
    def simulation_status(self) -> None:
        self.client.get("/api/simulations/status")

    @task(3)
    def run_simulation(self) -> None:
        network = random.choice(["power", "water", "roads"])
        self.client.post(f"/api/simulations/run?network={network}")

    @task(3)
    def monitor_stress(self) -> None:
        self.client.get("/api/v1/monitor/stress")

    @task(2)
    def monitor_types(self) -> None:
        self.client.get("/api/v1/monitor/types")

    @task(1)
    def spatial_stress_points(self) -> None:
        infra = random.choice(["power", "water", "roads"])
        self.client.get(f"/api/v1/spatial/stress-points?infrastructure_type={infra}&limit=60")


class SindioMonitorUser(HttpUser):
    """Simulates a monitoring/ops user polling the API frequently."""

    wait_time = between(0.5, 2)
    weight = 2

    @task(10)
    def health_check(self) -> None:
        self.client.get("/health")

    @task(5)
    def ready_check(self) -> None:
        self.client.get("/health/ready")

    @task(5)
    def metrics_endpoint(self) -> None:
        self.client.get("/metrics")

    @task(3)
    def monitor_stress(self) -> None:
        self.client.get("/api/v1/monitor/stress")


class SindioSimUser(HttpUser):
    """Simulates a heavy simulation user."""

    wait_time = between(5, 15)
    weight = 1

    @task(5)
    def run_simulation(self) -> None:
        network = random.choice(["power", "water", "roads"])
        self.client.post(f"/api/simulations/run?network={network}")

    @task(3)
    def monitor_classification(self) -> None:
        self.client.get("/api/v1/monitor/classification")

    @task(2)
    def spatial_heatmap(self) -> None:
        self.client.get("/api/v1/spatial/stress-heatmap?bbox=36.65,-1.43,37.10,-0.98&infrastructure_type=power")
