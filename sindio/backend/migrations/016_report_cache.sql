-- Sindio Migration 016: Report Cache Table
-- Stores official report metrics for alignment checking by the unified monitor.

CREATE TABLE IF NOT EXISTS report_cache (
    id              SERIAL PRIMARY KEY,
    infrastructure_type VARCHAR(30) NOT NULL,
    report_source   VARCHAR(255) NOT NULL DEFAULT '',
    report_date     DATE NOT NULL,
    frequency       VARCHAR(20) NOT NULL DEFAULT 'monthly',
    report_data     JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_report_cache_type_date
    ON report_cache (infrastructure_type, report_date DESC);

CREATE INDEX IF NOT EXISTS idx_report_cache_created
    ON report_cache (created_at DESC);
