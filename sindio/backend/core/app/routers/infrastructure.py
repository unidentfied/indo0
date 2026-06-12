from fastapi import APIRouter

router = APIRouter()

base_data = {
    "power": {
        "grid_stability": 98.2,
        "current_load": "4.2 GW",
        "active_nodes": 14204,
        "latency_ms": 12,
        "region": "Central District",
        "capacity_percent": 92.4,
        "redundancy_active": True,
    },
    "water": {
        "grid_stability": 94.2,
        "current_load": "82,400 m³/day",
        "active_nodes": 8400,
        "latency_ms": 18,
        "region": "Nairobi Water Zone A",
        "capacity_percent": 78.0,
        "redundancy_active": True,
    },
    "road": {
        "grid_stability": 87.5,
        "current_load": "High",
        "active_nodes": 3200,
        "latency_ms": 45,
        "region": "Greater Nairobi Road Net",
        "capacity_percent": 88.0,
        "redundancy_active": False,
    },
}

@router.get("/{system}")
def get_infrastructure(system: str):
    return base_data.get(system, {"error": "system not found"})
