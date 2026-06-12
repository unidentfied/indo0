-- Sindio: Migration — Alert Explanations table
-- Stores RAG-generated natural-language explanations for alerts.
-- Linked to alerts table via alert_id foreign key.

CREATE TABLE IF NOT EXISTS alert_explanations (
    alert_id            UUID NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    explanation_text    TEXT NOT NULL,
    historical_alerts   JSONB DEFAULT '[]',
    planning_references JSONB DEFAULT '[]',
    maintenance_context TEXT,
    llm_model           VARCHAR(50),
    generated_at        TIMESTAMPTZ DEFAULT NOW(),
    cached_until        TIMESTAMPTZ,

    PRIMARY KEY (alert_id, generated_at)
);

CREATE INDEX IF NOT EXISTS idx_explanations_alert
    ON alert_explanations (alert_id, generated_at DESC);
