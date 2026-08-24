-- Versioned contract columns for the portfolio-wide development session fabric.
-- Contracts slice only: additive columns, indexes and CHECK constraints. No behaviour,
-- no backfills, no triggers, no drops.
--
-- WHY. 20260813120000_development_session_store.sql gave sessions a durable event stream,
-- but its `status` vocabulary is active/completed/failed/abandoned — which cannot say
-- whether a change reached a user. Every adapter (Codex/ChatGPT, Claude Cowork,
-- orchestrator-native coders, thin product-app clients) therefore invents its own
-- phase names, and a closure can assert delivered work against no SHA at all.
--
-- The pinned states live in runner/development_session_contract.py; the CHECK below is
-- the same list, restated where a caller that bypasses the module cannot dodge it.
--
-- DONE and MERGED are ABSENT on purpose. They are task-level bookkeeping: a branch
-- exists, or it is on an integration branch. Only DEPLOYED_AND_VERIFIED means a user
-- can reach the change, and the fleet has repeatedly reported a merge as a ship.
--
-- ROLLOUT ORDER (see development_session_contract.rollout_plan()):
--   1. this migration (every column nullable or defaulted, so old writers keep working)
--   2. readers that ignore unknown fields
--   3. writers that emit them
--   4. only then raise ORCH_SESSION_CONTRACT_MIN_VERSION
-- ROLLBACK: revert writers, then readers. Leave this migration in place — dropping a
-- column is not backward compatible, and every column here is optional to an old writer.
--
-- Idempotent: safe to re-run across rolling hosts.

-- ---------------------------------------------------------------------------
-- Sessions: contract version, lifecycle state, fencing, adapter identity, SHAs.
-- ---------------------------------------------------------------------------
alter table if exists public.development_sessions
  add column if not exists contract_version text not null default '1.0',
  add column if not exists schema_version   integer not null default 2,
  -- Nullable: an in-flight session written by a pre-contract writer has no lifecycle
  -- state yet, and defaulting it to CREATED would retroactively assert something false.
  add column if not exists lifecycle_state  text,
  add column if not exists blocked_from     text,
  -- Lease fencing. "<session_id>:<generation>". A write whose token names a generation
  -- lower than the session's current one is stale and must be refused. Comparing tokens
  -- rather than timestamps is the point: a paused Mac that wakes with an old lease has a
  -- perfectly plausible clock and a provably stale generation.
  add column if not exists fencing_token    text,
  add column if not exists adapter_version  text,
  -- The three SHAs a closure must be able to name. Separate on purpose: a change can be
  -- committed onto one base and released from a different tree.
  add column if not exists base_sha         text,
  add column if not exists artifact_sha     text,
  add column if not exists release_sha      text,
  add column if not exists rolled_back_from text,
  add column if not exists rolled_back_at   timestamptz;

do $$
begin
  if not exists (select 1 from pg_constraint
                 where conname = 'development_sessions_lifecycle_state_check') then
    alter table public.development_sessions
      add constraint development_sessions_lifecycle_state_check
      check (lifecycle_state is null or lifecycle_state in (
        'CREATED','PLANNING','PLAN_REVIEW','EXECUTING','VERIFYING',
        'INTEGRATING','RELEASING','DEPLOYED_AND_VERIFIED','BLOCKED'));
  end if;

  -- A session may only claim it reached production if it can name the release it
  -- reached production from. Stated as a constraint because the claim is the one thing
  -- nobody can re-derive after the fact.
  if not exists (select 1 from pg_constraint
                 where conname = 'development_sessions_deployed_needs_shas_check') then
    alter table public.development_sessions
      add constraint development_sessions_deployed_needs_shas_check
      check (lifecycle_state is distinct from 'DEPLOYED_AND_VERIFIED'
             or (base_sha is not null and artifact_sha is not null
                 and release_sha is not null));
  end if;
end $$;

create index if not exists development_sessions_lifecycle_idx
  on public.development_sessions (lifecycle_state, updated_at desc);
-- Stale-lease sweep: find sessions whose fencing token no longer matches their generation.
create index if not exists development_sessions_fencing_idx
  on public.development_sessions (fencing_token);

-- ---------------------------------------------------------------------------
-- Events: stamp the contract version each event was written under, so a reader can
-- refuse a record it cannot faithfully interpret instead of half-parsing it.
-- ---------------------------------------------------------------------------
alter table if exists public.development_session_events
  add column if not exists contract_version text not null default '1.0',
  add column if not exists actor            text,
  add column if not exists actor_kind       text,
  add column if not exists fencing_token    text;

do $$
begin
  if not exists (select 1 from pg_constraint
                 where conname = 'development_session_events_actor_kind_check') then
    alter table public.development_session_events
      add constraint development_session_events_actor_kind_check
      check (actor_kind is null or actor_kind in ('owner','agent','adapter','system'));
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- Proof receipts: the command that was run, its exit code, and the SHA it ran against.
-- All three together, or the receipt proves that something passed somewhere.
-- ---------------------------------------------------------------------------
create table if not exists public.development_session_proofs (
  proof_id         uuid primary key default gen_random_uuid(),
  session_id       uuid
                   references public.development_sessions (session_id) on delete cascade,
  slug             text,
  contract_version text not null default '1.0',
  kind             text not null
    check (kind in ('test','build','lint','deploy-check','asserted')),
  command          text not null check (length(btrim(command)) >= 3),
  exit_code        integer not null,
  -- The SHA the command was run against. NOT NULL: a receipt without one is not a claim
  -- anyone can reproduce, which is the only kind of claim worth recording.
  artifact_sha     text not null,
  runner_host      text,
  adapter          text,
  generation       bigint not null default 0,
  output_digest    text,
  created_at       timestamptz not null default now()
);

create index if not exists development_session_proofs_session_idx
  on public.development_session_proofs (session_id, created_at desc);
create index if not exists development_session_proofs_sha_idx
  on public.development_session_proofs (artifact_sha);
-- Closure gate reads "is there a PASSING proof of a proving kind for this sha".
create index if not exists development_session_proofs_passing_idx
  on public.development_session_proofs (artifact_sha, kind)
  where exit_code = 0 and kind <> 'asserted';

-- ---------------------------------------------------------------------------
-- Steering decisions: what was decided, by whom, and why.
-- ---------------------------------------------------------------------------
create table if not exists public.development_session_steering (
  decision_id      uuid primary key default gen_random_uuid(),
  session_id       uuid
                   references public.development_sessions (session_id) on delete cascade,
  contract_version text not null default '1.0',
  decision         text not null
    check (decision in ('continue','revise','split','abort','escalate','rollback')),
  actor            text not null,
  actor_kind       text not null default 'agent'
    check (actor_kind in ('owner','agent','adapter','system')),
  -- Rationale is NOT NULL because a decision nobody explained cannot be reviewed, and
  -- abort/rollback/escalate are exactly the decisions that get reviewed.
  rationale        text not null check (length(btrim(rationale)) > 0),
  created_at       timestamptz not null default now(),
  -- abort, rollback and escalate are owner-only. Enforced here so an adapter cannot
  -- authorise its own escalation by bypassing the module.
  constraint development_session_steering_owner_only_check
    check (decision not in ('abort','escalate','rollback') or actor_kind = 'owner')
);

create index if not exists development_session_steering_session_idx
  on public.development_session_steering (session_id, created_at desc);
