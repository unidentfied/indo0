-- Sindio: Migration 010 — Agent Traces
-- ============================================================
-- Persists every run of the LangGraph agentic recommendation
-- engine for debugging, audit, and human-feedback tracking.

CREATE TABLE IF NOT EXISTS agent_traces (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    alert_id         UUID,                   -- REFERENCES alerts(id)
    run_id           TEXT NOT NULL,          -- unique per agent execution
    node_name        VARCHAR(50) NOT NULL,   -- planner | researcher | verifier | drafter | human_review
    state_snapshot   JSONB NOT NULL,         -- full SindioAgentState at node entry
    output           JSONB,                  -- node-specific output
    duration_ms      INTEGER,               -- wall-clock time spent in node
    status           VARCHAR(20) NOT NULL DEFAULT 'running'
                         CHECK (status IN ('running', 'completed', 'failed', 'timed_out')),
    error_message    TEXT,
    human_feedback   JSONB,                  -- { approved: bool, edited_draft: dict, comment: text }
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_agent_run ON agent_traces (run_id);
CREATE INDEX idx_agent_node ON agent_traces (run_id, node_name);
CREATE INDEX idx_agent_alert ON agent_traces (alert_id);

COMMENT ON TABLE agent_traces IS 'Debug traces for LangGraph agentic recommendation runs.';
