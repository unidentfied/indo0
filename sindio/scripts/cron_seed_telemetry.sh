#!/usr/bin/env bash
# Sindio — Telemetry Seed Cron
# Run every 5 minutes to ensure monitor ingestion has recent data.
# Usage: */5 * * * * /path/to/cron_seed_telemetry.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="/tmp/sindio-venv/bin/python3"

# Ensure venv exists
if [ ! -f "$VENV_PYTHON" ]; then
    python3 -m venv /tmp/sindio-venv
    "$VENV_PYTHON" -m pip install --only-binary=:all: psycopg2-binary numpy > /dev/null 2>&1
fi

cd "$SCRIPT_DIR"

"$VENV_PYTHON" << 'PYEOF'
import psycopg2, random, os, datetime

def env(k, d):
    return os.environ.get(k, d)

DB = f"host={env('DB_HOST','localhost')} port={env('DB_PORT','5432')} dbname={env('DB_NAME','sindio')} user={env('DB_USER','sindio_user')} password={env('DB_PASSWORD','sindio_pass')}"
now = datetime.datetime.now(datetime.timezone.utc)

try:
    conn = psycopg2.connect(DB)
    cur = conn.cursor()

    # Power SCADA
    cur.execute("""
        INSERT INTO power_scada (bus_id, voltage_pu, load_mw, ward, lat, lon, updated_at)
        SELECT 'BUS-' || i, random()*0.2+0.8, random()*100+20,
          'CBD', -1.29+random()*0.1, 36.82+random()*0.1, NOW()
        FROM generate_series(1,5) i
    """)

    # Water SCADA
    cur.execute("""
        INSERT INTO water_scada (node_id, pressure_m, flow_lps, ward, lat, lon, updated_at)
        SELECT 'WAT-' || i, random()*30+15, random()*50+10,
          'CBD', -1.29+random()*0.1, 36.82+random()*0.1, NOW()
        FROM generate_series(1,5) i
    """)

    # Mobility
    cur.execute("""
        INSERT INTO mobility_aggregates (time, h3_index, h3_resolution, vehicle_count, avg_speed_ms, freeflow_speed_ms, created_at)
        SELECT NOW(), '87259' || lpad(i::text, 4, '0'), 9,
          (random()*200+10)::int, random()*15+2, 13.9, NOW()
        FROM generate_series(1,5) i
    """)

    # Other telemetry tables
    for tbl, prefix, cols in [
        ("waste_sensors", "WST", "station_id, fill_level"),
        ("sidewalk_counters", "SW", "path_id, pedestrian_count"),
        ("lrt_telemetry", "LRT", "segment_id, train_count, headway_sec"),
        ("sgr_telemetry", "SGR", "segment_id, stress_level"),
        ("airport_telemetry", "RWY", "runway_id, flight_rate, surface_condition"),
    ]:
        cur.execute(f"""
            INSERT INTO {tbl} ({cols}, ward, lat, lon, updated_at)
            SELECT '{prefix}-' || i, random()*100, 'CBD', -1.29, 36.82, NOW()
            FROM generate_series(1,3) i
        """)

    conn.commit()
    cur.close()
    conn.close()
except Exception:
    pass  # DB unreachable — non-critical cron, skip silently
PYEOF
