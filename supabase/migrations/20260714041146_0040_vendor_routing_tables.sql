
-- 0040_vendor_routing_tables.sql
-- Tables for multi-vendor routing telemetry, shadow comparison, and capability tracking.

-- 1. routing_decisions — every routing choice logged
CREATE TABLE IF NOT EXISTS routing_decisions (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   timestamptz NOT NULL DEFAULT now(),
    task_id      text,
    task_kind    text,
    difficulty   text,
    tier         text NOT NULL,          -- sub | api | speculative
    provider     text NOT NULL,
    model        text NOT NULL,
    coder        text,
    reason       text,
    est_cost_usd numeric(10,6) DEFAULT 0,
    actual_cost  numeric(10,6),
    latency_ms   integer,
    success      boolean,
    error_class  text,
    metadata     jsonb DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_rd_created ON routing_decisions (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rd_provider ON routing_decisions (provider, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rd_tier ON routing_decisions (tier, created_at DESC);

-- 2. shadow_comparisons — primary vs shadow result pairs
CREATE TABLE IF NOT EXISTS shadow_comparisons (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at     timestamptz NOT NULL DEFAULT now(),
    task_id        text NOT NULL,
    primary_provider   text NOT NULL,
    primary_model      text NOT NULL,
    primary_cost_usd   numeric(10,6),
    primary_latency_ms integer,
    primary_success    boolean,
    shadow_provider    text NOT NULL,
    shadow_model       text NOT NULL,
    shadow_cost_usd    numeric(10,6),
    shadow_latency_ms  integer,
    shadow_success     boolean,
    quality_delta      numeric(5,2),     -- shadow minus primary quality score
    cost_savings_usd   numeric(10,6),    -- how much cheaper shadow was
    winner             text,             -- primary | shadow | tie
    metadata           jsonb DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sc_created ON shadow_comparisons (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sc_winner ON shadow_comparisons (winner, created_at DESC);

-- 3. skill_outcomes — Cowork skill execution records
CREATE TABLE IF NOT EXISTS skill_outcomes (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   timestamptz NOT NULL DEFAULT now(),
    task_id      text,
    skill_type   text NOT NULL,          -- browser | document | visual_verify | data_extract
    provider     text NOT NULL DEFAULT 'claude',
    model        text NOT NULL,
    success      boolean,
    duration_ms  integer,
    cost_usd     numeric(10,6),
    error_class  text,
    metadata     jsonb DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_so_skill ON skill_outcomes (skill_type, created_at DESC);

-- 4. creative_spend — creative AI budget tracking
CREATE TABLE IF NOT EXISTS creative_spend (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   timestamptz NOT NULL DEFAULT now(),
    provider     text NOT NULL,          -- bfl | ideogram | elevenlabs | kling | meshy
    model        text,
    operation    text,                   -- image_gen | voice_gen | video_gen | 3d_gen
    cost_usd     numeric(10,6) NOT NULL,
    success      boolean DEFAULT true,
    asset_url    text,
    metadata     jsonb DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_cs_provider ON creative_spend (provider, created_at DESC);

-- 5. vendor_capabilities — capability matrix snapshot for dashboarding
CREATE TABLE IF NOT EXISTS vendor_capabilities (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    vendor          text NOT NULL,
    model           text NOT NULL,
    capability      text NOT NULL,
    score           numeric(3,2) DEFAULT 1.0,   -- 0-1 capability strength
    context_window  integer,
    cost_in         numeric(10,4),               -- $/1M tok input
    cost_out        numeric(10,4),               -- $/1M tok output
    tier            text,                        -- fast | mid | heavy | frontier
    metadata        jsonb DEFAULT '{}'::jsonb,
    UNIQUE (vendor, model, capability)
);

CREATE INDEX IF NOT EXISTS idx_vc_vendor ON vendor_capabilities (vendor);
CREATE INDEX IF NOT EXISTS idx_vc_capability ON vendor_capabilities (capability);

-- RLS: enable but allow service role full access
ALTER TABLE routing_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE shadow_comparisons ENABLE ROW LEVEL SECURITY;
ALTER TABLE skill_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE creative_spend ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendor_capabilities ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON routing_decisions FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON shadow_comparisons FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON skill_outcomes FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON creative_spend FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON vendor_capabilities FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Authenticated users can read routing telemetry (for dashboard)
CREATE POLICY "authed_read" ON routing_decisions FOR SELECT TO authenticated USING (true);
CREATE POLICY "authed_read" ON shadow_comparisons FOR SELECT TO authenticated USING (true);
CREATE POLICY "authed_read" ON skill_outcomes FOR SELECT TO authenticated USING (true);
CREATE POLICY "authed_read" ON creative_spend FOR SELECT TO authenticated USING (true);
CREATE POLICY "authed_read" ON vendor_capabilities FOR SELECT TO authenticated USING (true);
;
