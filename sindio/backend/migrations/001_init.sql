-- Sindio: Initial database migration
-- Creates core tables for urban planning data, simulations, alerts, and users.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";
CREATE EXTENSION IF NOT EXISTS "timescaledb";

-- ============================================================
-- Users & Authentication
-- ============================================================
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    org_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Infrastructure Nodes (power, water, road)
-- ============================================================
CREATE TABLE infrastructure_nodes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    system_type VARCHAR(20) NOT NULL CHECK (system_type IN ('power', 'water', 'roads', 'solid_waste', 'sidewalks', 'lrt', 'sgr', 'airports')),
    node_name VARCHAR(255) NOT NULL,
    location GEOGRAPHY(POINT, 4326) NOT NULL,
    capacity DOUBLE PRECISION,
    current_load DOUBLE PRECISION,
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'degraded', 'offline')),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_infra_system ON infrastructure_nodes(system_type);
CREATE INDEX idx_infra_location ON infrastructure_nodes USING GIST(location);

-- ============================================================
-- Sensor Telemetry (timeseries)
-- ============================================================
CREATE TABLE sensor_telemetry (
    id BIGSERIAL PRIMARY KEY,
    node_id UUID REFERENCES infrastructure_nodes(id) ON DELETE CASCADE,
    metric_type VARCHAR(50) NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    unit VARCHAR(20) NOT NULL,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('sensor_telemetry', 'recorded_at');
CREATE INDEX idx_telemetry_node ON sensor_telemetry(node_id, recorded_at DESC);

-- ============================================================
-- Simulation Runs
-- ============================================================
CREATE TABLE simulations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_by UUID REFERENCES users(id),
    network_type VARCHAR(20) NOT NULL CHECK (network_type IN ('power', 'water', 'roads', 'solid_waste', 'sidewalks', 'lrt', 'sgr', 'airports')),
    stress_factor VARCHAR(255),
    failure_risk VARCHAR(10) NOT NULL CHECK (failure_risk IN ('low', 'medium', 'high')),
    status VARCHAR(20) DEFAULT 'running' CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    recommendation TEXT,
    result_payload JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_sim_status ON simulations(status);
CREATE INDEX idx_sim_created ON simulations(created_at DESC);

-- ============================================================
-- Alerts (temporally spaced)
-- ============================================================
CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    level VARCHAR(10) NOT NULL CHECK (level IN ('critical', 'warning', 'advisory')),
    category VARCHAR(20) NOT NULL CHECK (category IN ('electricity', 'water', 'roads', 'traffic', 'utilities')),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    location GEOGRAPHY(POINT, 4326),
    node_id UUID REFERENCES infrastructure_nodes(id),
    acknowledged BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_alerts_level ON alerts(level, created_at DESC);
CREATE INDEX idx_alerts_node ON alerts(node_id);

-- ============================================================
-- GIS Layers (vector features)
-- ============================================================
CREATE TABLE gis_layers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    layer_name VARCHAR(255) NOT NULL,
    feature_type VARCHAR(50) NOT NULL,
    geometry GEOMETRY(GEOMETRY, 4326),
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_gis_layer ON gis_layers(layer_name);
CREATE INDEX idx_gis_geom ON gis_layers USING GIST(geometry);

-- ============================================================
-- Model Inference Cache
-- ============================================================
CREATE TABLE inference_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_name VARCHAR(255) NOT NULL,
    input_hash VARCHAR(64) NOT NULL,
    output JSONB NOT NULL,
    confidence DOUBLE PRECISION,
    ttl_seconds INTEGER DEFAULT 3600,
    cached_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cache_lookup ON inference_cache(model_name, input_hash);
CREATE INDEX idx_cache_expiry ON inference_cache(cached_at + (ttl_seconds * INTERVAL '1 second'));

-- ============================================================
-- Seed: Central District infrastructure nodes
-- ============================================================
INSERT INTO infrastructure_nodes (system_type, node_name, location, capacity, current_load, status) VALUES
('power',   'Substation 4-A',  ST_GeogFromText('POINT(36.8219 -1.2921)'),  100.0, 85.3, 'active'),
('power',   'Substation 7-B',  ST_GeogFromText('POINT(36.8050 -1.2833)'),  100.0, 62.1, 'active'),
('water',   'Pump Station W-102', ST_GeogFromText('POINT(36.8150 -1.2980)'), 200.0, 128.0, 'degraded'),
('water',   'Reservoir Upper Hill', ST_GeogFromText('POINT(36.8120 -1.2900)'), 500.0, 410.0, 'active'),
('roads',   'A8 Junction Westlands', ST_GeogFromText('POINT(36.8090 -1.2670)'), 100.0, 88.0, 'active'),
('roads',   'Waiyaki Way Interchange', ST_GeogFromText('POINT(36.8020 -1.2700)'), 100.0, 74.0, 'active');
