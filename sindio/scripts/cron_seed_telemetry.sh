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

DB_PASS = env('DB_PASSWORD', '')
if not DB_PASS:
    raise RuntimeError("DB_PASSWORD environment variable is required for telemetry seeding")
DB = f"host={env('DB_HOST','localhost')} port={env('DB_PORT','5432')} dbname={env('DB_NAME','sindio')} user={env('DB_USER','sindio_user')} password={DB_PASS}"
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
        INSERT INTO mobility_aggregates (time, h3_index, vehicle_count, ward, lat, lon)
        SELECT NOW(), '87259' || lpad(i::text, 4, '0'),
          random()*200+10, 'CBD', -1.29+random()*0.1, 36.82+random()*0.1
        FROM generate_series(1,5) i
    """)

    # Other telemetry tables
    cur.execute("""
        INSERT INTO waste_sensors (station_id, fill_level, ward, lat, lon, updated_at)
        SELECT 'WST-' || i, random()*100, 'CBD', -1.29+random()*0.1, 36.82+random()*0.1, NOW()
        FROM generate_series(1,3) i
    """)

    cur.execute("""
        INSERT INTO sidewalk_counters (path_id, pedestrian_count, ward, lat, lon, updated_at)
        SELECT 'SW-' || i, random()*100, 'CBD', -1.29+random()*0.1, 36.82+random()*0.1, NOW()
        FROM generate_series(1,3) i
    """)

    cur.execute("""
        INSERT INTO lrt_telemetry (segment_id, train_count, headway_sec, ward, lat, lon, updated_at)
        SELECT 'LRT-' || i, (random()*10)::int, random()*300+60, 'CBD', -1.29+random()*0.1, 36.82+random()*0.1, NOW()
        FROM generate_series(1,3) i
    """)

    cur.execute("""
        INSERT INTO sgr_telemetry (segment_id, stress_level, speed_limit, ward, lat, lon, updated_at)
        SELECT 'SGR-' || i, random()*100, 80.0, 'CBD', -1.29+random()*0.1, 36.82+random()*0.1, NOW()
        FROM generate_series(1,3) i
    """)

    cur.execute("""
        INSERT INTO airport_telemetry (runway_id, flight_rate, surface_condition, ward, lat, lon, updated_at)
        SELECT 'RWY-' || i, random()*100, 0.95, 'CBD', -1.29+random()*0.1, 36.82+random()*0.1, NOW()
        FROM generate_series(1,3) i
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Seeding completed successfully")
except Exception as e:
    import traceback
    traceback.print_exc()
PYEOF
