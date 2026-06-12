from fastapi import APIRouter
from typing import List
import random
import asyncio
from datetime import datetime

router = APIRouter()

@router.post("/run")
async def run_simulation(network: str = "power", stress_factor: str = "Population Increase (+15%)"):
    await asyncio.sleep(0.5)  # simulate ML inference
    impacts = [
        {"time": "00:00", "load": 40},
        {"time": "06:00", "load": 65},
        {"time": "12:00", "load": 92},
        {"time": "18:00", "load": 55},
        {"time": "23:59", "load": 30},
    ]
    return {
        "id": f"SIM-{random.randint(1000, 9999)}",
        "network": network,
        "stress_factor": stress_factor,
        "projected_impacts": impacts,
        "failure_risk": "high",
        "recommendation": "Reroute 12% of load to auxiliary substations within 2 hours.",
        "created_at": datetime.now().isoformat(),
    }

@router.get("/status")
def get_status():
    return {
        "active": True,
        "nodes_scanned": 14204,
        "latency_ms": 12,
        "simulation_time": "T+04:15:00",
        "progress": 0.68,
    }
