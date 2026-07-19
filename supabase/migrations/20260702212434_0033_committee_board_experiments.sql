-- champion/challenger + auto-experiments (settle reversible splits with data instead of a human)
create table if not exists committee_experiments (
  id uuid primary key default gen_random_uuid(),
  app text, slug text, hypothesis text, kind text default 'ab',   -- ab | holdout
  status text default 'running',                                   -- running | concluded
  metric_start numeric, metric_last numeric, lift numeric, decision text,
  created_at timestamptz default now(), concluded_at timestamptz
);
create index if not exists idx_exp_status on committee_experiments(status);

-- portfolio board: cross-app allocation of the next build effort
create table if not exists board_allocations (
  id uuid primary key default gen_random_uuid(),
  cycle timestamptz default now(), app text, recommended_share numeric, rationale text
);

-- event-driven watch: external signals (reg/security/competitor) that should re-open the docket
create table if not exists watch_signals (
  id uuid primary key default gen_random_uuid(),
  kind text, source text, summary text, affects_app text,
  acted boolean default false, seen_at timestamptz default now()
);

-- plain-English board minutes per cycle
create table if not exists board_minutes (
  id uuid primary key default gen_random_uuid(),
  cycle timestamptz default now(), headline text, body text
);;
