-- Database Steering: every linked database becomes a continuously reviewed subject,
-- and every fact it yields lands in the legal-memo evidence ledger.
--
-- Context (2026-09-12). The fleet steers CODE with gates, verdict cards, an expert corps
-- and swarm-filed remediation. Its only DATABASE control was rls_guard: one COUNT(*) per
-- app, once a day, over a hand-typed `security_posture` list of eight Supabase refs —
-- apparently-law and illuminati, both live, were not on it. Meanwhile the Management API
-- token already reaches 25 projects and exposes free security/performance advisor lints,
-- pg_stat_statements and the whole catalog. Nothing read them.
--
-- These tables are the substrate for runner/db_registry.py (sources), db_probes.py +
-- db_steering.py (findings, snapshots, briefs) and db_memo.py (memo drafts + evidence).
-- Credentials are NEVER stored here: `db_sources.credential_ref` names where a secret
-- lives (env:, keychain:, doppler:, onepassword:, vault:<connector_account>, file:), the
-- same discipline as runner/secrets_manager.py.

create table if not exists public.db_sources (
  id              uuid primary key default gen_random_uuid(),
  project         text,                                   -- fleet project name (projects.name), nullable
  label           text not null,
  provider        text not null check (provider in (
                    'supabase','postgres','mysql','aws_rds','aws_aurora','aws_redshift',
                    'gcp_cloudsql','gcp_alloydb','gcp_bigquery','azure_postgres','azure_mysql',
                    'neon','planetscale','cockroachdb','snowflake','mongodb','other')),
  dialect         text not null default 'postgres' check (dialect in ('postgres','mysql','bigquery','snowflake','mongodb','other')),
  ref             text not null,                          -- supabase project ref / host / instance / dataset
  region          text,
  credential_ref  text,                                   -- a REFERENCE, never a value (see header)
  config          jsonb not null default '{}'::jsonb,     -- provider specifics: port, database, resource_arn, ...
  discovered_via  text not null default 'operator',      -- operator | supabase_management_api | web_connector
  status          text not null default 'active' check (status in ('active','paused','unreachable','inactive')),
  enabled         boolean not null default true,
  capabilities    jsonb not null default '{}'::jsonb,     -- advisors, pg_stat_statements, ... as discovered
  last_scan_at    timestamptz,
  last_ok_at      timestamptz,
  last_error      text,
  consecutive_failures int not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (provider, ref)
);
create index if not exists db_sources_project_idx on public.db_sources(project);
create index if not exists db_sources_enabled_idx on public.db_sources(enabled, status);

create table if not exists public.db_findings (
  id              uuid primary key default gen_random_uuid(),
  source_id       uuid not null references public.db_sources(id) on delete cascade,
  project         text,
  probe_id        text not null,
  category        text not null check (category in (
                    'security','privacy','integrity','audit','performance','availability',
                    'retention','schema_drift','cost','ai_governance')),
  severity        text not null check (severity in ('info','low','medium','high','critical')),
  fingerprint     text not null,                          -- probe + object identity; metrics excluded
  title           text not null,
  detail          text,
  object_schema   text,
  object_name     text,
  metrics         jsonb not null default '{}'::jsonb,
  evidence_kinds  text[] not null default '{}',
  direction       text not null default 'undermines' check (direction in ('supports','undermines')),
  remediation     text,
  status          text not null default 'open' check (status in ('open','resolved','suppressed','acknowledged')),
  first_seen_at   timestamptz not null default now(),
  last_seen_at    timestamptz not null default now(),
  resolved_at     timestamptz,
  occurrences     int not null default 1,
  task_slug       text,                                   -- swarm remediation task, when filed
  created_at      timestamptz not null default now(),
  unique (source_id, fingerprint)
);
create index if not exists db_findings_open_idx on public.db_findings(project, status, severity);
create index if not exists db_findings_source_idx on public.db_findings(source_id, status);
create index if not exists db_findings_probe_idx on public.db_findings(probe_id);
create index if not exists db_findings_evidence_idx on public.db_findings using gin (evidence_kinds);

create table if not exists public.db_posture_snapshots (
  id              uuid primary key default gen_random_uuid(),
  source_id       uuid not null references public.db_sources(id) on delete cascade,
  project         text,
  taken_at        timestamptz not null default now(),
  score           numeric(5,2),                           -- 0-100, higher is healthier
  counts          jsonb not null default '{}'::jsonb,     -- open findings by severity and category
  probe_stats     jsonb not null default '{}'::jsonb,     -- probes run, skipped, failed, durations
  facts           jsonb not null default '{}'::jsonb,     -- table counts, sizes, extensions: the positive record
  summary         text
);
create index if not exists db_posture_snapshots_source_idx on public.db_posture_snapshots(source_id, taken_at desc);

-- The per-project brief prompt_assembler injects into every coder prompt for that project.
-- Small by construction (<= 2KB): a few concrete "when you touch X, do Y" lines.
create table if not exists public.db_steering_briefs (
  project         text primary key,
  brief           text not null,
  findings_hash   text not null,
  open_counts     jsonb not null default '{}'::jsonb,
  updated_at      timestamptz not null default now()
);

-- Internal legal-memo drafts, one per (project, memo_kind). Built incrementally from the
-- evidence ledger; prose is regenerated only when the evidence hash changes. Internal by
-- construction: nothing here is customer-facing and nothing here is legal advice.
create table if not exists public.legal_memo_drafts (
  id              uuid primary key default gen_random_uuid(),
  project         text not null,
  memo_kind       text not null,
  title           text not null,
  thesis          text,
  body            text,                                   -- markdown
  arguments       jsonb not null default '[]'::jsonb,     -- [{key, claim, strength, supports:[fp], undermines:[fp]}]
  evidence_hash   text,
  evidence_count  int not null default 0,
  status          text not null default 'draft' check (status in ('draft','reviewed','stale')),
  publication_state text not null default 'internal',
  gauntlet        jsonb,                                  -- last expert-corps review, when one ran
  gauntlet_at     timestamptz,
  model_provider  text,
  model_name      text,
  last_evidence_at timestamptz,
  drafted_at      timestamptz,
  updated_at      timestamptz not null default now(),
  unique (project, memo_kind)
);
create index if not exists legal_memo_drafts_project_idx on public.legal_memo_drafts(project, status);

create table if not exists public.legal_memo_evidence (
  id              uuid primary key default gen_random_uuid(),
  memo_id         uuid not null references public.legal_memo_drafts(id) on delete cascade,
  finding_id      uuid not null references public.db_findings(id) on delete cascade,
  argument_key    text not null,
  direction       text not null check (direction in ('supports','undermines')),
  weight          numeric(4,2) not null default 1.0,
  note            text,
  created_at      timestamptz not null default now(),
  unique (memo_id, finding_id, argument_key)
);
create index if not exists legal_memo_evidence_memo_idx on public.legal_memo_evidence(memo_id, argument_key);

-- Read for members; the runner writes with the service role (bypasses RLS), same as
-- legal_docket / verdict_cards.
alter table public.db_sources            enable row level security;
alter table public.db_findings           enable row level security;
alter table public.db_posture_snapshots  enable row level security;
alter table public.db_steering_briefs    enable row level security;
alter table public.legal_memo_drafts     enable row level security;
alter table public.legal_memo_evidence   enable row level security;
do $$ begin
  execute 'drop policy if exists db_sources_read on public.db_sources';
  execute 'create policy db_sources_read on public.db_sources for select to authenticated using (true)';
  execute 'drop policy if exists db_findings_read on public.db_findings';
  execute 'create policy db_findings_read on public.db_findings for select to authenticated using (true)';
  execute 'drop policy if exists db_posture_snapshots_read on public.db_posture_snapshots';
  execute 'create policy db_posture_snapshots_read on public.db_posture_snapshots for select to authenticated using (true)';
  execute 'drop policy if exists db_steering_briefs_read on public.db_steering_briefs';
  execute 'create policy db_steering_briefs_read on public.db_steering_briefs for select to authenticated using (true)';
  execute 'drop policy if exists legal_memo_drafts_read on public.legal_memo_drafts';
  execute 'create policy legal_memo_drafts_read on public.legal_memo_drafts for select to authenticated using (true)';
  execute 'drop policy if exists legal_memo_evidence_read on public.legal_memo_evidence';
  execute 'create policy legal_memo_evidence_read on public.legal_memo_evidence for select to authenticated using (true)';
end $$;

select 'database steering migration OK' as status;
