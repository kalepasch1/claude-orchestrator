-- 0016_growth_intelligence.sql
-- Portfolio budget controller (+ circuit breaker), predictive lead scoring, cross-app next-best-
-- product, and the auto case-study loop. Idempotent.

-- ---- Portfolio budget controller ----
create table if not exists growth_budget (
  scope      text not null,                 -- 'app' | 'segment'
  key        text not null,
  allocation numeric(14,2) not null default 0,
  spend      numeric(14,2) not null default 0,
  cap        numeric(14,2),
  status     text not null default 'active',-- active | paused (circuit breaker)
  updated_at timestamptz not null default now(),
  primary key (scope, key)
);

-- Reallocate a total budget across non-infra apps by momentum (proxy for marginal profit).
create or replace function rebalance_budget(p_total numeric)
returns int language plpgsql as $$
declare tot numeric; n int := 0; rec record;
begin
  select sum(score) into tot from growth_momentum_latest where tier <> 'infra' and score > 0;
  if coalesce(tot,0) = 0 then return 0; end if;
  for rec in select app, score from growth_momentum_latest where tier <> 'infra' and score > 0 loop
    insert into growth_budget(scope,key,allocation,updated_at)
    values ('app', rec.app, round(p_total * rec.score/tot, 2), now())
    on conflict (scope,key) do update set allocation=excluded.allocation, updated_at=now()
    where growth_budget.status='active';
    n := n + 1;
  end loop;
  return n;
end $$;

-- Circuit breaker: pause any app/segment spending with zero conversions in the window.
create or replace function check_cac_circuit(p_window interval default interval '7 days', p_min_spend numeric default 100)
returns int language plpgsql as $$
declare rec record; n int := 0; convs int;
begin
  for rec in select scope,key,spend from growth_budget where status='active' and spend >= p_min_spend loop
    if rec.scope='app' then
      select count(*) into convs from growth_events
        where app=rec.key and event_type in ('signup','revenue') and ts >= now()-p_window;
    else
      select count(*) into convs from growth_events
        where segment=rec.key and event_type in ('signup','revenue') and ts >= now()-p_window;
    end if;
    if convs = 0 then
      update growth_budget set status='paused', updated_at=now() where scope=rec.scope and key=rec.key;
      n := n + 1;
    end if;
  end loop;
  return n;
end $$;

-- ---- Predictive lead scoring (fit x intent x recency), 0..100 ----
create or replace function score_lead(p_actor_hash text)
returns numeric language sql stable as $$
  with e as (select event_type, ts from growth_events where actor_hash = p_actor_hash)
  select least(100, round(
      20.0 * (select count(*) from e where event_type='qualified_lead')
    + 12.0 * (select count(*) from e where event_type='activate')
    +  6.0 * (select count(*) from e where event_type='signup')
    +  2.0 * (select count(*) from e where event_type='visit')
    + 30.0 * (case when exists(select 1 from e where ts >= now()-interval '3 days') then 1 else 0 end)
  , 1));
$$;

create or replace view growth_lead_scores as
select actor_hash, score_lead(actor_hash) as score,
       max(ts) as last_seen, count(*) as touches
from growth_events where actor_hash is not null group by actor_hash;

-- ---- Cross-app next-best-product (via handoff rules + what they've already touched) ----
create or replace function next_best_product(p_actor_hash text)
returns text language sql stable as $$
  select r.to_app
  from growth_events e
  join growth_handoff_rules r on r.enabled and r.from_app = e.app and r.when_event = e.event_type
  where e.actor_hash = p_actor_hash
    and not exists (select 1 from growth_events e2 where e2.actor_hash=p_actor_hash and e2.app=r.to_app)
  group by r.to_app
  order by count(*) desc
  limit 1;
$$;

-- ---- Auto case-study loop: on a customer win, draft a case study + attestation + file the work ----
create or replace function on_customer_win(p_app text, p_actor_hash text, p_segment text, p_value numeric default 0)
returns uuid language plpgsql as $$
declare pid uuid; tid uuid; att uuid;
begin
  select id into pid from projects where name = p_app;
  if pid is not null then
    insert into tasks(project_id, slug, prompt, kind, state, note)
    values (pid, 'case-study-'||left(p_actor_hash,10)||'-'||to_char(now(),'YYYYMMDD'),
      format('Draft a case study + testimonial request for a %s win in segment %s (value %s). '
        || 'Use only approved, attestable facts; request the customer''s consent + quote; on approval '
        || 'publish and feed the content engine.', p_app, p_segment, p_value),
      'gtm','QUEUED','auto-filed by on_customer_win')
    on conflict do nothing returning id into tid;
  end if;
  insert into growth_attestations(app, subject_kind, subject_id, claim, evidence, status)
  values (p_app, 'claim', p_actor_hash, 'Customer success outcome (pending consent + verification)',
    jsonb_build_object('segment',p_segment,'value',p_value), 'draft')
  returning id into att;
  return coalesce(tid, att);
end $$;

-- ---- RLS + grants ----
do $$ begin
  execute 'alter table growth_budget enable row level security';
  execute 'drop policy if exists growth_budget_sel on growth_budget';
  execute 'create policy growth_budget_sel on growth_budget for select to authenticated using (true)';
  execute 'drop policy if exists growth_budget_ins on growth_budget';
  execute 'create policy growth_budget_ins on growth_budget for insert to authenticated with check (true)';
  execute 'drop policy if exists growth_budget_upd on growth_budget';
  execute 'create policy growth_budget_upd on growth_budget for update to authenticated using (true) with check (true)';
end $$;
grant execute on function rebalance_budget(numeric) to authenticated, service_role;
grant execute on function check_cac_circuit(interval,numeric) to authenticated, service_role;
grant execute on function score_lead(text) to authenticated, service_role;
grant execute on function next_best_product(text) to authenticated, service_role;
grant execute on function on_customer_win(text,text,text,numeric) to authenticated, service_role;

-- recurring driver for the autonomous BD tick (runner reads loops)
insert into loops (project, type, cadence_seconds, config)
values ('claude-orchestrator','bd_autopilot', 900, '{"loop":"bd_autopilot"}')
on conflict (project, type) do nothing;
