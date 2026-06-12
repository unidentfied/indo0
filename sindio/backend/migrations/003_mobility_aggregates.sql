-- Sindio: Migration 003 — Mobility Aggregates Hypertable
-- TimescaleDB hypertable for 5-min H3-binned mobility metrics.
-- Fed by the Rust streaming consumer (Kafka → H3 → TimescaleDB).

CREATE TABLE IF NOT EXISTS mobility_aggregates (
    time                TIMESTAMPTZ NOT NULL,
    h3_index            VARCHAR(16) NOT NULL,
    h3_resolution       SMALLINT NOT NULL DEFAULT 9,
    vehicle_count       INTEGER NOT NULL,
    avg_speed_ms        DOUBLE PRECISION,
    p50_speed_ms        DOUBLE PRECISION,
    p95_speed_ms        DOUBLE PRECISION,
    congestion_index    DOUBLE PRECISION,
    freeflow_speed_ms   DOUBLE PRECISION NOT NULL DEFAULT 13.9,
    bounding_pings      JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Convert to TimescaleDB hypertable (7-day chunks)
SELECT create_hypertable('mobility_aggregates', 'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists       => TRUE
);

-- Unique constraint for idempotent upserts
CREATE UNIQUE INDEX IF NOT EXISTS uq_mobility_bin
    ON mobility_aggregates (h3_index, time);

-- Spatial index on H3 cell
CREATE INDEX IF NOT EXISTS idx_mobility_h3
    ON mobility_aggregates (h3_index, time DESC);

-- Enable compression (optional, activate after 30 days)
-- SELECT add_compression_policy('mobility_aggregates', INTERVAL '30 days');
