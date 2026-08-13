-- WAVE C — platform spine persistence. Contracts slice only: tables, indexes,
-- constraints and RLS. No behaviour, no backfills, no triggers.
--
-- Mirrors packages/spine/shared/types (the entity layer) the way
-- 20260805000000_wave_c_platform_spine.sql mirrors runner/wave_c_contracts.py.
-- Where the TypeScript states an invariant in the type system — terminal
-- statuses mapping to `never`, an append-only log, a per-compound sequence —
-- this states the same invariant as a constraint, so the rule survives a caller
-- that bypasses the typed client.
--
-- Table names are `spine_*` on purpose. The failed-recovery placeholder for this
-- slice named `pipelines`, `pipeline_stages` and `passport_snapshot`, but those
-- strings appear nowhere in the codebase except that placeholder itself, so
-- creating tables under them would be inventing a schema no code reads.
--
-- NOT YET APPLIED to eatfwdzfurujcuwlhdgj — apply after a shadow dry-run.
-- Idempotent: safe to re-run across rolling hosts.

-- ---------------------------------------------------------------------------
-- Compounds — the unit of compounding work.
-- ---------------------------------------------------------------------------
create table if not exists public.spine_compounds (
  compound_id uuid primary key default gen_random_uuid(),
  name text not null,
  owner text not null,
  status text not null default 'draft'
    check (status in ('draft','queued','running','settled','failed')),
  -- Ordered WaveSpec[] as declared at creation. Immutable for the compound's
  -- life: re-planning means a new compound, so a settled record still says
  -- what actually ran.
  waves jsonb not null default '[]'::jsonb,
  labels jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  terminal_at timestamptz null,
  terminal_reason text null,
  -- Highest event sequence applied. Gap detection reads this; without it
  -- out-of-order delivery cannot be told from a missed event.
  applied_sequence bigint not null default 0
    check (applied_sequence >= 0),
  -- A terminal status carries its timestamp and a non-terminal one does not.
  -- This is the constraint form of TerminalCompoundStatus.
  constraint spine_compounds_terminal_at_matches_status check (
    (status in ('settled','failed')) = (terminal_at is not null)
  )
);

-- CreateCompound rejects a duplicate (owner, name) with `conflict`; enforce it
-- here so two concurrent creates cannot both win.
create unique index if not exists uq_spine_compounds_owner_name
  on public.spine_compounds(owner, name);
create index if not exists idx_spine_compounds_owner_status
  on public.spine_compounds(owner, status);
create index if not exists idx_spine_compounds_active_updated
  on public.spine_compounds(updated_at desc)
  where status not in ('settled','failed');

-- ---------------------------------------------------------------------------
-- Waves — one execution unit of a compound.
-- ---------------------------------------------------------------------------
create table if not exists public.spine_waves (
  wave_id uuid primary key default gen_random_uuid(),
  compound_id uuid not null
    references public.spine_compounds(compound_id) on delete cascade,
  name text not null,
  status text not null default 'pending'
    check (status in ('pending','running','settled','failed','skipped')),
  -- 1-based. Matches WaveState.attempt.
  attempt integer not null default 1 check (attempt >= 1),
  spec jsonb not null default '{}'::jsonb,
  -- Append-only WaveAttempt[], oldest first. Retries append; a wave that
  -- eventually settled still shows what failed.
  attempts jsonb not null default '[]'::jsonb,
  -- WaveOutput. Present only once settled — the compounding seam that wave N+1
  -- reads. Artifacts carry a digest so a real change is distinguishable from a
  -- re-run.
  output jsonb null,
  started_at timestamptz null,
  settled_at timestamptz null,
  terminal_reason text null,
  -- Output exists exactly when the wave settled: an unsettled wave publishing
  -- output would let a downstream wave consume a partial result.
  constraint spine_waves_output_requires_settled check (
    (status = 'settled') or (output is null)
  ),
  constraint spine_waves_settled_at_matches_status check (
    (status in ('settled','failed','skipped')) = (settled_at is not null)
  )
);

-- Wave names are unique within their compound (WaveSpec.name), which is what
-- makes `dependsOn` resolvable by name.
create unique index if not exists uq_spine_waves_compound_name
  on public.spine_waves(compound_id, name);
create index if not exists idx_spine_waves_compound_status
  on public.spine_waves(compound_id, status);

-- ---------------------------------------------------------------------------
-- Events — the append-only log. The only completion path.
-- ---------------------------------------------------------------------------
create table if not exists public.spine_events (
  event_id uuid primary key default gen_random_uuid(),
  compound_id uuid not null
    references public.spine_compounds(compound_id) on delete cascade,
  kind text not null check (kind in (
    'compound.created','compound.cancelled',
    'wave.triggered','wave.settled','wave.failed'
  )),
  wave_id uuid null
    references public.spine_waves(wave_id) on delete cascade,
  -- Monotonic per compound. Consumers order on this, not on occurred_at,
  -- because occurred_at can tie.
  sequence bigint not null check (sequence > 0),
  occurred_at timestamptz not null,
  -- When the platform durably recorded it. Distinct from occurred_at.
  recorded_at timestamptz not null default now(),
  -- The delivered wire event, verbatim, so the log replays what arrived.
  event jsonb not null,
  -- False when the delivery was a duplicate or out of order and changed no
  -- state. Recorded either way: a rejected delivery is evidence of a producer
  -- replaying or racing, and dropping it hides that.
  applied boolean not null default false,
  rejection_reason text null check (rejection_reason in (
    'duplicate','out_of_order','terminal_status','unknown_compound'
  )),
  -- An applied event has no rejection reason and an unapplied one must give it.
  constraint spine_events_rejection_matches_applied check (
    applied = (rejection_reason is null)
  ),
  -- Wave-scoped kinds name their wave; compound-scoped kinds do not.
  constraint spine_events_wave_id_matches_kind check (
    (kind like 'wave.%') = (wave_id is not null)
  )
);

-- One event per (compound, sequence). This is what makes the gap check in
-- applied_sequence meaningful: a replay cannot occupy a new slot.
create unique index if not exists uq_spine_events_compound_sequence
  on public.spine_events(compound_id, sequence);
create index if not exists idx_spine_events_compound_recorded
  on public.spine_events(compound_id, recorded_at desc);
-- Rejected deliveries are the diagnostic read, and they are the minority.
create index if not exists idx_spine_events_rejected
  on public.spine_events(compound_id, rejection_reason)
  where applied = false;

-- ---------------------------------------------------------------------------
-- Idempotency ledger — every mutating contract takes an idempotencyKey and a
-- retry must return the original effect, not a second one. That promise needs
-- somewhere to remember the first outcome.
-- ---------------------------------------------------------------------------
create table if not exists public.spine_idempotency_keys (
  id uuid primary key default gen_random_uuid(),
  -- Which operation the key was used for; the same key in two operations is
  -- two independent effects.
  scope text not null check (scope in (
    'create_compound','cancel_compound','trigger_wave','process_event'
  )),
  idempotency_key text not null,
  compound_id uuid null
    references public.spine_compounds(compound_id) on delete cascade,
  -- The response replayed to a retry, so dedup returns the original ids.
  result jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create unique index if not exists uq_spine_idempotency_scope_key
  on public.spine_idempotency_keys(scope, idempotency_key);

-- ---------------------------------------------------------------------------
-- RLS: operators read, service role writes. Same posture as steering_events
-- and 20260805000000_wave_c_platform_spine.sql.
-- ---------------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array[
    'spine_compounds','spine_waves','spine_events','spine_idempotency_keys'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I on public.%I', t || '_auth_read', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (true)',
      t || '_auth_read', t
    );
  end loop;
end $$;
