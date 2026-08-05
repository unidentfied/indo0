-- Migration 017: Carbon Credits & Parametric Insurance tables

CREATE TABLE IF NOT EXISTS carbon_baselines (
    id SERIAL PRIMARY KEY,
    city_slug VARCHAR(64) NOT NULL,
    infra_type VARCHAR(64) NOT NULL,
    asset_id VARCHAR(128) NOT NULL,
    baseline_tco2e_per_year DOUBLE PRECISION NOT NULL,
    energy_consumption_mwh DOUBLE PRECISION DEFAULT 0.0,
    emission_factor DOUBLE PRECISION DEFAULT 0.0,
    calculation_method VARCHAR(64) DEFAULT 'iso_14064',
    data_sources JSON DEFAULT '[]',
    calculated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_carbon_baselines_city ON carbon_baselines(city_slug);
CREATE INDEX IF NOT EXISTS idx_carbon_baselines_type ON carbon_baselines(infra_type);

CREATE TABLE IF NOT EXISTS carbon_credits (
    id SERIAL PRIMARY KEY,
    city_slug VARCHAR(64) NOT NULL,
    infra_type VARCHAR(64) NOT NULL,
    asset_id VARCHAR(128) NOT NULL,
    credit_id VARCHAR(64) NOT NULL UNIQUE,
    tco2e_saved DOUBLE PRECISION NOT NULL,
    upgrade_description VARCHAR(512) DEFAULT '',
    upgrade_date TIMESTAMPTZ NOT NULL,
    verification_status VARCHAR(32) DEFAULT 'pending',
    verification_body VARCHAR(128) DEFAULT '',
    certificate_hash VARCHAR(128) DEFAULT '',
    market_price_per_tco2e DOUBLE PRECISION DEFAULT 0.0,
    total_value_usd DOUBLE PRECISION DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    verified_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    metadata_json JSON DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_carbon_credits_city ON carbon_credits(city_slug);
CREATE INDEX IF NOT EXISTS idx_carbon_credits_type ON carbon_credits(infra_type);

CREATE TABLE IF NOT EXISTS insurance_policies (
    id SERIAL PRIMARY KEY,
    city_slug VARCHAR(64) NOT NULL,
    policy_id VARCHAR(64) NOT NULL UNIQUE,
    provider_name VARCHAR(128) DEFAULT 'Sindio Parametric',
    policy_type VARCHAR(32) NOT NULL DEFAULT 'parametric',
    infra_type VARCHAR(64) NOT NULL,
    insured_asset_id VARCHAR(128) NOT NULL,
    coverage_amount_usd DOUBLE PRECISION DEFAULT 0.0,
    premium_usd DOUBLE PRECISION DEFAULT 0.0,
    trigger_stress_threshold DOUBLE PRECISION DEFAULT 0.80,
    trigger_window_hours INTEGER DEFAULT 24,
    payout_percent DOUBLE PRECISION DEFAULT 1.0,
    status VARCHAR(32) DEFAULT 'active',
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    metadata_json JSON DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_insurance_policies_city ON insurance_policies(city_slug);
CREATE INDEX IF NOT EXISTS idx_insurance_policies_type ON insurance_policies(infra_type);
CREATE INDEX IF NOT EXISTS idx_insurance_policies_asset ON insurance_policies(insured_asset_id);

CREATE TABLE IF NOT EXISTS risk_assessments (
    id SERIAL PRIMARY KEY,
    city_slug VARCHAR(64) NOT NULL,
    asset_id VARCHAR(128) NOT NULL,
    infra_type VARCHAR(64) NOT NULL,
    risk_score DOUBLE PRECISION NOT NULL,
    failure_probability_1yr DOUBLE PRECISION DEFAULT 0.0,
    expected_annual_loss_usd DOUBLE PRECISION DEFAULT 0.0,
    max_foreseeable_loss_usd DOUBLE PRECISION DEFAULT 0.0,
    hazard_factors JSON DEFAULT '[]',
    vulnerability_factors JSON DEFAULT '[]',
    exposure_factors JSON DEFAULT '[]',
    assessed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_risk_assessments_city ON risk_assessments(city_slug);
CREATE INDEX IF NOT EXISTS idx_risk_assessments_asset ON risk_assessments(asset_id);
CREATE INDEX IF NOT EXISTS idx_risk_assessments_type ON risk_assessments(infra_type);

CREATE TABLE IF NOT EXISTS claim_events (
    id SERIAL PRIMARY KEY,
    city_slug VARCHAR(64) NOT NULL,
    policy_id VARCHAR(64) NOT NULL,
    claim_id VARCHAR(64) NOT NULL UNIQUE,
    trigger_stress_value DOUBLE PRECISION NOT NULL,
    trigger_timestamp TIMESTAMPTZ NOT NULL,
    payout_amount_usd DOUBLE PRECISION DEFAULT 0.0,
    status VARCHAR(32) DEFAULT 'pending',
    verified_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    metadata_json JSON DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_claim_events_city ON claim_events(city_slug);
CREATE INDEX IF NOT EXISTS idx_claim_events_policy ON claim_events(policy_id);
