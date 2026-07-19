-- goal-driven autonomy: standing objectives the swarm pursues
create table if not exists goals (
  id          uuid primary key default gen_random_uuid(),
  project     text,
  objective   text not null,            -- e.g. "raise test coverage to 80%"
  metric      text,                     -- how success is measured
  target      text,
  status      text not null default 'active',   -- active | met | paused
  priority    int not null default 100,
  created_at  timestamptz not null default now()
);
alter table goals enable row level security;
do $$ begin
  execute 'drop policy if exists goals_auth on goals';
  execute 'create policy goals_auth on goals for select to authenticated using (true)';
  execute 'drop policy if exists goals_write on goals';
  execute 'create policy goals_write on goals for insert to authenticated with check (true)';
end $$;
alter publication supabase_realtime add table goals;

-- semantic result cache: reuse near-identical task results, save tokens
create table if not exists result_cache (
  signature   text primary key,         -- hash(project + normalized prompt + base commit)
  project     text, slug text,
  branch      text, summary text,
  hits        int not null default 0,
  created_at  timestamptz not null default now(),
  last_used   timestamptz
);
alter table result_cache enable row level security;
do $$ begin
  execute 'drop policy if exists cache_auth on result_cache';
  execute 'create policy cache_auth on result_cache for select to authenticated using (true)';
end $$;

-- portfolio health score per project
create or replace view v_project_health as
with t as (
  select p.name as project,
    count(*) filter (where tk.state in ('BLOCKED','CONFLICT','TESTFAIL')) as blocked,
    count(*) filter (where tk.state in ('RUNNING','QUEUED','WAITING')) as active,
    count(*) filter (where tk.state in ('DONE','MERGED')) as done
  from projects p left join tasks tk on tk.project_id = p.id group by p.name
),
a as (select project, count(*) as open_approvals from approvals where status='pending' group by project),
s as (select project, spent from v_spend_mtd),
b as (select project, monthly_usd_cap from budgets)
select p.name as project,
  coalesce(t.blocked,0) as blocked, coalesce(t.active,0) as active, coalesce(t.done,0) as done,
  coalesce(a.open_approvals,0) as open_approvals,
  coalesce(s.spent,0) as spent, b.monthly_usd_cap as cap,
  greatest(0, 100
    - coalesce(t.blocked,0)*15
    - coalesce(a.open_approvals,0)*5
    - (case when b.monthly_usd_cap is not null and coalesce(s.spent,0) >= b.monthly_usd_cap then 20 else 0 end)
  ) as health_score
from projects p
left join t on t.project=p.name left join a on a.project=p.name
left join s on s.project=p.name left join b on b.project=p.name;

-- unified action inbox: everything needing a human, ranked
create or replace view v_action_inbox as
  select 'approval' as type, id::text as ref, project, kind as label, title as detail,
         created_at, (case kind when 'secret' then 1 when 'material' then 2 else 3 end) as priority
  from approvals where status='pending'
  union all
  select 'blocked_task', id::text, (select name from projects where id=tasks.project_id),
         state::text, slug || ' — ' || coalesce(note,''), updated_at, 2
  from tasks where state in ('BLOCKED','CONFLICT','TESTFAIL')
  order by priority asc, created_at asc;;
