-- v3.1 additions: budget guardrails, regression memory, month-to-date spend view.
create table if not exists budgets (
  project         text primary key,
  monthly_usd_cap numeric(12,2) not null default 100,
  hard_pause      boolean not null default true,
  updated_at      timestamptz not null default now()
);

create table if not exists failures (
  id          uuid primary key default gen_random_uuid(),
  project     text, slug text, kind text default 'build',
  approach    text, root_cause text, lesson text,
  keywords    text[] not null default '{}',
  created_at  timestamptz not null default now()
);
create index if not exists failures_kw_idx on failures using gin (keywords);

create or replace view v_spend_mtd as
  select project, date_trunc('month', now()) as month,
         coalesce(sum(usd),0)::numeric(12,2) as spent
  from outcomes where created_at >= date_trunc('month', now())
  group by project;

alter table budgets enable row level security;
alter table failures enable row level security;
do $$ begin
  execute 'drop policy if exists budgets_auth on budgets';
  execute 'create policy budgets_auth on budgets for select to authenticated using (true)';
  execute 'drop policy if exists failures_auth on failures';
  execute 'create policy failures_auth on failures for select to authenticated using (true)';
end $$;
alter publication supabase_realtime add table budgets;
