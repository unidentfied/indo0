-- Sindio Migration 014: Telemetry Tables for Unified Monitor
-- Creates real-time telemetry tables for ALL infrastructure types.
-- These tables are queried by the unified monitoring ingestion layer.

-- ============================================================
-- Power SCADA Telemetry
-- ============================================================
CREATE TABLE IF NOT EXISTS power_scada (
    id              BIGSERIAL PRIMARY KEY,
    bus_id          VARCHAR(64) NOT NULL,
    voltage_pu      DOUBLE PRECISION NOT NULL,
    load_mw         DOUBLE PRECISION NOT NULL,
    load_mvar       DOUBLE PRECISION,
    line_loading_pct DOUBLE PRECISION DEFAULT 0.0,
    frequency_hz    DOUBLE PRECISION DEFAULT 50.0,
    ward            VARCHAR(255) DEFAULT '',
    lat             DOUBLE PRECISION DEFAULT 0.0,
    lon             DOUBLE PRECISION DEFAULT 0.0,
    capacity        DOUBLE PRECISION DEFAULT 100.0,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('power_scada', 'updated_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_power_scada_bus ON power_scada(bus_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_power_scada_time ON power_scada(updated_at DESC);

-- ============================================================
-- Water SCADA Telemetry
-- ============================================================
CREATE TABLE IF NOT EXISTS water_scada (
    id              BIGSERIAL PRIMARY KEY,
    node_id         VARCHAR(64) NOT NULL,
    pressure_m      DOUBLE PRECISION NOT NULL,
    flow_lps        DOUBLE PRECISION NOT NULL,
    head_m          DOUBLE PRECISION,
    turbidity_ntu   DOUBLE PRECISION,
    chlorine_mgl    DOUBLE PRECISION,
    ward            VARCHAR(255) DEFAULT '',
    lat             DOUBLE PRECISION DEFAULT 0.0,
    lon             DOUBLE PRECISION DEFAULT 0.0,
    capacity        DOUBLE PRECISION DEFAULT 100.0,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('water_scada', 'updated_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_water_scada_node ON water_scada(node_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_water_scada_time ON water_scada(updated_at DESC);

-- ============================================================
-- Waste Collection Sensors
-- ============================================================
CREATE TABLE IF NOT EXISTS waste_sensors (
    id              BIGSERIAL PRIMARY KEY,
    station_id      VARCHAR(64) NOT NULL,
    fill_level      DOUBLE PRECISION NOT NULL,  -- 0.0–1.0
    weight_kg       DOUBLE PRECISION,
    temperature_c   DOUBLE PRECISION,
    ward            VARCHAR(255) DEFAULT '',
    lat             DOUBLE PRECISION DEFAULT 0.0,
    lon             DOUBLE PRECISION DEFAULT 0.0,
    capacity        DOUBLE PRECISION DEFAULT 100.0,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('waste_sensors', 'updated_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_waste_station ON waste_sensors(station_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_waste_time ON waste_sensors(updated_at DESC);

-- ============================================================
-- Sidewalk Pedestrian Counters
-- ============================================================
CREATE TABLE IF NOT EXISTS sidewalk_counters (
    id              BIGSERIAL PRIMARY KEY,
    path_id         VARCHAR(64) NOT NULL,
    pedestrian_count INTEGER NOT NULL,
    avg_speed_ms    DOUBLE PRECISION,
    density_ped_m2  DOUBLE PRECISION,
    ward            VARCHAR(255) DEFAULT '',
    lat             DOUBLE PRECISION DEFAULT 0.0,
    lon             DOUBLE PRECISION DEFAULT 0.0,
    capacity        DOUBLE PRECISION DEFAULT 100.0,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('sidewalk_counters', 'updated_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_sidewalk_path ON sidewalk_counters(path_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sidewalk_time ON sidewalk_counters(updated_at DESC);

-- ============================================================
-- LRT Telemetry
-- ============================================================
CREATE TABLE IF NOT EXISTS lrt_telemetry (
    id              BIGSERIAL PRIMARY KEY,
    segment_id      VARCHAR(64) NOT NULL,
    train_count     INTEGER NOT NULL,
    headway_sec     DOUBLE PRECISION,
    avg_speed_kmh   DOUBLE PRECISION,
    delay_sec       DOUBLE PRECISION DEFAULT 0.0,
    ward            VARCHAR(255) DEFAULT '',
    lat             DOUBLE PRECISION DEFAULT 0.0,
    lon             DOUBLE PRECISION DEFAULT 0.0,
    capacity        DOUBLE PRECISION DEFAULT 100.0,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('lrt_telemetry', 'updated_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_lrt_segment ON lrt_telemetry(segment_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_lrt_time ON lrt_telemetry(updated_at DESC);

-- ============================================================
-- SGR (Standard Gauge Railway) Telemetry
-- ============================================================
CREATE TABLE IF NOT EXISTS sgr_telemetry (
    id              BIGSERIAL PRIMARY KEY,
    segment_id      VARCHAR(64) NOT NULL,
    stress_level    DOUBLE PRECISION NOT NULL,  -- 0.0–1.0
    speed_limit_kmh DOUBLE PRECISION,
    train_count     INTEGER DEFAULT 0,
    track_temp_c    DOUBLE PRECISION,
    ward            VARCHAR(255) DEFAULT '',
    lat             DOUBLE PRECISION DEFAULT 0.0,
    lon             DOUBLE PRECISION DEFAULT 0.0,
    capacity        DOUBLE PRECISION DEFAULT 100.0,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('sgr_telemetry', 'updated_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_sgr_segment ON sgr_telemetry(segment_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sgr_time ON sgr_telemetry(updated_at DESC);

-- ============================================================
-- Airport Operations Telemetry
-- ============================================================
CREATE TABLE IF NOT EXISTS airport_telemetry (
    id              BIGSERIAL PRIMARY KEY,
    runway_id       VARCHAR(64) NOT NULL,
    flight_rate     DOUBLE PRECISION NOT NULL,  -- flights/hr
    surface_condition VARCHAR(20) DEFAULT 'good',  -- good | fair | poor
    visibility_km   DOUBLE PRECISION,
    wind_speed_kmh  DOUBLE PRECISION,
    ward            VARCHAR(255) DEFAULT '',
    lat             DOUBLE PRECISION DEFAULT 0.0,
    lon             DOUBLE PRECISION DEFAULT 0.0,
    capacity        DOUBLE PRECISION DEFAULT 100.0,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('airport_telemetry', 'updated_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_airport_runway ON airport_telemetry(runway_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_airport_time ON airport_telemetry(updated_at DESC);

-- ============================================================
-- Stress Classifications (previously created at runtime)
-- ============================================================
CREATE TABLE IF NOT EXISTS stress_classifications (
    asset_id          VARCHAR(255) PRIMARY KEY,
    asset_type        VARCHAR(20),
    ward              VARCHAR(255),
    geometry          GEOMETRY(POINT, 4326),
    stress_ml         DOUBLE PRECISION,
    stress_physics    DOUBLE PRECISION,
    time_to_breach_hours DOUBLE PRECISION,
    failure_mode      VARCHAR(30),
    cascading_effects TEXT,
    recommendation    TEXT,
    classification_type VARCHAR(30),
    confidence        DOUBLE PRECISION,
    dominant_period_hours DOUBLE PRECISION,
    spearman_rho      DOUBLE PRECISION,
    recurrence_pct    DOUBLE PRECISION,
    density_pct       DOUBLE PRECISION,
    classification_pvalue DOUBLE PRECISION,
    significant_cycles TEXT,
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stress_class_geom
    ON stress_classifications USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_stress_class_type
    ON stress_classifications (classification_type, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_stress_class_ward
    ON stress_classifications (ward, classification_type);

-- ============================================================
-- Seed: Sample telemetry data for development
-- ============================================================

-- Power SCADA sample
INSERT INTO power_scada (bus_id, voltage_pu, load_mw, ward, lat, lon, capacity) VALUES
('sub_4a', 0.97, 85.3, 'Central', -1.2921, 36.8219, 100.0),
('sub_7b', 0.99, 62.1, 'Westlands', -1.2833, 36.8050, 100.0),
('sub_1c', 0.95, 91.0, 'Kilimani', -1.2950, 36.8100, 100.0);

-- Water SCADA sample
INSERT INTO water_scada (node_id, pressure_m, flow_lps, ward, lat, lon, capacity) VALUES
('pump_w102', 32.5, 45.2, 'Upper Hill', -1.2980, 36.8150, 200.0),
('reservoir_uh', 48.0, 120.0, 'Upper Hill', -1.2900, 36.8120, 500.0),
('junction_cb', 28.0, 38.5, 'Central', -1.2860, 36.8200, 150.0);

-- Waste sensors sample
INSERT INTO waste_sensors (station_id, fill_level, ward, lat, lon, capacity) VALUES
('ws_001', 0.72, 'Kibera', -1.3120, 36.7850, 10.0),
('ws_002', 0.45, 'Embakasi', -1.3200, 36.9100, 10.0),
('ws_003', 0.88, 'Kasarani', -1.2500, 36.9300, 10.0);

-- Sidewalk counters sample
INSERT INTO sidewalk_counters (path_id, pedestrian_count, ward, lat, lon, capacity) VALUES
('path_cbd_1', 420, 'Central', -1.2860, 36.8240, 500.0),
('path_west_1', 310, 'Westlands', -1.2670, 36.8090, 400.0),
('path_kili_1', 180, 'Kilimani', -1.2920, 36.8000, 300.0);

-- LRT telemetry sample
INSERT INTO lrt_telemetry (segment_id, train_count, headway_sec, ward, lat, lon, capacity) VALUES
('lrt_s1', 4, 300.0, 'Central', -1.2850, 36.8200, 6.0),
('lrt_s2', 3, 420.0, 'Westlands', -1.2680, 36.8100, 6.0),
('lrt_s3', 5, 240.0, 'Embakasi', -1.3100, 36.9000, 6.0);

-- SGR telemetry sample
INSERT INTO sgr_telemetry (segment_id, stress_level, speed_limit_kmh, ward, lat, lon, capacity) VALUES
('sgr_m1', 0.35, 120.0, 'Embakasi', -1.3150, 36.9200, 20.0),
('sgr_m2', 0.28, 120.0, 'Athi River', -1.3500, 36.9700, 20.0),
('sgr_m3', 0.42, 100.0, 'Syokimau', -1.3300, 36.9400, 20.0);

-- Airport telemetry sample
INSERT INTO airport_telemetry (runway_id, flight_rate, surface_condition, ward, lat, lon, capacity) VALUES
('jkia_06', 38.0, 'good', 'Embakasi', -1.3192, 36.9278, 45.0),
('jkia_24', 35.0, 'good', 'Embakasi', -1.3192, 36.9278, 45.0),
('jkia_03', 12.0, 'fair', 'Embakasi', -1.3192, 36.9278, 20.0);
