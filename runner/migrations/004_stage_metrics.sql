-- 004_stage_metrics.sql — the table meta_loop's pipeline auto-tuner reads.
--
-- APPLIED 2026-08-25.
--
-- WHY IT IS NEEDED
--
-- runner/meta_loop.py reads `stage_metrics` in two places:
--
--   _stage_metrics_summary()      window_days = 30   (tuning baselines)
--   _plan_auto_tune_decisions()   window_days = 5    (cycle-time regressions)
--
-- and `grep -rn '"stage_metrics"' runner` finds those two reads and no INSERT
-- anywhere in the repository. The relation does not exist in the control plane
-- either (checked against information_schema on project eatfwdzfurujcuwlhdgj:
-- stage_metrics, pipeline_metrics and file_reservations are all absent).
--
-- So _stage_metrics_summary() returned {} on every call, the tuning loop under
-- it never entered, and the pipeline auto-tuner has never emitted a decision.
--
-- runner/improvement_measure.stage_metrics() is the producer, added in the same
-- commit as this file. With the table present it wrote 48 rows on its first real
-- run and meta_loop._stage_metrics_summary() went from {} to 46 (project, kind)
-- groups -- the auto-tuner has input for the first time. It stays fail-soft: if
-- the relation is ever absent it reports stage_metrics_written = 0 WITH the
-- error named, because "0 written, no errors" is also what a correct run over an
-- empty window looks like.
--
-- Applying this does NOT switch the auto-tuner on. ORCH_AUTO_TUNE_ENABLE
-- defaults false and is unset on this fleet, so meta_loop plans and records
-- decisions without applying them until an operator opts in.
--
-- SHAPE
--
-- One row per (project_id, kind, window_days). The producer recomputes and
-- upserts on every run, so the unique constraint is the identity of a
-- measurement window, not a history — history lives in the tasks and outcomes
-- rows the numbers are derived from.

CREATE TABLE IF NOT EXISTS stage_metrics (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id              uuid NOT NULL,
    kind                    text NOT NULL,
    window_days             integer NOT NULL,

    avg_cycle_time_seconds  double precision NOT NULL DEFAULT 0,
    first_try_yield_pct     double precision NOT NULL DEFAULT 0,
    sample_count            integer NOT NULL DEFAULT 0,

    computed_at             timestamptz NOT NULL DEFAULT now(),

    -- The upsert target. Without this, every producer run appends a new row and
    -- the consumer's `rows[0]` becomes "whichever PostgREST returned first",
    -- which is how a tuning decision comes to depend on row order.
    CONSTRAINT stage_metrics_window_uniq UNIQUE (project_id, kind, window_days),

    -- The consumer divides by these and compares them against thresholds; a
    -- negative or out-of-range value would produce a tuning decision from
    -- nonsense rather than a refusal.
    CONSTRAINT stage_metrics_window_days_positive CHECK (window_days > 0),
    CONSTRAINT stage_metrics_cycle_time_nonneg CHECK (avg_cycle_time_seconds >= 0),
    CONSTRAINT stage_metrics_sample_count_nonneg CHECK (sample_count >= 0),
    CONSTRAINT stage_metrics_yield_is_a_percentage
        CHECK (first_try_yield_pct >= 0 AND first_try_yield_pct <= 100)
);

-- Both consumer queries filter on (project_id, kind, window_days); the unique
-- constraint's index already serves them, so no second index is created here.

-- RLS on with no policies: the service role bypasses RLS, and every reader and
-- writer of this table is the service role. Anything else gets nothing, which
-- is the correct default for a table that has never been exposed.
ALTER TABLE stage_metrics ENABLE ROW LEVEL SECURITY;
