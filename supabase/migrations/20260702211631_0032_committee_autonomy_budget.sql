-- staged rollout mandates: a GO becomes canary -> ramp -> full, auto-advanced/rolled-back on metrics
create table if not exists committee_rollouts (
  id uuid primary key default gen_random_uuid(),
  app text, slug text, stage text default 'canary',   -- canary | ramp | full | rolled_back
  pct integer default 5, metric_start numeric, metric_last numeric,
  status text default 'active', note text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);
create index if not exists idx_rollout_active on committee_rollouts(status);

-- post-decision scoreboard: which committees/seats are actually right (fed by realized outcomes)
create table if not exists committee_scoreboard (
  entity_type text, committee text, seat text,
  calls integer, correct integer, accuracy numeric, avg_ev numeric,
  updated_at timestamptz default now(),
  primary key (entity_type, committee, seat)
);

-- owner override learning: when the owner decides against the committee, capture it to retrain thresholds
create table if not exists owner_overrides (
  id uuid primary key default gen_random_uuid(),
  subject_type text, subject_id uuid, subject_title text,
  committee_rec text, owner_decision text, direction text,  -- owner_more_cautious | owner_more_aggressive
  created_at timestamptz default now()
);

-- small learned owner model (threshold nudges etc.)
create table if not exists owner_model (
  key text primary key, value numeric, updated_at timestamptz default now()
);

-- app scoping on opinions enables cross-app "shared case law"
alter table committee_opinions add column if not exists app text;;
