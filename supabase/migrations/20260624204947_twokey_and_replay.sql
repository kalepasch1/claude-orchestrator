-- two-key approvals for high-risk actions
alter table approvals add column if not exists approvals_required int not null default 1;
alter table approvals add column if not exists second_approver text;

-- deterministic replay: snapshot every run so any build is reproducible/bisectable
create table if not exists runs (
  id          uuid primary key default gen_random_uuid(),
  task_id     uuid,
  project     text, slug text, kind text,
  model       text, account text,
  base_commit text,
  prompt      text,           -- the exact composed prompt (prefix+context+lessons+task)
  confidence  numeric(4,3),
  created_at  timestamptz not null default now()
);
create index if not exists runs_task_idx on runs(task_id);
alter table runs enable row level security;
do $$ begin
  execute 'drop policy if exists runs_auth on runs';
  execute 'create policy runs_auth on runs for select to authenticated using (true)';
end $$;;
