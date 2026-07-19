-- per-project release/deploy config
alter table projects add column if not exists prod_branch text;         -- auto-detected: main|master
alter table projects add column if not exists staging_branch text default 'orchestrator/staging';
alter table projects add column if not exists last_good_sha text;       -- last successful prod deploy commit (rollback target)
alter table projects add column if not exists vercel_project text;      -- vercel project id/name (optional)

-- release train: each batch cut from staging -> prod, with deploy status for rollback
create table if not exists releases (
  id uuid primary key default gen_random_uuid(),
  project text, version text,
  from_sha text, to_sha text,
  n_changes integer, changelog text,
  deploy_status text default 'pending',   -- pending|building|success|failed|rolled_back
  vercel_url text, note text,
  created_at timestamptz default now(), deployed_at timestamptz
);
create index if not exists idx_releases_proj on releases(project, created_at desc);

-- global version register: v1 = current improvement queue; bumped on critical-mass/novel improvements
create table if not exists versions (
  version text primary key,               -- e.g. 'v1', 'v2'
  title text, summary text,
  status text default 'in_progress',      -- in_progress|released
  opened_at timestamptz default now(), released_at timestamptz
);
insert into versions (version, title, summary, status)
  values ('v1','Foundational orchestration','Autonomous multi-app orchestration: billing firewall, multi-model triage, auto-merge, cockpit, release trains.','in_progress')
  on conflict (version) do nothing;;
