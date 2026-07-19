-- v3.3: cross-repo transactions, per-task confidence, per-project thresholds + ROI weight

-- cross-repo refactor transactions
create table if not exists txns (
  id          text primary key,
  name        text not null,
  description text,
  status      text not null default 'pending', -- pending | merged | aborted
  created_at  timestamptz not null default now(),
  resolved_at timestamptz
);
alter table txns enable row level security;
do $$ begin
  execute 'drop policy if exists txns_auth_read on txns';
  execute 'create policy txns_auth_read on txns for select to authenticated using (true)';
  execute 'drop policy if exists txns_auth_write on txns';
  execute 'create policy txns_auth_write on txns for insert to authenticated with check (true)';
  execute 'drop policy if exists txns_auth_update on txns';
  execute 'create policy txns_auth_update on txns for update to authenticated using (true) with check (true)';
end $$;
alter publication supabase_realtime add table txns;

-- confidence score stored on each task for dashboard display
alter table tasks add column if not exists confidence numeric;

-- per-project: custom confidence threshold + ROI scheduling weight
alter table projects add column if not exists confidence_threshold numeric;
alter table projects add column if not exists concurrency_weight int not null default 1;

-- runs table: ensure realtime
do $$ begin
  alter publication supabase_realtime add table runs;
exception when others then null;
end $$;
