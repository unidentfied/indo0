-- Sindio: Migration 012 — Playbook Executions
-- ============================================================
-- Tracks every playbook run for analytics: which playbooks are
-- most effective, step-level success rates, and fallback triggers.

CREATE TABLE IF NOT EXISTS playbook_executions (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    alert_id         TEXT NOT NULL,
    playbook_name    VARCHAR(255) NOT NULL,
    trigger_match    JSONB NOT NULL,        -- {infrastructure_type, classification, severity}
    steps_executed   JSONB NOT NULL,        -- [{action, status, duration_ms, output, error?}]
    steps_total      INTEGER NOT NULL,
    steps_succeeded  INTEGER NOT NULL DEFAULT 0,
    steps_failed     INTEGER NOT NULL DEFAULT 0,
    fallback_used    BOOLEAN NOT NULL DEFAULT FALSE,
    fallback_reason  TEXT,
    output_text      TEXT,                  -- rendered output_template
    top_recommendation JSONB,               -- the final recommendation
    executed_by      VARCHAR(255),
    duration_ms      INTEGER,
    status           VARCHAR(20) NOT NULL DEFAULT 'running'
                         CHECK (status IN ('running', 'completed', 'failed', 'fallback')),
    metadata         JSONB DEFAULT '{}',
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_pb_ex_alert ON playbook_executions (alert_id);
CREATE INDEX idx_pb_ex_name ON playbook_executions (playbook_name);
CREATE INDEX idx_pb_ex_status ON playbook_executions (status);
CREATE INDEX idx_pb_ex_created ON playbook_executions (created_at DESC);
