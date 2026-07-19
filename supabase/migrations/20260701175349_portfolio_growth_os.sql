-- 0010_portfolio_growth_os.sql
create table if not exists growth_apps (
  app text primary key, display_name text, tier text not null default 'longtail',
  cluster text, stage text not null default 'prelaunch', audience text, north_star text,
  monetization text, enabled boolean not null default true, meta jsonb not null default '{}',
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);

create table if not exists growth_events (
  id bigint generated always as identity primary key, app text not null, event_type text not null,
  ts timestamptz not null default now(), segment text, channel text, source text, actor_hash text,
  value numeric(14,4) default 0, props jsonb not null default '{}', dedup_key text,
  created_at timestamptz not null default now()
);
create unique index if not exists growth_events_dedup_uq on growth_events (app, dedup_key) where dedup_key is not null;
create index if not exists growth_events_app_ts_idx  on growth_events (app, ts desc);
create index if not exists growth_events_type_ts_idx on growth_events (event_type, ts desc);
create index if not exists growth_events_seg_idx     on growth_events (segment) where segment is not null;

create or replace function emit_growth_event(
  p_app text, p_event_type text, p_segment text default null, p_channel text default null,
  p_source text default null, p_actor_hash text default null, p_value numeric default 0,
  p_props jsonb default '{}', p_dedup_key text default null
) returns bigint language plpgsql security definer set search_path = public as $$
declare new_id bigint;
begin
  if p_actor_hash is not null and (position('@' in p_actor_hash) > 0 or length(p_actor_hash) < 16) then
    raise exception 'actor_hash must be an opaque hash, not PII';
  end if;
  insert into growth_events(app, event_type, segment, channel, source, actor_hash, value, props, dedup_key)
  values (p_app, lower(p_event_type), p_segment, p_channel, p_source, p_actor_hash, coalesce(p_value,0), coalesce(p_props,'{}'), p_dedup_key)
  on conflict (app, dedup_key) where dedup_key is not null do nothing
  returning id into new_id;
  return new_id;
end $$;

create table if not exists growth_momentum (
  id bigint generated always as identity primary key, app text not null,
  as_of timestamptz not null default now(), score numeric(10,4) not null default 0, rank int,
  trend text, components jsonb not null default '{}', created_at timestamptz not null default now()
);
create index if not exists growth_momentum_asof_idx on growth_momentum (as_of desc);
create index if not exists growth_momentum_app_idx   on growth_momentum (app, as_of desc);

create or replace function compute_growth_momentum()
returns void language plpgsql as $$
declare r record; v_rank int := 0;
begin
  create temp table _m on commit drop as
  with base as (
    select a.app,
      count(*) filter (where e.event_type='visit'          and e.ts >= now()-interval '7 days')  as visits_c,
      count(*) filter (where e.event_type='signup'         and e.ts >= now()-interval '7 days')  as signups_c,
      count(*) filter (where e.event_type='qualified_lead' and e.ts >= now()-interval '7 days')  as ql_c,
      coalesce(sum(e.value) filter (where e.event_type in ('revenue','expansion') and e.ts >= now()-interval '7 days'),0) as rev_c,
      count(*) filter (where e.event_type='visit'          and e.ts >= now()-interval '14 days' and e.ts < now()-interval '7 days') as visits_p,
      count(*) filter (where e.event_type='signup'         and e.ts >= now()-interval '14 days' and e.ts < now()-interval '7 days') as signups_p,
      count(*) filter (where e.event_type='qualified_lead' and e.ts >= now()-interval '14 days' and e.ts < now()-interval '7 days') as ql_p,
      coalesce(sum(e.value) filter (where e.event_type in ('revenue','expansion') and e.ts >= now()-interval '14 days' and e.ts < now()-interval '7 days'),0) as rev_p
    from growth_apps a left join growth_events e on e.app = a.app
    where a.enabled and a.tier <> 'infra' group by a.app
  ),
  scored as (
    select app, visits_c, signups_c, ql_c, rev_c,
      least((visits_c+1.0)/(visits_p+1.0),5) as g_visits,
      least((signups_c+1.0)/(signups_p+1.0),5) as g_signups,
      least((ql_c+1.0)/(ql_p+1.0),5) as g_ql,
      least((rev_c+1.0)/(rev_p+1.0),5) as g_rev,
      case when visits_c>0 then (signups_c::numeric/visits_c) else 0 end as conv
    from base
  )
  select app, visits_c, signups_c, ql_c, rev_c, g_visits, g_signups, g_ql, g_rev, conv,
    round(least(100,greatest(0,(0.40*g_rev+0.25*g_ql+0.20*g_signups+0.15*g_visits)*20+(conv*10))),2) as score,
    case when (0.40*g_rev+0.25*g_ql+0.20*g_signups+0.15*g_visits)>1.15 then 'rising'
         when (0.40*g_rev+0.25*g_ql+0.20*g_signups+0.15*g_visits)<0.90 then 'cooling'
         else 'steady' end as trend
  from scored;

  for r in select * from _m order by score desc loop
    v_rank := v_rank + 1;
    insert into growth_momentum(app, score, rank, trend, components)
    values (r.app, r.score, v_rank, r.trend, jsonb_build_object(
        'visits_7d', r.visits_c, 'signups_7d', r.signups_c, 'qualified_leads_7d', r.ql_c,
        'revenue_7d', r.rev_c, 'g_revenue', round(r.g_rev,2), 'g_qualified', round(r.g_ql,2),
        'g_signups', round(r.g_signups,2), 'g_visits', round(r.g_visits,2), 'signup_conversion', round(r.conv,4)));
  end loop;
end $$;

create or replace view growth_momentum_latest as
select m.app, a.display_name, a.tier, a.cluster, a.stage, a.north_star,
       m.score, m.rank, m.trend, m.components, m.as_of
from growth_momentum m
join lateral (select max(as_of) as_of from growth_momentum m2 where m2.app = m.app) last on last.as_of = m.as_of
left join growth_apps a on a.app = m.app order by m.rank;

create table if not exists growth_segments (
  id uuid primary key default gen_random_uuid(), app text not null, product text, archetype text,
  micro_segment text, path text unique, positioning text, message text, channel text, offer text,
  landing_variant text, status text not null default 'proposed', curated_by text default 'growth-bot',
  meta jsonb not null default '{}', created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index if not exists growth_segments_app_idx on growth_segments (app, status);

create table if not exists growth_arms (
  id uuid primary key default gen_random_uuid(), segment_id uuid references growth_segments(id) on delete cascade,
  arm text not null, variant jsonb not null default '{}', impressions bigint not null default 0,
  conversions bigint not null default 0, reward_sum numeric(14,4) not null default 0,
  status text not null default 'active', created_at timestamptz not null default now(), unique (segment_id, arm)
);

create or replace function pick_growth_arm(p_segment_id uuid)
returns growth_arms language plpgsql as $$
declare total bigint; chosen growth_arms;
begin
  select coalesce(sum(impressions),0) into total from growth_arms where segment_id = p_segment_id and status='active';
  select * into chosen from growth_arms where segment_id=p_segment_id and status='active' and impressions=0 limit 1;
  if found then return chosen; end if;
  select * into chosen from growth_arms where segment_id=p_segment_id and status='active'
    order by (reward_sum/nullif(impressions,0)) + sqrt(2*ln(greatest(total,1))/nullif(impressions,1)) desc limit 1;
  return chosen;
end $$;

create table if not exists growth_content (
  id uuid primary key default gen_random_uuid(), app text not null, topic text not null, target_segment text,
  primary_keyword text, gap_demand int default 0, corpus_refs jsonb not null default '[]',
  status text not null default 'gap_detected', quality_score numeric(6,3), url text,
  task_id uuid references tasks(id) on delete set null, approval_id uuid, derivatives jsonb not null default '[]',
  meta jsonb not null default '{}', created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index if not exists growth_content_app_status_idx on growth_content (app, status);
create index if not exists growth_content_demand_idx on growth_content (gap_demand desc);
create unique index if not exists growth_content_app_kw_uq on growth_content (app, primary_keyword) where primary_keyword is not null;

create or replace view growth_action_feed as
select 'task'::text as item_kind, t.id::text as item_id, p.name as app, t.slug as title,
       t.state::text as status, t.note as detail, t.created_at
from tasks t join projects p on p.id = t.project_id
where t.kind='gtm' and t.state in ('QUEUED','WAITING','BLOCKED','RETRY')
union all
select 'approval'::text, a.id::text, a.project, a.title, a.status::text, a.why, a.created_at
from approvals a where a.status='pending' and (a.kind in ('gtm','proposal','material'))
order by created_at desc;

do $$
declare tbl text;
begin
  foreach tbl in array array['growth_apps','growth_events','growth_momentum','growth_segments','growth_arms','growth_content'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    if tbl in ('growth_apps','growth_segments','growth_arms','growth_content') then
      execute format('drop policy if exists %I_ins on %I', tbl, tbl);
      execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
      execute format('drop policy if exists %I_upd on %I', tbl, tbl);
      execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
    end if;
  end loop;
end $$;

grant execute on function emit_growth_event(text,text,text,text,text,text,numeric,jsonb,text) to anon, authenticated;
grant execute on function compute_growth_momentum() to authenticated, service_role;
grant execute on function pick_growth_arm(uuid) to authenticated, service_role;

insert into growth_apps (app, display_name, tier, cluster, stage, audience, north_star, monetization) values
  ('tomorrow','Tomorrow','spearhead','risk','prelaunch','Community banks, corporate treasuries, insurers','qualified_lead','txn'),
  ('apparently','Apparently','spearhead','gaming','live','Gaming vendors/operators needing multi-state compliance','revenue','flatfee'),
  ('smarter','Smarter','cluster','dealflow','prelaunch','Founders, dealmakers, small-firm & in-house counsel','signup','subscription'),
  ('pareto-2080','Pareto','cluster','wealth','prelaunch','HNW/early-retirees/high-earners','signup','subscription'),
  ('racefeed','Galop','longtail','gaming','prelaunch','Millennial/Gen-Z racing entertainment','activate','handle'),
  ('darwn','Darwn','longtail','markets','prelaunch','Traders in human-capital markets (healthcare/legal)','signup','txn'),
  ('claude-orchestrator','Beethoven','infra',null,'live','Internal control plane','n/a','other')
on conflict (app) do update set display_name=excluded.display_name, tier=excluded.tier, cluster=excluded.cluster,
  audience=excluded.audience, north_star=excluded.north_star, monetization=excluded.monetization, updated_at=now();;
