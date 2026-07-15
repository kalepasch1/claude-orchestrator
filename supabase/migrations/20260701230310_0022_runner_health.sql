create table if not exists runner_health (
  id uuid primary key default gen_random_uuid(),
  runner_id text, hostname text,
  firewall_ok boolean, locked_worktrees integer, claimable integer,
  ram_free_gb numeric, stale_running_cleared integer,
  status text, detail text, created_at timestamptz default now()
);
create index if not exists idx_runner_health_t on runner_health(created_at desc);
-- track auto-remediation of BLOCKED tasks
alter table tasks add column if not exists remediation_count integer not null default 0;;
