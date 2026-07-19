-- budget guardrails
create table if not exists budgets (
  project        text primary key,
  monthly_usd_cap numeric(12,2) not null default 100,
  hard_pause     boolean not null default true,   -- true = stop swarm at cap; false = warn only
  updated_at     timestamptz not null default now()
);

-- regression memory: failed approaches + root causes
create table if not exists failures (
  id          uuid primary key default gen_random_uuid(),
  project     text,
  slug        text,
  kind        text default 'build',
  approach    text,            -- what was tried
  root_cause  text,            -- why it failed
  lesson      text,            -- the "avoid this" rule to inject next time
  keywords    text[] not null default '{}',
  created_at  timestamptz not null default now()
);
create index if not exists failures_kw_idx on failures using gin (keywords);

-- month-to-date spend per project (drives budget guard + burn-down chart)
create or replace view v_spend_mtd as
  select project,
         date_trunc('month', now()) as month,
         coalesce(sum(usd),0)::numeric(12,2) as spent
  from outcomes
  where created_at >= date_trunc('month', now())
  group by project;

-- RLS
alter table budgets enable row level security;
alter table failures enable row level security;
do $$ begin
  execute 'drop policy if exists budgets_auth on budgets';
  execute 'create policy budgets_auth on budgets for select to authenticated using (true)';
  execute 'drop policy if exists failures_auth on failures';
  execute 'create policy failures_auth on failures for select to authenticated using (true)';
end $$;

alter publication supabase_realtime add table budgets;

-- seed a default budget for tomorrow so the chart has a cap line
insert into budgets (project, monthly_usd_cap, hard_pause) values ('tomorrow', 200, true)
on conflict (project) do nothing;;
