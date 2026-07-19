-- v3.9: per-run structured log lines; realtime channel for LogView binding.
create table if not exists run_logs (
  id       uuid        primary key default gen_random_uuid(),
  run_id   uuid        references runs(id) on delete cascade,
  ts       timestamptz not null default now(),
  level    text        not null check (level in ('debug','info','warn','error')),
  source   text,
  message  text        not null
);
create index if not exists run_logs_run_ts_idx on run_logs(run_id, ts);

alter table run_logs enable row level security;
do $$ begin
  execute 'drop policy if exists run_logs_auth_read on run_logs';
  execute 'create policy run_logs_auth_read on run_logs for select to authenticated using (true)';
exception when others then null; end $$;

do $$ begin
  alter publication supabase_realtime add table run_logs;
exception when others then null; end $$;;
