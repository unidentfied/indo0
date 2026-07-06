"""Simulation compat router — makes Core simulation endpoints match Mock API contract.

The frontend expects async task semantics (task_id + polling) that the Mock API
provides via Redis/Celery. The Core runs simulations synchronously. This router
bridges the gap by generating synthetic task IDs and storing results in memory.
"""
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.routers.simulations import run_simulation, SimulationRequest

router = APIRouter()

# In-memory result store for demo compat (no TTL — grows unbounded in long-running prod)
_RESULTS: Dict[str, Any] = {}


@router.post("/run")
async def simulate_run_compat(payload: dict):
    """Accept the same body as Mock API /v1/simulate/run and return a task envelope."""
    network = payload.get("infrastructure_type", "power")
    stress_factor = payload.get("stress_factor", "Population Increase (+15%)")
    result = await run_simulation(
        SimulationRequest(network=network, stress_factor=stress_factor), None
    )
    task_id = f"SIM-{hash(result.id + result.created_at) % 9000 + 1000:04d}"
    _RESULTS[task_id] = result.model_dump() if hasattr(result, "model_dump") else result.dict()
    return {
        "task_id": task_id,
        "status": "queued",
        "message": f"Simulation {task_id} queued",
    }


@router.get("/status/{task_id}")
async def simulate_status_compat(task_id: str):
    """Return completed status for a synthetic task_id."""
    result = _RESULTS.get(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "task_id": task_id,
        "status": "completed",
        "progress": 1.0,
        "result": result,
        "created_at": now,
        "updated_at": now,
    }
