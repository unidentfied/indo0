"""
Sindio — Seed test data into the local PostgreSQL/PostGIS database.
Generates synthetic Nairobi infrastructure, telemetry, and alert records.
Usage: python scripts/seed_test_data.py
"""
import os
import uuid
import random
import datetime
from dotenv import load_dotenv

load_dotenv()

# Configuration
DB_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
    f"{os.getenv('DB_PASSWORD', '')}@"
    f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
    f"{os.getenv('DB_NAME', 'sindio')}",
)

NAIROBI_BBOX = {
    "lat_min": -1.4300,
    "lat_max": -0.9800,
    "lng_min": 36.6500,
    "lng_max": 37.1000,
}

SYSTEM_TYPES = ["power", "water", "road"]
METRICS = {
    "power": [("voltage_kv", "kV"), ("current_a", "A"), ("temperature_c", "°C")],
    "water": [("pressure_psi", "PSI"), ("flow_rate", "m³/h"), ("quality_ph", "pH")],
    "road": [("speed_kmh", "km/h"), ("congestion_pct", "%"), ("vehicle_count", "vehicles")],
}
SEVERITY_LEVELS = ["critical", "warning", "advisory", "info"]
CATEGORIES = ["electricity", "water", "roads", "traffic", "utilities"]

LANDMARKS = [
    ("Kilimani", 36.7850, -1.2900),
    ("Upper Hill", 36.8122, -1.2975),
    ("Westlands", 36.8090, -1.2670),
    ("CBD", 36.8219, -1.2833),
    ("Karen", 36.7200, -1.3800),
    ("Eastleigh", 36.8580, -1.2700),
    ("Langata", 36.7700, -1.3700),
    ("Parklands", 36.8000, -1.2600),
    ("Ngong Road", 36.7900, -1.3000),
    ("Industrial Area", 36.8500, -1.3200),
]


def generate_nodes(count: int = 50) -> list:
    nodes = []
    for _ in range(count):
        name, base_lng, base_lat = random.choice(LANDMARKS)
        system = random.choice(SYSTEM_TYPES)
        capacity = round(random.uniform(50, 500), 1)
        current = round(random.uniform(10, capacity * 1.05), 1)
        nodes.append({
            "id": str(uuid.uuid4()),
            "system_type": system,
            "node_name": f"{system}-{name}-{random.randint(1, 99):02d}",
            "lng": round(base_lng + random.uniform(-0.02, 0.02), 6),
            "lat": round(base_lat + random.uniform(-0.02, 0.02), 6),
            "capacity": capacity,
            "current_load": current,
            "status": random.choice(["active", "active", "active", "degraded"]),
        })
    return nodes


def generate_telemetry(nodes: list, hours: int = 24) -> list:
    records = []
    base_time = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    for node in nodes:
        metrics = METRICS.get(node["system_type"], [])
        for _ in range(random.randint(5, 20)):
            metric_name, unit = random.choice(metrics)
            base_val = random.uniform(10, 100)
            records.append({
                "node_id": node["id"],
                "metric_type": metric_name,
                "value": round(base_val + random.uniform(-20, 20), 2),
                "unit": unit,
                "recorded_at": (base_time + datetime.timedelta(minutes=random.randint(0, hours * 60))).isoformat(),
            })
    return records


def generate_alerts(nodes: list, count: int = 20) -> list:
    titles = {
        "electricity": [
            "Transformer overload predicted at {location}",
            "Grid frequency deviation detected in {location}",
            "Substation {node} approaching thermal limit",
        ],
        "water": [
            "Pressure drop detected in {location}",
            "Leak suspected on main line near {location}",
            "Reservoir level below threshold at {location}",
        ],
        "roads": [
            "Heavy congestion forecast on {location}",
            "Bridge load factor exceeding design at {location}",
            "Surface degradation detected on {location}",
        ],
        "traffic": [
            "Route {node} redirected due to incident",
            "AADT surge recorded on {location} corridor",
            "Signal timing misalignment at {location} intersection",
        ],
        "utilities": [
            "Sewage flow anomaly detected near {location}",
            "Gas pressure reading irregular at {location}",
            "Telecom node {node} latency spike",
        ],
    }
    alerts = []
    for _ in range(count):
        node = random.choice(nodes)
        cat = random.choice(CATEGORIES)
        cat_titles = titles.get(cat, titles["utilities"])
        name, lng, lat = random.choice(LANDMARKS)
        alerts.append({
            "id": str(uuid.uuid4()),
            "level": random.choice(SEVERITY_LEVELS),
            "category": cat,
            "title": random.choice(cat_titles).format(location=name, node=node["node_name"]),
            "description": f"Sensor data indicates abnormal readings requiring investigation.",
            "lng": lng,
            "lat": lat,
            "node_id": node["id"],
            "created_at": (datetime.datetime.utcnow() - datetime.timedelta(minutes=random.randint(0, 480))).isoformat(),
        })
    return alerts


def generate_simulations(count: int = 10) -> list:
    sims = []
    for _ in range(count):
        network = random.choice(SYSTEM_TYPES)
        sims.append({
            "id": str(uuid.uuid4()),
            "network_type": network,
            "stress_factor": random.choice([
                "Population Increase (+15%)",
                "Monsoon Flooding (50yr)",
                "Peak Hour +30%",
                "Infrastructure Failure Cascade",
                "Heatwave — Thermal Expansion",
            ]),
            "failure_risk": random.choice(["low", "medium", "high"]),
            "status": random.choice(["completed", "running", "completed", "completed"]),
            "recommendation": f"Re-route {random.randint(10, 40)}% of {network} capacity to auxiliary nodes.",
        })
    return sims


def main():
    import psycopg2

    print("Generating test data for Sindio...")
    nodes = generate_nodes(50)
    telemetry = generate_telemetry(nodes)
    alerts = generate_alerts(nodes, 20)
    simulations = generate_simulations(10)

    print(f"  Nodes:      {len(nodes)}")
    print(f"  Telemetry:  {len(telemetry)} records")
    print(f"  Alerts:     {len(alerts)}")
    print(f"  Simulations:{len(simulations)}")

    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        print(f"Connected to PostgreSQL: {DB_URL}")

        # Insert infrastructure nodes
        for node in nodes:
            cur.execute(
                """INSERT INTO infrastructure_nodes (id, system_type, node_name, location, capacity, current_load, status)
                   VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (node["id"], node["system_type"], node["node_name"],
                 node["lng"], node["lat"], node["capacity"], node["current_load"], node["status"]),
            )

        # Insert telemetry
        for t in telemetry:
            cur.execute(
                """INSERT INTO sensor_telemetry (node_id, metric_type, value, unit, recorded_at)
                   VALUES (%s, %s, %s, %s, %s)""",
                (t["node_id"], t["metric_type"], t["value"], t["unit"], t["recorded_at"]),
            )

        # Insert alerts
        for alert in alerts:
            cur.execute(
                """INSERT INTO alerts (id, level, category, title, description, location, node_id, created_at)
                   VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (alert["id"], alert["level"], alert["category"], alert["title"],
                 alert["description"], alert["lng"], alert["lat"],
                 alert["node_id"], alert["created_at"]),
            )

        # Insert simulations
        for sim in simulations:
            cur.execute(
                """INSERT INTO simulations (id, network_type, stress_factor, failure_risk, status, recommendation)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (sim["id"], sim["network_type"], sim["stress_factor"],
                 sim["failure_risk"], sim["status"], sim["recommendation"]),
            )

        conn.commit()
        cur.close()
        conn.close()
        print("Seed complete. Data inserted into PostgreSQL.")

    except Exception as exc:
        print(f"Database insert failed: {exc}")
        print("Data generated but NOT inserted. Ensure PostgreSQL is running.")


if __name__ == "__main__":
    main()
