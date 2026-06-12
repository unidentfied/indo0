-- Sindio: Migration 008 — Classification History (TimescaleDB hypertable)
-- Stores per-asset classification results for trend/shift detection over years.
-- Queried by the long-window classifier to detect transitions like
-- "recurring → density_driven" as population growth overtakes seasonal patterns.

CREATE TABLE IF NOT EXISTS classification_history (
    id                  BIGSERIAL,
    asset_id            VARCHAR(255) NOT NULL,
    asset_type          VARCHAR(20) NOT NULL,
    ward                VARCHAR(255),
    classification_type VARCHAR(30) NOT NULL CHECK (
        classification_type IN (
            'recurring_only', 'density_driven_only', 'mixed', 'unstable'
        )
    ),
    confidence           DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    dominant_period_days DOUBLE PRECISION,
    peak_timing_cv       DOUBLE PRECISION,    -- coefficient of variation of peak timing
    spearman_rho         DOUBLE PRECISION,    -- 18-month rolling correlation
    data_window_months   INTEGER NOT NULL,     -- months of data used for this classification
    next_check_interval_days INTEGER,
    recurring_multiplier DOUBLE PRECISION,
    density_multiplier   DOUBLE PRECISION,
    stl_seasonal_strength DOUBLE PRECISION,   -- strength of seasonal component (0-1)
    stl_trend_strength   DOUBLE PRECISION,    -- strength of trend component (0-1)
    classification_metadata JSONB DEFAULT '{}',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (id, created_at)
);

-- Convert to hypertable: 90-day chunks, 10-year retention
SELECT create_hypertable('classification_history', 'created_at',
    chunk_time_interval => INTERVAL '90 days',
    if_not_exists       => TRUE
);

-- Index for per-asset history (shift detection)
CREATE INDEX IF NOT EXISTS idx_class_history_asset
    ON classification_history (asset_id, created_at DESC);

-- Index for classification type trends
CREATE INDEX IF NOT EXISTS idx_class_history_type
    ON classification_history (classification_type, created_at DESC);

-- Index for ward-level aggregation
CREATE INDEX IF NOT EXISTS idx_class_history_ward
    ON classification_history (ward, created_at DESC);
