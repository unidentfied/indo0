-- TimescaleDB Data Retention Policy
-- ============================================================
-- Automatically drops old chunks to prevent unbounded table growth.
-- Run: psql -h $DB_HOST -U $DB_USER -d sindio -f 015_retention_policy.sql

-- Add retention policy for sensor_readings (drop after 90 days)
SELECT add_retention_policy('sensor_readings', INTERVAL '90 days');

-- Add retention policy for ingestion_logs (drop after 30 days)
SELECT add_retention_policy('ingestion_logs', INTERVAL '30 days');

-- Add retention policy for alert_history (drop after 180 days)
SELECT add_retention_policy('alert_history', INTERVAL '180 days');

-- Materialized view: daily stress aggregates (refreshed every hour)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_stress AS
SELECT
    infrastructure_type,
    ward,
    date_trunc('day', timestamp) AS day,
    COUNT(*) AS reading_count,
    AVG(value) AS avg_stress,
    MAX(value) AS max_stress,
    MIN(value) AS min_stress,
    STDDEV(value) AS stress_stddev,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY value) AS p95_stress,
    SUM(CASE WHEN value > 0.8 THEN 1 ELSE 0 END) AS critical_count
FROM sensor_readings
WHERE timestamp > now() - interval '30 days'
GROUP BY infrastructure_type, ward, date_trunc('day', timestamp);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily_stress ON mv_daily_stress (infrastructure_type, ward, day);
CREATE INDEX IF NOT EXISTS idx_mv_daily_stress_day ON mv_daily_stress (day);

-- Materialized view: hourly monitor stress (refreshed every 15 min)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hourly_monitor AS
SELECT
    infrastructure_type,
    date_trunc('hour', timestamp) AS hour,
    COUNT(*) AS asset_count,
    AVG(stress) AS avg_stress,
    MAX(stress) AS max_stress,
    COUNT(*) FILTER (WHERE time_to_breach_hours < 24) AS imminent_breach_count
FROM stress_classifications
WHERE timestamp > now() - interval '7 days'
GROUP BY infrastructure_type, date_trunc('hour', timestamp);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_hourly_monitor ON mv_hourly_monitor (infrastructure_type, hour);

-- Refresh policy: every 15 minutes
SELECT add_job('refresh_materialized_view', '15 minutes', config => '{"view_name": "mv_hourly_monitor"}');
