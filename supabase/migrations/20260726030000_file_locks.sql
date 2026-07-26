-- Create file_locks table for conflict-free multi-agent coordination
create table if not exists file_locks (
  id uuid primary key default gen_random_uuid(),
  project_id text not null,
  file_path text not null,
  locked_by text not null,        -- dag_id or agent identifier
  lock_type text not null check (lock_type in ('exclusive','shared')),
  task_slug text,
  acquired_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '30 minutes'),
  released_at timestamptz,
  constraint uq_active_exclusive unique (project_id, file_path)
);

create index if not exists idx_file_locks_active on file_locks(project_id, file_path)
  where released_at is null;
create index if not exists idx_file_locks_expires on file_locks(expires_at)
  where released_at is null;

alter table file_locks enable row level security;
create policy if not exists "Service role full access" on file_locks
  for all using (auth.role() = 'service_role');
