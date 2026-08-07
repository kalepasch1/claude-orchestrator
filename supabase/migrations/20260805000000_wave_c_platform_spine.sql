-- WAVE C (Parts 4, 6, 7) — shared substrate the sibling shards build against.
-- Contracts slice only: tables + indexes + RLS, no behaviour, no backfills.
-- Mirrors runner/wave_c_contracts.py. See docs/wave-c-contracts.md.
-- NOT YET APPLIED to eatfwdzfurujcuwlhdgj — apply after a shadow dry-run.

-- ---------------------------------------------------------------------------
-- PART 4 — self-service code generator: disposition ledger
-- ---------------------------------------------------------------------------
create table if not exists public.codegen_disposition_ledger (
  id uuid primary key default gen_random_uuid(),
  task_slug text not null,
  project text not null,
  branch text null,
  disposition text not null default 'PENDING'
    check (disposition in ('PENDING','MERGED','SUPERSEDED','REJECTED','ABANDONED')),
  transplanted_from text null,
  similarity double precision not null default 0,
  rationale text null,
  recorded_at timestamptz not null default now()
);

create index if not exists idx_codegen_ledger_project_recorded
  on public.codegen_disposition_ledger(project, recorded_at desc);
create index if not exists idx_codegen_ledger_slug
  on public.codegen_disposition_ledger(task_slug);

create table if not exists public.codegen_golden_path_templates (
  id uuid primary key default gen_random_uuid(),
  vertical text not null,
  name text not null,
  file_scaffold jsonb not null default '[]'::jsonb,
  conventions jsonb not null default '[]'::jsonb,
  distilled_from jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now(),
  unique (vertical, name)
);

-- ---------------------------------------------------------------------------
-- PART 6 — matter spine, exposure flywheel, renewal annuity
-- ---------------------------------------------------------------------------
create table if not exists public.matter_records (
  matter_id uuid primary key default gen_random_uuid(),
  project text not null,
  title text not null default '',
  stage text not null default 'intake'
    check (stage in ('intake','triage','licensing','filings','video','newsletters','closed')),
  owner_label text null,
  linked_artifacts jsonb not null default '{}'::jsonb,
  expected_loss_usd numeric(20,2) not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_matter_records_project_stage
  on public.matter_records(project, stage);

create table if not exists public.matter_exposures (
  exposure_id uuid primary key default gen_random_uuid(),
  matter_id uuid not null references public.matter_records(matter_id) on delete cascade,
  risk_class text not null default '',
  expected_loss_usd numeric(20,2) not null default 0,
  hedgeable boolean not null default false,
  hedge_instrument_id text null,
  foundry_request_id text null,
  created_at timestamptz not null default now()
);

create index if not exists idx_matter_exposures_matter
  on public.matter_exposures(matter_id);
create index if not exists idx_matter_exposures_unhedgeable
  on public.matter_exposures(risk_class) where hedgeable = false;

create table if not exists public.matter_renewals (
  renewal_id uuid primary key default gen_random_uuid(),
  matter_id uuid not null references public.matter_records(matter_id) on delete cascade,
  source_filing_id text null,
  kind text not null default 'renewal' check (kind in ('renewal','report','attestation')),
  due_at timestamptz not null,
  lead_days integer not null default 30,
  monitor_armed boolean not null default false
);

create index if not exists idx_matter_renewals_due on public.matter_renewals(due_at asc);

-- ---------------------------------------------------------------------------
-- PART 7 — initiative-level integration + disposition memory
-- ---------------------------------------------------------------------------
create table if not exists public.initiatives (
  initiative_id uuid primary key default gen_random_uuid(),
  project text not null,
  title text not null default '',
  state text not null default 'open'
    check (state in ('open','ready','judging','merged','closed')),
  member_slugs jsonb not null default '[]'::jsonb,
  branches jsonb not null default '[]'::jsonb,
  complete boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_initiatives_project_state
  on public.initiatives(project, state);

create table if not exists public.disposition_memory (
  id uuid primary key default gen_random_uuid(),
  task_slug text not null,
  project text not null,
  disposition text not null default 'PENDING'
    check (disposition in ('PENDING','MERGED','SUPERSEDED','REJECTED','ABANDONED')),
  dedupe_key text not null,
  reason text null,
  suppressed_slugs jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create unique index if not exists uq_disposition_memory_key
  on public.disposition_memory(project, dedupe_key);

-- ---------------------------------------------------------------------------
-- RLS: operators read, service role writes (same posture as steering_events).
-- ---------------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array[
    'codegen_disposition_ledger','codegen_golden_path_templates',
    'matter_records','matter_exposures','matter_renewals',
    'initiatives','disposition_memory'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I on public.%I', t || '_auth_read', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (true)',
      t || '_auth_read', t
    );
  end loop;
end $$;
