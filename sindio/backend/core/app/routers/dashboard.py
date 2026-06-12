from fastapi import APIRouter, Query

router = APIRouter()

_METRICS = {
    "power": [
        {"label": "Grid Stability", "value": "99.7%", "delta": "+0.2%", "status": "good"},
        {"label": "Current Load", "value": "0.5 GW", "delta": "+0.02 GW", "status": "good"},
        {"label": "Active Nodes", "value": "14,204", "delta": "+12", "status": "good"},
        {"label": "Stressed Nodes", "value": "829", "delta": "+34", "status": "warning"},
    ],
    "water": [
        {"label": "System Pressure", "value": "78.5 PSI", "delta": "-2.1 PSI", "status": "good"},
        {"label": "Flow Rate", "value": "12,400 m\u00b3/h", "delta": "+340", "status": "good"},
        {"label": "Active Nodes", "value": "8,400", "delta": "+8", "status": "good"},
        {"label": "Leak Alerts", "value": "3", "delta": "+1", "status": "warning"},
    ],
    "roads": [
        {"label": "Avg Speed", "value": "34.2 km/h", "delta": "-1.8", "status": "good"},
        {"label": "Congestion Index", "value": "0.42", "delta": "+0.03", "status": "warning"},
        {"label": "Active Segments", "value": "6,454", "delta": "+5", "status": "good"},
        {"label": "Incidents", "value": "7", "delta": "+2", "status": "advisory"},
    ],
    "solid_waste": [
        {"label": "Collection Rate", "value": "86%", "delta": "+1%", "status": "good"},
        {"label": "Active Routes", "value": "42", "delta": "0", "status": "good"},
        {"label": "Overflow Sensors", "value": "5", "delta": "+2", "status": "warning"},
    ],
    "sidewalks": [
        {"label": "Condition Score", "value": "72/100", "delta": "-3", "status": "warning"},
        {"label": "Accessibility Rating", "value": "68%", "delta": "+2%", "status": "good"},
    ],
    "lrt": [
        {"label": "On-Time Performance", "value": "94%", "delta": "+1%", "status": "good"},
        {"label": "Daily Ridership", "value": "48,200", "delta": "+1,200", "status": "good"},
    ],
    "sgr": [
        {"label": "On-Time Performance", "value": "88%", "delta": "-2%", "status": "warning"},
        {"label": "Daily Ridership", "value": "15,400", "delta": "+800", "status": "good"},
    ],
    "airports": [
        {"label": "Flight Delays", "value": "12%", "delta": "+3%", "status": "advisory"},
        {"label": "Gate Utilization", "value": "78%", "delta": "0", "status": "good"},
    ],
}

_ALERTS = [
    {
        "id": "ALT-DB001",
        "timestamp": "2026-06-09T10:30:00+00:00",
        "level": "critical",
        "category": "electricity",
        "title": "Power Grid: Transformer overload at Kilimani Substation",
        "description": "Transformer 4-A at 85% capacity. Cooling system activated. Recommend load shedding on feeder lines 7, 12.",
        "location": "Kilimani",
        "confidence": 0.92,
        "data_sources_used": ["scada_realtime", "weather_forecast"],
    },
    {
        "id": "ALT-DB002",
        "timestamp": "2026-06-09T10:15:00+00:00",
        "level": "warning",
        "category": "water",
        "title": "Water Main: Pressure drop detected in Upper Hill",
        "description": "Sensor W-102 at 64% of nominal pressure. Possible leak on the 300mm main.",
        "location": "Upper Hill",
        "confidence": 0.78,
        "data_sources_used": ["pressure_sensors", "flow_meters"],
    },
    {
        "id": "ALT-DB003",
        "timestamp": "2026-06-09T09:45:00+00:00",
        "level": "advisory",
        "category": "roads",
        "title": "Road Network: Heavy congestion on Waiyaki Way",
        "description": "Traffic speed dropped to 18 km/h. Recommend signal timing adjustment at Westlands junction.",
        "location": "Westlands",
        "confidence": 0.88,
        "data_sources_used": ["traffic_cameras", "gps_probes"],
    },
    {
        "id": "ALT-DB004",
        "timestamp": "2026-06-09T09:20:00+00:00",
        "level": "warning",
        "category": "solid_waste",
        "title": "Solid Waste: Overflow detected at Karura collection point",
        "description": "Bin sensor KP-044 at 97% capacity. Collection scheduled for tomorrow.",
        "location": "Karura",
        "confidence": 0.95,
        "data_sources_used": ["bin_sensors", "collection_schedule"],
    },
    {
        "id": "ALT-DB005",
        "timestamp": "2026-06-09T08:55:00+00:00",
        "level": "advisory",
        "category": "airports",
        "title": "Airports: Gate congestion at JKIA Terminal 1A",
        "description": "4 flights scheduled for gates 3-6 within 30min window. Recommend reassigning 2 flights.",
        "location": "JKIA",
        "confidence": 0.82,
        "data_sources_used": ["flight_schedule", "gate_sensors"],
    },
]


@router.get("/dashboard/metrics")
async def dashboard_metrics(system: str = Query("power")):
    system = system.lower().replace(" ", "_").replace("-", "_")
    return _METRICS.get(system, _METRICS["power"])


@router.get("/dashboard/alerts")
async def dashboard_alerts(limit: int = Query(10)):
    return _ALERTS[:limit]
