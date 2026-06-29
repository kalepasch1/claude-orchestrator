-- v3.2: goal-driven autonomy, semantic result cache, portfolio health + action inbox.
create table if not exists goals (
  id uuid primary key default gen_random_uuid(),
  project text, objective text not null, metric text, target text,
  status text not null default 'active', priority int not null default 100,
  created_at timestamptz not null default now()
);
create table if not exists result_cache (
  signature text primary key, project text, slug text, branch text, summary text,
  hits int not null default 0, created_at timestamptz not null default now(), last_used timestamptz
);
alter table goals enable row level security;
alter table result_cache enable row level security;
do $$ begin
  execute 'drop policy if exists goals_auth on goals';
  execute 'create policy goals_auth on goals for select to authenticated using (true)';
  execute 'drop policy if exists goals_write on goals';
  execute 'create policy goals_write on goals for insert to authenticated with check (true)';
  execute 'drop policy if exists cache_auth on result_cache';
  execute 'create policy cache_auth on result_cache for select to authenticated using (true)';
end $$;
alter publication supabase_realtime add table goals;
-- views v_project_health and v_action_inbox: see applied migration / connector.
