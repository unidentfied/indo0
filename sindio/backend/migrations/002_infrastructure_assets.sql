-- Sindio: Migration 002 — Infrastructure Assets table
-- Stores ingested water / power / road geometry for stress-test simulations.

CREATE TABLE IF NOT EXISTS infrastructure_assets (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    asset_type      VARCHAR(10) NOT NULL CHECK (asset_type IN ('water', 'power', 'roads', 'solid_waste', 'sidewalks', 'lrt', 'sgr', 'airports')),
    source_name     VARCHAR(255) NOT NULL,
    geometry        GEOMETRY(LINESTRING, 32737) NOT NULL,
    capacity_value  DOUBLE PRECISION,
    capacity_unit   VARCHAR(20) CHECK (capacity_unit IN ('L/s', 'kVA', 'veh/hr')),
    year_constructed INTEGER CHECK (year_constructed >= 1900 AND year_constructed <= 2100),
    last_maintenance DATE,
    ward_name       VARCHAR(255),
    source_hash     VARCHAR(64) NOT NULL,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Spatial index (EPSG:32737 bounding-box GiST)
CREATE INDEX IF NOT EXISTS idx_infra_assets_geom
    ON infrastructure_assets USING GIST (geometry);

-- Lookup index for idempotent upserts
CREATE UNIQUE INDEX IF NOT EXISTS uq_infra_assets_source
    ON infrastructure_assets (asset_type, source_name);
