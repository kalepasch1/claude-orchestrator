-- HOST UPDATE VISIBILITY (2026-08-06)
--
-- A host pinned at an old code_sha used to be indistinguishable from a current one:
-- it heartbeats, it claims, active_tasks is non-zero. Mandys-MacBook-Pro.local ran
-- 40+ commits behind for two days on exactly that basis and completed 0 of 46 tasks.
-- Publishing commits_behind on the heartbeat turns "is this host stale?" from a manual
-- fetch-and-compare into a single query.
--
-- Additive and idempotent. runner/db.py strips commits_behind and retries if a remote
-- has not applied this yet, so rolling upgrades stay safe in both directions.

ALTER TABLE IF EXISTS public.runner_heartbeats
  ADD COLUMN IF NOT EXISTS commits_behind integer;

COMMENT ON COLUMN public.runner_heartbeats.commits_behind IS
  'Commits HEAD is behind origin/<default branch> at heartbeat time; NULL when unknowable.';

-- Stale-host lookup without a repo fetch.
CREATE INDEX IF NOT EXISTS runner_heartbeats_commits_behind_idx
  ON public.runner_heartbeats (commits_behind)
  WHERE commits_behind IS NOT NULL AND commits_behind > 0;

-- host_update alerts are read by kind + unresolved on every operator sweep.
CREATE INDEX IF NOT EXISTS runner_alerts_kind_unresolved_idx
  ON public.runner_alerts (kind, created_at DESC)
  WHERE resolved = false;
