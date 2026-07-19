-- Cross-portfolio compounding A/B test framework schema.
--
-- Fills the gap: experiment_portfolio.py and auto_experiment.py insert into
-- "experiments" but no migration created the table.  This migration creates
-- the canonical experiments table plus new cross-portfolio-specific tables
-- that let the orchestrator measure whether learnings from one project
-- compound into measurable wins across other projects.

-- ============================================================
-- 1. experiments  (materialises the table code already writes to)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.experiments (
  id            text PRIMARY KEY,
  title         text,
  project       text,                       -- originating project or 'orchestrator'
  category      text,                       -- metric family: success_rate | cost_per_task | latency
  status        text DEFAULT 'active',      -- active | monitoring | graduated | discarded
  control_value text,
  candidate_value text,
  hypothesis    text,
  fleet_allocation_pct numeric DEFAULT 2,
  knob          text,                       -- env knob name (auto_experiment compat)
  current_value text,                       -- auto_experiment compat
  verdict       text,                       -- adopt | reject | no_knob | no_evals | inconclusive
  detail        text,
  note          text,
  approval_filed boolean DEFAULT false,
  created_at    timestamptz DEFAULT now(),
  updated_at    timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS experiments_status_idx
  ON public.experiments(status);
CREATE INDEX IF NOT EXISTS experiments_project_idx
  ON public.experiments(project);

-- ============================================================
-- 2. cross_portfolio_ab_tests
--    Each row is one cross-portfolio compounding experiment:
--    "Does a winning change in project A also lift project B?"
-- ============================================================
CREATE TABLE IF NOT EXISTS public.cross_portfolio_ab_tests (
  id              text PRIMARY KEY,
  source_experiment_id text REFERENCES public.experiments(id),
  source_project  text NOT NULL,             -- project where the win was first observed
  target_projects text[] NOT NULL DEFAULT '{}', -- projects where the change is being tested
  change_type     text NOT NULL,             -- model_choice | timeout | concurrency | context_size | prompt_template
  control_desc    text,                      -- what control arm uses
  candidate_desc  text,                      -- what candidate arm uses
  hypothesis      text,
  status          text DEFAULT 'pending',    -- pending | active | graduated | discarded | rolled_back
  fleet_pct       numeric DEFAULT 2,         -- % of fleet allocated to this test
  min_sample_size int DEFAULT 20,            -- per-project minimum before stat test
  cost_tolerance  numeric DEFAULT 1.10,      -- candidate can cost up to 10% more
  win_threshold   numeric DEFAULT 0.95,      -- candidate must be >= 95% of control
  rollback_threshold numeric DEFAULT 0.90,   -- below 90% triggers rollback
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS xpab_status_idx
  ON public.cross_portfolio_ab_tests(status);
CREATE INDEX IF NOT EXISTS xpab_source_project_idx
  ON public.cross_portfolio_ab_tests(source_project);

-- ============================================================
-- 3. cross_portfolio_ab_results
--    Per-project, per-variant outcome aggregates for each test.
-- ============================================================
CREATE TABLE IF NOT EXISTS public.cross_portfolio_ab_results (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ab_test_id      text NOT NULL REFERENCES public.cross_portfolio_ab_tests(id),
  project         text NOT NULL,             -- which target project this row covers
  variant         text NOT NULL CHECK (variant IN ('control', 'candidate')),
  sample_size     int DEFAULT 0,
  pass_count      int DEFAULT 0,
  fail_count      int DEFAULT 0,
  total_cost_usd  numeric DEFAULT 0,
  avg_latency_s   numeric DEFAULT 0,
  pass_rate       numeric GENERATED ALWAYS AS (
                    CASE WHEN sample_size > 0
                         THEN round(pass_count::numeric / sample_size, 4)
                         ELSE 0 END
                  ) STORED,
  avg_cost_usd    numeric GENERATED ALWAYS AS (
                    CASE WHEN sample_size > 0
                         THEN round(total_cost_usd / sample_size, 6)
                         ELSE 0 END
                  ) STORED,
  verdict         text,                      -- winning | losing | inconclusive | graduated | rolled_back
  updated_at      timestamptz DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS xpab_results_test_project_variant
  ON public.cross_portfolio_ab_results(ab_test_id, project, variant);

-- ============================================================
-- 4. compounding_edges
--    Records when a graduated experiment compounds across projects.
--    Links to intent_graph_edges for provenance.
-- ============================================================
CREATE TABLE IF NOT EXISTS public.compounding_edges (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ab_test_id          text REFERENCES public.cross_portfolio_ab_tests(id),
  source_project      text NOT NULL,
  target_project      text NOT NULL,
  intent_signature    text,                  -- join key to intent_graph_edges
  lift_pass_rate      numeric,               -- delta in pass rate (candidate - control)
  lift_cost_pct       numeric,               -- cost change % (negative = savings)
  lift_latency_pct    numeric,               -- latency change % (negative = faster)
  compounding_score   numeric,               -- composite score: weighted sum of lifts
  graduated_at        timestamptz,
  created_at          timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS compounding_edges_source_idx
  ON public.compounding_edges(source_project, target_project);
CREATE INDEX IF NOT EXISTS compounding_edges_intent_idx
  ON public.compounding_edges(intent_signature);

-- Add experiment_id and experiment_variant to outcomes so
-- experiment_portfolio.evaluate_experiment() queries work.
ALTER TABLE public.outcomes
  ADD COLUMN IF NOT EXISTS experiment_id text,
  ADD COLUMN IF NOT EXISTS experiment_variant text;

CREATE INDEX IF NOT EXISTS outcomes_experiment_idx
  ON public.outcomes(experiment_id)
  WHERE experiment_id IS NOT NULL;
