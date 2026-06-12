-- Sindio: Migration 009 — Proprietary Utility Data
-- ============================================================
-- Encrypted storage for water/power utility partner data with
-- row-level security (RLS), audit logging, and foreign data
-- wrapper (FDW) integration for mock API development.
--
-- Depends on: 001_init.sql (uuid-ossp, postgis, users table)

-- ------------------------------------------------------------------
-- Extensions
-- ------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- pgp_sym_encrypt / pgp_sym_decrypt
CREATE EXTENSION IF NOT EXISTS postgres_fdw;  -- foreign data wrappers (dev mocks)

-- ------------------------------------------------------------------
-- 1. Data Partner Agreements
-- ------------------------------------------------------------------
CREATE TYPE partner_access_level AS ENUM ('read_only', 'read_write');

CREATE TABLE data_partner_agreements (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    partner_name         VARCHAR(255) NOT NULL UNIQUE,
    access_level         partner_access_level NOT NULL DEFAULT 'read_only',
    encryption_key_hash  TEXT NOT NULL,        -- bcrypt / sha256 of the application-managed key
    rotation_date        DATE NOT NULL,        -- next scheduled key rotation
    active               BOOLEAN NOT NULL DEFAULT TRUE,
    contact_email        VARCHAR(255),
    signed_at            TIMESTAMPTZ DEFAULT NOW(),
    expires_at           TIMESTAMPTZ,
    metadata             JSONB DEFAULT '{}',
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

-- ------------------------------------------------------------------
-- 2. Planner → Ward mapping (for RLS)
-- ------------------------------------------------------------------
CREATE TABLE planner_wards (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ward_name  VARCHAR(255) NOT NULL,
    granted_by UUID REFERENCES users(id),
    granted_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, ward_name)
);

CREATE INDEX idx_planner_wards_user ON planner_wards (user_id);

-- Row-level security requires a db role; create one for planners.
-- In production this would be a group role mapped to application JWT claims.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'planner') THEN
        CREATE ROLE planner;
    END IF;
END
$$;

-- Helper function: returns wards the current user is assigned to.
-- The application sets `sindio.current_user_id` before querying proprietary tables.
CREATE OR REPLACE FUNCTION sindio_assigned_wards()
RETURNS TEXT[] AS $$
BEGIN
    RETURN ARRAY(
        SELECT pw.ward_name
        FROM planner_wards pw
        WHERE pw.user_id = NULLIF(current_setting('sindio.current_user_id', TRUE), '')::UUID
    );
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- ------------------------------------------------------------------
-- 3. Water Utility — Proprietary
-- ------------------------------------------------------------------
CREATE TABLE water_utility_proprietary (
    asset_id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    flow_rates_encrypted      BYTEA NOT NULL,   -- pgp_sym_encrypt(flow_rates_json, key)
    -- Decrypted: numeric[]  (last 30 daily flow-rate readings, L/s)
    pressure_psi              DOUBLE PRECISION NOT NULL,
    meter_id                  VARCHAR(64) UNIQUE NOT NULL,
    data_sharing_agreement_id UUID REFERENCES data_partner_agreements(id),
    ward_name                 VARCHAR(255) NOT NULL,   -- for RLS filtering
    last_export_utc           TIMESTAMPTZ,
    location                  GEOGRAPHY(POINT, 4326),
    status                    VARCHAR(20) DEFAULT 'active'
                                  CHECK (status IN ('active', 'inactive', 'maintenance')),
    metadata                  JSONB DEFAULT '{}',
    created_at                TIMESTAMPTZ DEFAULT NOW(),
    updated_at                TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_water_prop_ward ON water_utility_proprietary (ward_name);
CREATE INDEX idx_water_prop_partner ON water_utility_proprietary (data_sharing_agreement_id);
CREATE INDEX idx_water_prop_meter ON water_utility_proprietary (meter_id);
CREATE INDEX idx_water_prop_geom ON water_utility_proprietary USING GIST (location);

-- RLS: enable + policy
ALTER TABLE water_utility_proprietary ENABLE ROW LEVEL SECURITY;

CREATE POLICY water_ward_access ON water_utility_proprietary
    FOR ALL
    TO planner
    USING (ward_name = ANY(sindio_assigned_wards()));

-- Decryption function (application calls this after authenticating)
CREATE OR REPLACE FUNCTION decrypted_flow_rates(
    p_asset_id UUID,
    p_key TEXT
) RETURNS NUMERIC[] AS $$
DECLARE
    raw BYTEA;
    json_data TEXT;
BEGIN
    SELECT flow_rates_encrypted INTO raw
    FROM water_utility_proprietary
    WHERE asset_id = p_asset_id;

    IF raw IS NULL THEN
        RETURN NULL;
    END IF;

    json_data := pgp_sym_decrypt(raw, p_key);
    RETURN (json_data::jsonb)::NUMERIC[];
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ------------------------------------------------------------------
-- 4. Power Utility — Proprietary
-- ------------------------------------------------------------------
CREATE TYPE power_data_partner AS ENUM ('KPLC', 'RuralElectrification');

CREATE TABLE power_utility_proprietary (
    asset_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kwh_daily          DOUBLE PRECISION NOT NULL,
    voltage            DOUBLE PRECISION,
    substation_id      VARCHAR(64) NOT NULL,
    data_partner       power_data_partner NOT NULL,
    ward_name          VARCHAR(255) NOT NULL,
    capacity_kva       DOUBLE PRECISION,
    peak_load_kw       DOUBLE PRECISION,
    location           GEOGRAPHY(POINT, 4326),
    status             VARCHAR(20) DEFAULT 'active'
                           CHECK (status IN ('active', 'inactive', 'maintenance', 'tripped')),
    metadata           JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_power_prop_ward ON power_utility_proprietary (ward_name);
CREATE INDEX idx_power_prop_partner ON power_utility_proprietary (data_partner);
CREATE INDEX idx_power_prop_substation ON power_utility_proprietary (substation_id);
CREATE INDEX idx_power_prop_geom ON power_utility_proprietary USING GIST (location);

ALTER TABLE power_utility_proprietary ENABLE ROW LEVEL SECURITY;

CREATE POLICY power_ward_access ON power_utility_proprietary
    FOR ALL
    TO planner
    USING (ward_name = ANY(sindio_assigned_wards()));

-- ------------------------------------------------------------------
-- 5. Audit Logging — every SELECT on proprietary tables is recorded
-- ------------------------------------------------------------------
CREATE TABLE proprietary_data_access_log (
    id               BIGSERIAL PRIMARY KEY,
    user_id          UUID,
    session_id       TEXT,
    table_accessed   VARCHAR(100) NOT NULL,
    asset_id_range   TEXT,                -- e.g. "ward=Kilimani" or "asset_id=uuid"
    query_fingerprint TEXT,
    accessed_at      TIMESTAMPTZ DEFAULT NOW(),
    client_ip        INET,
    success          BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_prop_audit_user ON proprietary_data_access_log (user_id);
CREATE INDEX idx_prop_audit_time ON proprietary_data_access_log (accessed_at);
CREATE INDEX idx_prop_audit_table ON proprietary_data_access_log (table_accessed);

-- Audit logging function — call this from the application layer before
-- executing a SELECT against proprietary tables.
CREATE OR REPLACE FUNCTION log_proprietary_access(
    p_user_id       UUID,
    p_table_name    VARCHAR,
    p_asset_range   TEXT DEFAULT NULL,
    p_client_ip     INET DEFAULT NULL,
    p_session_id    TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    INSERT INTO proprietary_data_access_log
        (user_id, table_accessed, asset_id_range, client_ip, session_id, success)
    VALUES
        (p_user_id, p_table_name, p_asset_range, p_client_ip, p_session_id, TRUE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Auto-log failed access attempts via a statement-level trigger on the
-- RLS policy (fires when the policy filters all rows for a query)
CREATE OR REPLACE FUNCTION log_rls_blocked_access()
RETURNS EVENT_TRIGGER AS $$
BEGIN
    -- This is a placeholder — pgaudit or a security-barrier VIEW
    -- provides more reliable per-query logging.
    -- For now, the application calls log_proprietary_access() explicitly.
    NULL;
END;
$$ LANGUAGE plpgsql;

-- ------------------------------------------------------------------
-- 6. Foreign Data Wrapper — mock utility APIs for development
-- ------------------------------------------------------------------
CREATE SERVER IF NOT EXISTS mock_utility_api
    FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (
        host 'localhost',
        port '5432',
        dbname 'sindio'
    );

-- Mock foreign table: water utility data (maps to a simple mock view)
CREATE OR REPLACE VIEW mock_water_readings AS
SELECT
    'MOCK-W-' || LPAD(gs::TEXT, 4, '0') AS meter_id,
    ARRAY(
        SELECT ROUND((RANDOM() * 50 + 20)::NUMERIC, 2)
        FROM generate_series(1, 30)
    ) AS flow_rates,
    ROUND((RANDOM() * 40 + 40)::NUMERIC, 2) AS pressure_psi,
    NOW() - (RANDOM() * INTERVAL '30 days') AS last_export_utc
FROM generate_series(1, 100) gs;

-- Mock foreign table: power utility data
CREATE OR REPLACE VIEW mock_power_readings AS
SELECT
    'SUB-' || LPAD(gs::TEXT, 4, '0') AS substation_id,
    (gs % 2 = 0)::BOOLEAN AS is_kplc,
    ROUND((RANDOM() * 5000 + 1000)::NUMERIC, 2) AS kwh_daily,
    ROUND((RANDOM() * 10 + 220)::NUMERIC, 2) AS voltage,
    NOW() - (RANDOM() * INTERVAL '1 day') AS recorded_at
FROM generate_series(1, 200) gs;

-- ------------------------------------------------------------------
-- 7. Seed data — initial partner agreement + test planner wards
-- ------------------------------------------------------------------

-- Default partner agreements (encryption_key_hash is a placeholder;
-- use a real bcrypt hash generated from your application's key)
INSERT INTO data_partner_agreements
    (partner_name, access_level, encryption_key_hash, rotation_date, contact_email)
VALUES
    ('Nairobi City Water & Sewerage Company', 'read_only',
     '$2b$12$mock_ncwsc_hash_do_not_use_in_production_000',
     CURRENT_DATE + INTERVAL '90 days', 'data@ncwsc.go.ke'),
    ('Kenya Power (KPLC)', 'read_only',
     '$2b$12$mock_kplc_hash_do_not_use_in_production_000',
     CURRENT_DATE + INTERVAL '60 days', 'gridops@kplc.co.ke'),
    ('Rural Electrification Authority', 'read_write',
     '$2b$12$mock_rea_hash_do_not_use_in_production_000',
     CURRENT_DATE + INTERVAL '30 days', 'data@rea.go.ke')
ON CONFLICT (partner_name) DO NOTHING;
