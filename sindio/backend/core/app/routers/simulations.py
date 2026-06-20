from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import optional_auth

from app.services.monitor import InfrastructureMonitor, get_all_configs, get_config

router = APIRouter()


class SimulationRequest(BaseModel):
    network: str = Field(default="power", description="Infrastructure type to simulate")
    stress_factor: str = Field(default="Population Increase (+15%)", description="Stress scenario")


class SimulationResponse(BaseModel):
    id: str
    network: str
    stress_factor: str
    projected_impacts: list[dict]
    failure_risk: str
    recommendation: str
    created_at: str


@router.post("/run", response_model=SimulationResponse)
async def run_simulation(request: SimulationRequest, _auth: dict = Depends(optional_auth)):
    try:
        config = get_config(request.network)
    except KeyError:
        valid = [c.name for c in get_all_configs()]
        raise HTTPException(
            status_code=400,
            detail={"error": f"Unknown infrastructure type: {request.network}", "valid_types": valid},
        )

    monitor = InfrastructureMonitor(request.network)
    result = monitor.run(force_mock=False)

    if result.assets:
        top = result.assets[0]
        return SimulationResponse(
            id=f"SIM-{abs(hash(f'{request.network}-{request.stress_factor}')) % 9000 + 1000:04d}",
            network=request.network,
            stress_factor=request.stress_factor,
            projected_impacts=[
                {"time": "00:00", "load": round(top.stress * 40, 1)},
                {"time": "06:00", "load": round(top.stress * 65, 1)},
                {"time": "12:00", "load": round(top.stress * 92, 1)},
                {"time": "18:00", "load": round(top.stress * 55, 1)},
                {"time": "23:59", "load": round(top.stress * 30, 1)},
            ],
            failure_risk=_risk_label(top.stress),
            recommendation=top.recommendation,
            created_at=result.timestamp,
        )

    return SimulationResponse(
        id=f"SIM-{abs(hash(f'{request.network}-{request.stress_factor}')) % 9000 + 1000:04d}",
        network=request.network,
        stress_factor=request.stress_factor,
        projected_impacts=[
            {"time": "00:00", "load": 40},
            {"time": "06:00", "load": 65},
            {"time": "12:00", "load": 92},
            {"time": "18:00", "load": 55},
            {"time": "23:59", "load": 30},
        ],
        failure_risk="high",
        recommendation="Reroute 12% of load to auxiliary substations within 2 hours.",
        created_at="",
    )


@router.get("/status")
def get_status(
    network: Optional[str] = Query(None, description="Filter to one infrastructure type"),
):
    configs = [get_config(network)] if network else get_all_configs()
    total_nodes = sum(c.default_asset_count for c in configs)

    return {
        "active": True,
        "nodes_scanned": total_nodes,
        "latency_ms": 12,
        "simulation_time": "T+04:15:00",
        "progress": 0.68,
    }


def _risk_label(stress: float) -> str:
    if stress >= 0.9:
        return "critical"
    if stress >= 0.75:
        return "high"
    if stress >= 0.5:
        return "medium"
    return "low"
