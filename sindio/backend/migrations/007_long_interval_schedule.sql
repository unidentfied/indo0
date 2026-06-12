-- Sindio: Migration 007 — Long Interval Schedule Persistence
-- Stores per-asset schedule state in PostgreSQL for durability
-- across restarts (6+ month intervals require persistent storage).

CREATE TABLE IF NOT EXISTS long_interval_schedule (
    asset_id              TEXT NOT NULL,
    infrastructure_type   VARCHAR(20) NOT NULL CHECK (infrastructure_type IN ('water', 'power', 'roads', 'solid_waste', 'sidewalks', 'lrt', 'sgr', 'airports')),
    classification        VARCHAR(20) DEFAULT 'normal' CHECK (classification IN ('recurring_only', 'density_driven', 'hybrid', 'normal')),
    density_rho           DOUBLE PRECISION,
    current_stress        DOUBLE PRECISION,
    base_interval_days    INTEGER NOT NULL,
    applied_multiplier    DOUBLE PRECISION DEFAULT 1.0,
    final_interval_days   INTEGER NOT NULL,
    jitter_pct            DOUBLE PRECISION DEFAULT 0,
    last_run              TIMESTAMPTZ,
    next_run              TIMESTAMPTZ NOT NULL,
    last_result           JSONB DEFAULT '{}',
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (asset_id)
);

-- Index for the dispatcher: find all assets due to run
CREATE INDEX IF NOT EXISTS idx_schedule_next_run
    ON long_interval_schedule (next_run)
    WHERE next_run IS NOT NULL;

-- Index for API: list next updates by infra type
CREATE INDEX IF NOT EXISTS idx_schedule_infra
    ON long_interval_schedule (infrastructure_type, next_run);

-- Index for dashboard: assets approaching their next check
CREATE INDEX IF NOT EXISTS idx_schedule_approaching
    ON long_interval_schedule (next_run)
    WHERE next_run > NOW() AND next_run < NOW() + INTERVAL '7 days';
