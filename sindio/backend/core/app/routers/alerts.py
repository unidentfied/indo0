from fastapi import APIRouter

router = APIRouter()

alerts = [
    {
        "id": "ALT-001",
        "timestamp": "09:42:15 AM",
        "level": "critical",
        "category": "electricity",
        "title": "Power Grid: 85% capacity in Kilimani region",
        "description": "Transformer cooling required.",
        "location": "Kilimani",
    },
    {
        "id": "ALT-002",
        "timestamp": "09:30:04 AM",
        "level": "warning",
        "category": "utilities",
        "title": "Water Main Pressure drop detected in Upper Hill",
        "description": "Sensor ID: W-102. Pressure at 64% of nominal.",
        "location": "Upper Hill",
    },
    {
        "id": "ALT-003",
        "timestamp": "09:12:40 AM",
        "level": "advisory",
        "category": "traffic",
        "title": "Autonomous Bus Route 14 redirected",
        "description": "Due to road maintenance on Waiyaki Way.",
        "location": "Waiyaki Way",
    },
]

@router.get("/dashboard")
def get_alerts():
    return alerts
