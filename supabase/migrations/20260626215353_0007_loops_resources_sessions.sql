-- v3.6: per-app autonomous loops, resource governance, session next-step decisions.
create table if not exists loops (
  id uuid primary key default gen_random_uuid(),
  project text not null, type text not null,
  cadence_seconds int not null default 1800, config jsonb not null default '{}',
  enabled boolean not null default true, health numeric(5,2) not null default 100,
  last_run timestamptz, created_at timestamptz not null default now(),
  unique (project, type)
);
create table if not exists resource_events (
  id bigint generated always as identity primary key,
  kind text not null, value numeric, detail text, action text,
  created_at timestamptz not null default now()
);
create table if not exists session_actions (
  id uuid primary key default gen_random_uuid(),
  session_id text, project text, status text,
  summary text, next_action text, auto boolean default false,
  created_at timestamptz not null default now()
);
alter table loops enable row level security;
alter table resource_events enable row level security;
alter table session_actions enable row level security;
do $$ declare t text; begin
  foreach t in array array['loops','resource_events','session_actions'] loop
    execute format('drop policy if exists %I_read on %I;', t, t);
    execute format('create policy %I_read on %I for select to authenticated using (true);', t, t);
  end loop;
  execute 'drop policy if exists loops_write on loops';
  execute 'create policy loops_write on loops for insert to authenticated with check (true)';
end $$;;
