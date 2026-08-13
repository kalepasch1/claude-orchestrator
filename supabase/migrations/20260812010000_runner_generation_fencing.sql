-- runner_generation_fencing — admission + write fencing for distributed runners.
--
-- A runner seat (runner_id) is immutable; each process start bumps a monotonic
-- runner_generation. The control plane admits exactly one generation per seat.
-- Claims and canonical mutations carry the fence; stale or unadmitted writers
-- may finish and emit a recoverable artifact, but may not claim or mutate.
--
-- Idempotent by design: every statement is IF NOT EXISTS / ADD COLUMN IF NOT
-- EXISTS so a partially-applied rollout can be re-run safely.

CREATE TABLE IF NOT EXISTS runner_admissions (
  runner_id        text PRIMARY KEY,
  host             text,
  generation       bigint NOT NULL DEFAULT 0,
  contract_hash    text,
  code_sha         text,
  admitted_at      timestamptz NOT NULL DEFAULT now(),
  admitted_by      text,
  drained          boolean NOT NULL DEFAULT false,
  drain_reason     text
);

CREATE INDEX IF NOT EXISTS runner_admissions_host_idx ON runner_admissions (host);

-- Generation must never move backwards for a seat. A rollback that reuses an
-- old generation is precisely the two-Mac race this table exists to stop.
CREATE OR REPLACE FUNCTION runner_admission_monotonic() RETURNS trigger AS $$
BEGIN
  IF NEW.generation < OLD.generation THEN
    RAISE EXCEPTION 'runner_admissions.generation is monotonic (% -> % for %)',
      OLD.generation, NEW.generation, OLD.runner_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_runner_admission_monotonic ON runner_admissions;
CREATE TRIGGER trg_runner_admission_monotonic
  BEFORE UPDATE ON runner_admissions
  FOR EACH ROW EXECUTE FUNCTION runner_admission_monotonic();

-- Fence carried by every claim. Nullable on purpose: pre-rollout runners write
-- NULL, and the client-side classifier treats NULL as legacy_pre_rollout only
-- while no admission row exists for that seat.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS runner_id text;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS runner_generation bigint;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS fence_token text;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS contract_hash text;

CREATE INDEX IF NOT EXISTS tasks_runner_fence_idx ON tasks (runner_id, runner_generation);

-- Same fence on the canonical proof surfaces, so a drained writer's rows are
-- attributable after the fact.
ALTER TABLE releases ADD COLUMN IF NOT EXISTS runner_id text;
ALTER TABLE releases ADD COLUMN IF NOT EXISTS runner_generation bigint;

-- Drain alerts are written in their own transaction; this keeps them queryable
-- even when the refusal that produced them rolled back.
ALTER TABLE runner_alerts ADD COLUMN IF NOT EXISTS runner_id text;
ALTER TABLE runner_alerts ADD COLUMN IF NOT EXISTS runner_generation bigint;
ALTER TABLE runner_alerts ADD COLUMN IF NOT EXISTS admitted_generation bigint;
ALTER TABLE runner_alerts ADD COLUMN IF NOT EXISTS verdict text;
ALTER TABLE runner_alerts ADD COLUMN IF NOT EXISTS contract_hash text;
ALTER TABLE runner_alerts ADD COLUMN IF NOT EXISTS expected_contract_hash text;
