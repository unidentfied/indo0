-- ============================================================
-- Migration: Create feedback table for persistent field operator submissions
-- ============================================================
-- Replaces the in-memory _FEEDBACK_STORE list in backend/app/routers/feedback.py

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id VARCHAR(32) PRIMARY KEY,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    submitted_by VARCHAR(128) NOT NULL DEFAULT 'unknown',
    user_role VARCHAR(32) NOT NULL DEFAULT 'unknown',
    status VARCHAR(16) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    asset_id VARCHAR(64) NOT NULL,
    infrastructure_type VARCHAR(32) NOT NULL,
    ward VARCHAR(64) NOT NULL,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    feedback_type VARCHAR(32) NOT NULL CHECK (feedback_type IN ('incorrect_prediction', 'ground_truth', 'asset_condition', 'maintenance_needed')),
    severity VARCHAR(16) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    description TEXT NOT NULL,
    observed_value DOUBLE PRECISION,
    expected_value DOUBLE PRECISION,
    photo_url TEXT,
    operator_name VARCHAR(128),
    operator_contact VARCHAR(128),
    resolved_at TIMESTAMPTZ,
    resolved_by VARCHAR(128),
    resolution_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status);
CREATE INDEX IF NOT EXISTS idx_feedback_infra_type ON feedback(infrastructure_type);
CREATE INDEX IF NOT EXISTS idx_feedback_submitted_at ON feedback(submitted_at DESC);
