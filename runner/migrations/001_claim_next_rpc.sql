-- Migration: claim_next(runner_id, runnable_projects)
-- Encodes the same ordering semantics as db.py claim_task into a single
-- Postgres function that selects ONE task FOR UPDATE SKIP LOCKED, sets
-- state=RUNNING+runner atomically, and returns the row.
--
-- Feature flag: ORCH_CLAIM_RPC (fleet_config), default false.
-- Enable via fleet_config after one observed clean day.
--
-- Ordering tiers (mirrors the Python sort tuple in db.claim_task):
--   1. release-fix tasks first (qafix-/relfix-/buildfix-/deployfix-)
--   2. recovery tasks (recover-missing-branch / slug starts with 'recover-')
--   3. rework tasks (rework-*)
--   4. improvement tasks (improve-*)
--   5. kind weight: bugfix=0, test=1, cleanup/chore=2, docs=3, build=4, etc.
--   6. confidence DESC (higher confidence claimed first)
--   7. portfolio project rank (projects.priority ASC)
--   8. ROI weight (projects.concurrency_weight DESC)
--   9. created_at ASC (FIFO within same tier)

CREATE OR REPLACE FUNCTION claim_next(
  p_runner_id text,
  p_runnable_projects uuid[] DEFAULT NULL
)
RETURNS SETOF tasks
LANGUAGE plpgsql
AS $$
DECLARE
  v_task tasks%ROWTYPE;
BEGIN
  -- Select one candidate, applying the multi-tier ordering.
  -- FOR UPDATE SKIP LOCKED ensures two runners never double-claim.
  SELECT t.* INTO v_task
  FROM tasks t
  LEFT JOIN projects p ON p.id = t.project_id
  WHERE t.state = 'QUEUED'
    AND t.kind NOT IN ('speculative')
    -- Host affinity: only claim tasks whose project is runnable here
    AND (p_runnable_projects IS NULL OR t.project_id = ANY(p_runnable_projects))
    -- Dependency gate: all deps must be DONE or MERGED
    AND (t.deps IS NULL OR array_length(t.deps, 1) IS NULL
         OR NOT EXISTS (
           SELECT 1 FROM unnest(t.deps) AS dep
           WHERE dep NOT IN (
             SELECT t2.slug FROM tasks t2
             WHERE t2.project_id = t.project_id
               AND t2.state IN ('DONE', 'MERGED')
           )
         ))
  ORDER BY
    -- Tier 1: release-fix tasks (unblock Vercel releases)
    CASE WHEN t.slug LIKE 'qafix-%' OR t.slug LIKE 'relfix-%'
              OR t.slug LIKE 'buildfix-%' OR t.slug LIKE 'deployfix-%'
         THEN 0 ELSE 1 END,
    -- Tier 2: recovery tasks
    CASE WHEN t.slug LIKE 'recover-%' OR t.kind = 'recovery' THEN 0 ELSE 1 END,
    -- Tier 3: rework tasks (quarantine rework)
    CASE WHEN t.slug LIKE 'rework-%' THEN 0 ELSE 1 END,
    -- Tier 4: improvement tasks
    CASE WHEN t.slug LIKE 'improve-%' OR t.kind = 'improvement' THEN 0 ELSE 1 END,
    -- Tier 5: kind weight (bugfix first, then test, cleanup, etc.)
    CASE t.kind
      WHEN 'bugfix'      THEN 0
      WHEN 'recovery'    THEN 1
      WHEN 'test'        THEN 2
      WHEN 'cleanup'     THEN 3
      WHEN 'chore'       THEN 3
      WHEN 'docs'        THEN 4
      WHEN 'build'       THEN 5
      WHEN 'efficiency'  THEN 6
      WHEN 'research'    THEN 7
      ELSE 8
    END,
    -- Tier 6: churn deprioritization (cont-/batch-mech last)
    CASE WHEN t.slug LIKE 'cont-%' OR t.slug LIKE 'batch-mech%' THEN 1 ELSE 0 END,
    -- Tier 7: confidence DESC (higher confidence first)
    t.confidence DESC NULLS LAST,
    -- Tier 8: portfolio project rank
    COALESCE(p.priority, 5) ASC,
    -- Tier 9: ROI weight DESC
    COALESCE(p.concurrency_weight, 1) DESC,
    -- Tier 10: FIFO
    t.created_at ASC
  LIMIT 1
  FOR UPDATE OF t SKIP LOCKED;

  IF v_task.id IS NULL THEN
    RETURN;  -- no eligible task
  END IF;

  -- Atomically claim: set state=RUNNING, record the runner
  UPDATE tasks
  SET state = 'RUNNING',
      account = p_runner_id,
      updated_at = now()
  WHERE id = v_task.id;

  -- Return the claimed row with updated state
  v_task.state := 'RUNNING';
  v_task.account := p_runner_id;
  RETURN NEXT v_task;
END;
$$;
