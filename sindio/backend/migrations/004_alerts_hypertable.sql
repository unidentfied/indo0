-- Sindio: Migration 004 — Alerts hypertable with 5-year retention
-- Extends the base alerts table from migration 001 with monitoring columns.
-- Published to Redis pub/sub for real-time WebSocket push.

-- Extend category check to include all infrastructure types
ALTER TABLE alerts DROP CONSTRAINT IF EXISTS alerts_category_check;
ALTER TABLE alerts ADD CONSTRAINT alerts_category_check
    CHECK (category IN ('electricity', 'water', 'roads', 'traffic', 'utilities',
                        'power', 'solid_waste', 'sidewalks', 'lrt', 'sgr', 'airports'));

-- Add monitoring/detail columns used by alert_generator.py
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS infrastructure_type VARCHAR(20);
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS asset_id VARCHAR(255);
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS severity DOUBLE PRECISION CHECK (severity >= 0 AND severity <= 1);
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS classification_type VARCHAR(30);
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS classification_confidence DOUBLE PRECISION;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS recommended_action TEXT;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS temporal_spacing JSONB DEFAULT '{}';
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS previous_stress DOUBLE PRECISION;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS current_stress DOUBLE PRECISION;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS stress_delta_24h DOUBLE PRECISION;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS trigger_reason VARCHAR(100);

-- Hypertable: 30-day chunks, 5-year retention
SELECT create_hypertable('alerts', 'created_at',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists       => TRUE
);

-- Drop data older than 5 years
SELECT add_retention_policy('alerts', INTERVAL '5 years',
    if_not_exists => TRUE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_alerts_type_severity
    ON alerts (infrastructure_type, severity DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_alerts_asset
    ON alerts (asset_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_alerts_location
    ON alerts USING GIST (location);

CREATE INDEX IF NOT EXISTS idx_alerts_unresolved
    ON alerts (infrastructure_type, created_at DESC)
    WHERE resolved_at IS NULL AND acknowledged = FALSE;
