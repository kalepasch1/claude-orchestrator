-- 005_pipeline_metrics.sql — the table runner/pipeline_metrics.py writes.
--
-- APPLIED 2026-08-25.
--
-- WHY IT WAS MISSING
--
-- pipeline_metrics.record() has been called on every merge-train pass since the
-- module was written, and pipeline_metrics.get_health() aggregates what it
-- writes. The relation did not exist, and both functions were
-- `except Exception: pass` -- so every insert failed, every read returned
-- nothing, and neither said so. Checked against information_schema on project
-- eatfwdzfurujcuwlhdgj: pipeline_metrics, stage_metrics and file_reservations
-- were all absent.
--
-- Two separate defects kept that invisible for months:
--
--   1. merge_train dropped the `summary["test_pipeline"] = _pm.get_health(...)`
--      line in a merge (it was added in 85f4aa95), so get_health() had no caller
--      anywhere in the repository while record() kept firing. Restored earlier
--      in this cleanup.
--   2. Both handlers swallowed the failure silently. They now log a warning
--      naming what was lost -- the slug and task_type for a failed insert, the
--      window and filter for a failed read.
--
-- With the table present, record() lands and get_health() aggregates; verified
-- by a live round trip (write -> read -> aggregate -> clean up).
--
-- SHAPE
--
-- Append-only, one row per test-pipeline run. There is no natural key -- the
-- same slug legitimately runs many times -- so there is no unique constraint and
-- nothing upserts here.

CREATE TABLE IF NOT EXISTS public.pipeline_metrics (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug           text NOT NULL DEFAULT '',
    task_type      text NOT NULL DEFAULT 'unknown',
    passed         boolean NOT NULL DEFAULT false,
    duration_ms    integer NOT NULL DEFAULT 0,
    gate_decision  text NOT NULL DEFAULT '',
    gate_reason    text NOT NULL DEFAULT '',
    recorded_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT pipeline_metrics_duration_nonneg CHECK (duration_ms >= 0)
);

-- get_health() filters recorded_at >= cutoff and orders by recorded_at desc.
CREATE INDEX IF NOT EXISTS pipeline_metrics_recorded_at_idx
    ON public.pipeline_metrics (recorded_at DESC);
-- ...and optionally narrows by task_type.
CREATE INDEX IF NOT EXISTS pipeline_metrics_task_type_recorded_at_idx
    ON public.pipeline_metrics (task_type, recorded_at DESC);

-- Service-role only, like the other runner-owned tables. RLS on with no
-- policies: SUPABASE_SERVICE_KEY bypasses RLS, everything else gets nothing.
ALTER TABLE public.pipeline_metrics ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.pipeline_metrics IS
    'One row per test-pipeline run: duration, pass/fail and gate decision by task '
    'type. Written by runner/pipeline_metrics.record(); aggregated by get_health(), '
    'which merge_train puts in its run summary under "test_pipeline". Append-only; '
    'no natural key, so no unique constraint.';
