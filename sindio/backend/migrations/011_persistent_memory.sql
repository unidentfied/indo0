-- Sindio: Migration 011 — Persistent Memory (short + long term)
-- ============================================================
-- Long-term memory (PostgreSQL):
--   simulation_memory  — stores simulation states, planner feedback,
--                        observed outcomes, and embedding vectors.
--   decision_memory    — stores planner actions + long-term outcomes.
--
-- Working memory (Redis, 7-day TTL):
--   Implemented in memory_service.py — current simulation state per
--   user and active agent workflow steps.
--
-- Memory retrieval:
--   FAISS-based vector search on simulation_memory.embedding is
--   performed by memory_service.py and injected into the agentic
--   workflow as historical precedents or warnings.

-- ------------------------------------------------------------------
-- 1. Simulation Memory (long-term, vector-indexed)
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS simulation_memory (
    id                         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    simulation_id              VARCHAR(64) NOT NULL,
    infrastructure_type        VARCHAR(20) NOT NULL
                                   CHECK (infrastructure_type IN (
                                       'water', 'power', 'roads', 'solid_waste',
                                       'sidewalks', 'lrt', 'sgr', 'airports'
                                   )),
    alert_id                   UUID,           -- REFERENCES alerts(id)
    ward                       VARCHAR(255) NOT NULL,
    embedding                  BYTEA NOT NULL, -- 1024-dim float32 numpy
    density_projection         JSONB DEFAULT '{}',
    planning_context           JSONB DEFAULT '{}',  -- alert + projection snapshot
    infrastructure_assets_affected TEXT[] DEFAULT '{}',
    recommendation             JSONB DEFAULT '{}',  -- the draft recommendation
    research_findings          JSONB DEFAULT '{}',  -- key data points
    planner_feedback           VARCHAR(20) DEFAULT 'none'
                                   CHECK (planner_feedback IN (
                                       'none', 'UPVOTE', 'DOWNVOTE'
                                   )),
    planner_comment            TEXT,
    feedback_given_by          VARCHAR(255),
    feedback_at                TIMESTAMPTZ,
    outcome_observed           VARCHAR(50)
                                   CHECK (outcome_observed IN (
                                       'breach_occurred', 'breach_averted',
                                       'upgrade_done', 'upgrade_scheduled',
                                       'no_change', 'deferred'
                                   )),
    outcome_months_later       INTEGER,        -- months after simulation
    outcome_notes              TEXT,
    tags                       TEXT[] DEFAULT '{}',
    created_at                 TIMESTAMPTZ DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sim_mem_type ON simulation_memory (infrastructure_type);
CREATE INDEX idx_sim_mem_ward ON simulation_memory (ward);
CREATE INDEX idx_sim_mem_feedback ON simulation_memory (planner_feedback);
CREATE INDEX idx_sim_mem_outcome ON simulation_memory (outcome_observed);
CREATE INDEX idx_sim_mem_created ON simulation_memory (created_at DESC);

-- Partial indexes for fast retrieval by feedback
CREATE INDEX idx_sim_mem_upvoted ON simulation_memory (created_at DESC)
    WHERE planner_feedback = 'UPVOTE';
CREATE INDEX idx_sim_mem_downvoted ON simulation_memory (created_at DESC)
    WHERE planner_feedback = 'DOWNVOTE';

-- ------------------------------------------------------------------
-- 2. Decision Memory (long-term outcomes)
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS decision_memory (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    alert_id             UUID,         -- REFERENCES alerts(id)
    planner_action_taken TEXT NOT NULL,
    simulation_memory_id UUID REFERENCES simulation_memory(id),
    asset_ids_affected   TEXT[] DEFAULT '{}',
    outcome_months_later INTEGER,
    outcome_description  TEXT,
    was_successful       BOOLEAN,
    cost_actual_kes      BIGINT,
    notes                TEXT,
    recorded_by          VARCHAR(255),
    recorded_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_dec_mem_alert ON decision_memory (alert_id);
CREATE INDEX idx_dec_mem_success ON decision_memory (was_successful);
CREATE INDEX idx_dec_mem_sim ON decision_memory (simulation_memory_id);

-- ------------------------------------------------------------------
-- 3. Feedback weight adjustment function
-- ------------------------------------------------------------------

CREATE OR REPLACE FUNCTION adjust_simulation_weight(
    p_simulation_id UUID,
    p_feedback VARCHAR,        -- 'UPVOTE' or 'DOWNVOTE'
    p_comment TEXT DEFAULT NULL,
    p_feedback_by VARCHAR DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE simulation_memory
    SET planner_feedback = p_feedback,
        planner_comment  = COALESCE(p_comment, planner_comment),
        feedback_given_by = COALESCE(p_feedback_by, feedback_given_by),
        feedback_at      = NOW(),
        updated_at       = NOW()
    WHERE id = p_simulation_id;
END;
$$ LANGUAGE plpgsql;

-- ------------------------------------------------------------------
-- 4. Seed — initial simulation memory entries for Nairobi wards
-- ------------------------------------------------------------------

INSERT INTO simulation_memory
    (simulation_id, infrastructure_type, ward, embedding,
     density_projection, planning_context, infrastructure_assets_affected,
     recommendation, planner_feedback, outcome_observed, tags)
VALUES
    ('sim-nov-2024-kilimani-water', 'water', 'Kilimani',
     '\x00000000'::BYTEA,   -- placeholder — replace with real embeddings
     '{"year":2028,"growth_rate":12.0}'::JSONB,
     '{}'::JSONB,
     ARRAY['WM-0133','WM-0145'],
     '{"action":"Upsize pipe to 300mm","timeline":"12 months","cost_range":"2-3M KES"}'::JSONB,
     'UPVOTE', 'upgrade_done',
     ARRAY['density_driven', 'water_stress', 'pipe_capacity']),
    ('sim-dec-2024-cbd-power', 'power', 'CBD',
     '\x00000000'::BYTEA,
     '{"year":2030,"growth_rate":14.0}'::JSONB,
     '{}'::JSONB,
     ARRAY['SUB-0071','SUB-0072'],
     '{"action":"Add transformer redundancy","timeline":"8 months","cost_range":"4-6M KES"}'::JSONB,
     'UPVOTE', 'breach_averted',
     ARRAY['density_driven', 'power_overload']),
    ('sim-feb-2025-upperhill-water', 'water', 'Upper Hill',
     '\x00000000'::BYTEA,
     '{"year":2029,"growth_rate":8.0}'::JSONB,
     '{}'::JSONB,
     ARRAY['WM-0201'],
     '{"action":"Reduce pressure zone — install PRV valve","timeline":"3 months","cost_range":"0.5-1M KES"}'::JSONB,
     'DOWNVOTE', 'breach_occurred',
     ARRAY['pressure_fluctuation', 'failed_itervention'])
ON CONFLICT DO NOTHING;
