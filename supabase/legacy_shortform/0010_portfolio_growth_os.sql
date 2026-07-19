-- 0010_portfolio_growth_os.sql
-- Portfolio Growth OS: cross-app event bus + momentum engine + segmentation tree
-- + bandit arms + content pipeline, layered on the existing orchestrator control plane.
--
-- Design notes
-- - Lives in the orchestrator Supabase (control plane), NOT in any product DB, so it is
--   the ONE place that sees all apps at once. Products emit events here via emit_growth_event().
-- - PRIVACY: no PII ever. Actors are stored as an opaque hash (actor_hash). Event payloads
--   carry metadata only (segment, value, counts) — mirrors the orchestrator's privacy.scrub()
--   invariant and the app_triage "metadata not payloads" rule.
-- - Reuses existing tables: tasks(kind='gtm') is the machine/human action queue; approvals is
--   the human gate; outcomes already ledgers $ per task. This migration adds the growth-specific
--   state and the momentum math on top.
-- - Idempotent: safe to re-run (create ... if not exists, create or replace, guarded policies).

-- ---------------------------------------------------------------------------
-- 1. App registry (GTM metadata layered over projects)
-- ---------------------------------------------------------------------------
create table if not exists growth_apps (
  app             text primary key,                 -- matches projects.name
  display_name    text,
  tier            text not null default 'longtail', -- spearhead | cluster | longtail | infra
  cluster         text,                             -- shared-audience grouping key (nullable)
  stage           text not null default 'prelaunch',-- prelaunch | live | scaling | paused
  audience        text,                             -- one-line ICP description
  north_star      text,                             -- the single metric that defines momentum
  monetization    text,                             -- txn | subscription | flatfee | handle | other
  enabled         boolean not null default true,
  meta            jsonb not null default '{}',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 2. The event bus (append-only, deduped, no PII)
-- ---------------------------------------------------------------------------
-- Canonical funnel event types (open enum — apps may add, but keep names STABLE,
-- they are the optimization key just like app_triage operation names):
--   impression, visit, signup, activate, qualified_lead, opportunity,
--   revenue, expansion, churn, refund, content_published, referral, nps
create table if not exists growth_events (
  id          bigint generated always as identity primary key,
  app         text not null,
  event_type  text not null,
  ts          timestamptz not null default now(),
  segment     text,                     -- optional segment path (see growth_segments.path)
  channel     text,                     -- organic | paid | referral | content | outbound | direct
  source      text,                     -- utm-source-ish free text
  actor_hash  text,                     -- sha256(app || user id || salt) — NEVER raw id
  value       numeric(14,4) default 0,  -- revenue/amount for monetary events; else 0
  props       jsonb not null default '{}',
  dedup_key   text,                     -- app-supplied idempotency key
  created_at  timestamptz not null default now()
);
create unique index if not exists growth_events_dedup_uq
  on growth_events (app, dedup_key) where dedup_key is not null;
create index if not exists growth_events_app_ts_idx  on growth_events (app, ts desc);
create index if not exists growth_events_type_ts_idx on growth_events (event_type, ts desc);
create index if not exists growth_events_seg_idx     on growth_events (segment) where segment is not null;

-- Safe ingestion RPC: apps call this with the anon key; SECURITY DEFINER writes the row.
-- Rejects anything that looks like PII in actor_hash (must be hex-ish, no '@').
create or replace function emit_growth_event(
  p_app text,
  p_event_type text,
  p_segment text default null,
  p_channel text default null,
  p_source text default null,
  p_actor_hash text default null,
  p_value numeric default 0,
  p_props jsonb default '{}',
  p_dedup_key text default null
) returns bigint
language plpgsql security definer set search_path = public as $$
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

-- ---------------------------------------------------------------------------
-- 3. Momentum engine — the solo-operator attention allocator
-- ---------------------------------------------------------------------------
-- Stores one scored snapshot per app per run. The cockpit reads the latest snapshot.
create table if not exists growth_momentum (
  id           bigint generated always as identity primary key,
  app          text not null,
  as_of        timestamptz not null default now(),
  score        numeric(10,4) not null default 0,   -- composite 0..100
  rank         int,
  trend        text,                                -- rising | steady | cooling
  components   jsonb not null default '{}',         -- {growth, revenue_velocity, conversion, ...}
  created_at   timestamptz not null default now()
);
create index if not exists growth_momentum_asof_idx on growth_momentum (as_of desc);
create index if not exists growth_momentum_app_idx   on growth_momentum (app, as_of desc);

-- Composite momentum: trailing 7d vs prior 7d across the core funnel, normalized 0..100.
-- Weighting favors revenue velocity, then qualified pipeline, then top-of-funnel growth.
create or replace function compute_growth_momentum()
returns void language plpgsql as $$
declare
  r record;
  v_rank int := 0;
begin
  create temp table _m on commit drop as
  with base as (
    select a.app,
      -- current 7d
      count(*) filter (where e.event_type='visit'          and e.ts >= now()-interval '7 days')  as visits_c,
      count(*) filter (where e.event_type='signup'         and e.ts >= now()-interval '7 days')  as signups_c,
      count(*) filter (where e.event_type='qualified_lead' and e.ts >= now()-interval '7 days')  as ql_c,
      coalesce(sum(e.value) filter (where e.event_type in ('revenue','expansion') and e.ts >= now()-interval '7 days'),0) as rev_c,
      -- prior 7d
      count(*) filter (where e.event_type='visit'          and e.ts >= now()-interval '14 days' and e.ts < now()-interval '7 days') as visits_p,
      count(*) filter (where e.event_type='signup'         and e.ts >= now()-interval '14 days' and e.ts < now()-interval '7 days') as signups_p,
      count(*) filter (where e.event_type='qualified_lead' and e.ts >= now()-interval '14 days' and e.ts < now()-interval '7 days') as ql_p,
      coalesce(sum(e.value) filter (where e.event_type in ('revenue','expansion') and e.ts >= now()-interval '14 days' and e.ts < now()-interval '7 days'),0) as rev_p
    from growth_apps a
    left join growth_events e on e.app = a.app
    where a.enabled and a.tier <> 'infra'
    group by a.app
  ),
  scored as (
    select app, visits_c, signups_c, ql_c, rev_c,
      -- growth ratios, clamped; +1 smoothing to avoid div/0
      least( (visits_c+1.0)/(visits_p+1.0), 5)   as g_visits,
      least( (signups_c+1.0)/(signups_p+1.0), 5) as g_signups,
      least( (ql_c+1.0)/(ql_p+1.0), 5)           as g_ql,
      least( (rev_c+1.0)/(rev_p+1.0), 5)         as g_rev,
      case when visits_c>0 then (signups_c::numeric/visits_c) else 0 end as conv
    from base
  )
  select app, visits_c, signups_c, ql_c, rev_c, g_visits, g_signups, g_ql, g_rev, conv,
    -- composite, weighted then mapped ~0..100 (growth of 1.0 = flat = ~40; 5x = ~100)
    round( least(100, greatest(0,
        (0.40*g_rev + 0.25*g_ql + 0.20*g_signups + 0.15*g_visits) * 20
        + (conv*10)
    )), 2) as score,
    case
      when (0.40*g_rev + 0.25*g_ql + 0.20*g_signups + 0.15*g_visits) > 1.15 then 'rising'
      when (0.40*g_rev + 0.25*g_ql + 0.20*g_signups + 0.15*g_visits) < 0.90 then 'cooling'
      else 'steady' end as trend
  from scored;

  for r in select * from _m order by score desc loop
    v_rank := v_rank + 1;
    insert into growth_momentum(app, score, rank, trend, components)
    values (r.app, r.score, v_rank, r.trend,
      jsonb_build_object(
        'visits_7d', r.visits_c, 'signups_7d', r.signups_c,
        'qualified_leads_7d', r.ql_c, 'revenue_7d', r.rev_c,
        'g_revenue', round(r.g_rev,2), 'g_qualified', round(r.g_ql,2),
        'g_signups', round(r.g_signups,2), 'g_visits', round(r.g_visits,2),
        'signup_conversion', round(r.conv,4)
      ));
  end loop;
end $$;

-- Convenience view: latest momentum snapshot per app, joined to registry.
create or replace view growth_momentum_latest as
select m.app, a.display_name, a.tier, a.cluster, a.stage, a.north_star,
       m.score, m.rank, m.trend, m.components, m.as_of
from growth_momentum m
join lateral (
  select max(as_of) as_of from growth_momentum m2 where m2.app = m.app
) last on last.as_of = m.as_of
left join growth_apps a on a.app = m.app
order by m.rank;

-- ---------------------------------------------------------------------------
-- 4. Segmentation tree — bot-curated strategy per app/service/archetype/segment
-- ---------------------------------------------------------------------------
create table if not exists growth_segments (
  id            uuid primary key default gen_random_uuid(),
  app           text not null,
  product       text,                 -- service/product within the app
  archetype     text,                 -- buyer archetype
  micro_segment text,                 -- behavioral/firmographic sub-slice
  path          text unique,          -- e.g. apparently/licensing/dfs-startup/urgent-nj-pa
  positioning   text,                 -- the angle for this leaf
  message       text,                 -- headline/promise
  channel       text,                 -- best channel for this leaf
  offer         text,                 -- the hook/offer
  landing_variant text,               -- variant key / url
  status        text not null default 'proposed', -- proposed | live | paused | won | retired
  curated_by    text default 'growth-bot',
  meta          jsonb not null default '{}',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists growth_segments_app_idx on growth_segments (app, status);

-- ---------------------------------------------------------------------------
-- 5. Bandit arms — per-segment experiment allocation (UCB1, matches orchestrator)
-- ---------------------------------------------------------------------------
create table if not exists growth_arms (
  id           uuid primary key default gen_random_uuid(),
  segment_id   uuid references growth_segments(id) on delete cascade,
  arm          text not null,            -- variant name
  variant      jsonb not null default '{}', -- copy/creative/offer payload
  impressions  bigint not null default 0,
  conversions  bigint not null default 0,
  reward_sum   numeric(14,4) not null default 0, -- e.g. $ or weighted value
  status       text not null default 'active', -- active | paused | winner | killed
  created_at   timestamptz not null default now(),
  unique (segment_id, arm)
);

-- UCB1 selection: pick the arm to serve next for a segment.
create or replace function pick_growth_arm(p_segment_id uuid)
returns growth_arms language plpgsql as $$
declare total bigint; chosen growth_arms;
begin
  select coalesce(sum(impressions),0) into total from growth_arms
    where segment_id = p_segment_id and status='active';
  -- serve any unexplored arm first
  select * into chosen from growth_arms
    where segment_id=p_segment_id and status='active' and impressions=0 limit 1;
  if found then return chosen; end if;
  -- else UCB1: mean reward + sqrt(2 ln N / n)
  select * into chosen from growth_arms
    where segment_id=p_segment_id and status='active'
    order by (reward_sum/nullif(impressions,0)) + sqrt(2*ln(greatest(total,1))/nullif(impressions,1)) desc
    limit 1;
  return chosen;
end $$;

-- ---------------------------------------------------------------------------
-- 6. Content / SEO pipeline (corpus-fed) — draft→cite-check→review→publish→repurpose
-- ---------------------------------------------------------------------------
create table if not exists growth_content (
  id            uuid primary key default gen_random_uuid(),
  app           text not null,
  topic         text not null,
  target_segment text,               -- growth_segments.path this content serves
  primary_keyword text,
  gap_demand    int default 0,        -- from corpus query-log gap detector (demand signal)
  corpus_refs   jsonb not null default '[]', -- citation doc ids from the app corpus
  status        text not null default 'gap_detected',
                -- gap_detected | drafting | cite_check | review | approved | published | repurposed | rejected
  quality_score numeric(6,3),
  url           text,
  task_id       uuid references tasks(id) on delete set null, -- the gtm task doing the work
  approval_id   uuid,                 -- the human review gate (approvals.id)
  derivatives   jsonb not null default '[]', -- newsletter/social/landing spawned from this
  meta          jsonb not null default '{}',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists growth_content_app_status_idx on growth_content (app, status);
create index if not exists growth_content_demand_idx on growth_content (gap_demand desc);

-- ---------------------------------------------------------------------------
-- 7. Human action feed for Smarter — one view over gtm tasks + open approvals
-- ---------------------------------------------------------------------------
create or replace view growth_action_feed as
select
  'task'::text as item_kind, t.id::text as item_id, p.name as app, t.slug as title,
  t.state::text as status, t.note as detail, t.created_at
from tasks t join projects p on p.id = t.project_id
where t.kind='gtm' and t.state in ('QUEUED','WAITING','BLOCKED','RETRY')
union all
select
  'approval'::text, a.id::text, a.project, a.title, a.status::text, a.why, a.created_at
from approvals a where a.status='pending'
  and (a.kind in ('gtm','proposal','material') )
order by created_at desc;

-- ---------------------------------------------------------------------------
-- 8. RLS — enable everywhere; service role writes (no policy), authenticated reads.
--    emit_growth_event is SECURITY DEFINER so anon apps can log without table grants.
-- ---------------------------------------------------------------------------
do $$
declare tbl text;
begin
  foreach tbl in array array[
    'growth_apps','growth_events','growth_momentum','growth_segments',
    'growth_arms','growth_content'
  ] loop
    execute format('alter table %I enable row level security', tbl);
    -- authenticated read (dashboard/cockpit)
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    -- authenticated write for curation surfaces (segments/arms/content/apps); events/momentum stay service-role + RPC
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

-- ---------------------------------------------------------------------------
-- 9. Seed the app registry from the known portfolio (edit tiers as strategy evolves)
-- ---------------------------------------------------------------------------
insert into growth_apps (app, display_name, tier, cluster, stage, audience, north_star, monetization) values
  ('tomorrow','Tomorrow',   'spearhead','risk',    'prelaunch','Community banks, corporate treasuries, insurers','qualified_lead','txn'),
  ('apparently','Apparently','spearhead','gaming',  'live',     'Gaming vendors/operators needing multi-state compliance','revenue','flatfee'),
  ('smarter','Smarter',      'cluster',  'dealflow','prelaunch','Founders, dealmakers, small-firm & in-house counsel','signup','subscription'),
  ('pareto-2080','Pareto',   'cluster',  'wealth',  'prelaunch','HNW/early-retirees/high-earners','signup','subscription'),
  ('racefeed','Galop',       'longtail', 'gaming',  'prelaunch','Millennial/Gen-Z racing entertainment','activate','handle'),
  ('darwn','Darwn',          'longtail', 'markets', 'prelaunch','Traders in human-capital markets (healthcare/legal)','signup','txn'),
  ('claude-orchestrator','Beethoven','infra',null,  'live',     'Internal control plane','n/a','other')
on conflict (app) do update set
  display_name=excluded.display_name, tier=excluded.tier, cluster=excluded.cluster,
  audience=excluded.audience, north_star=excluded.north_star, monetization=excluded.monetization,
  updated_at=now();

-- Done. Next: apps call emit_growth_event(...); schedule compute_growth_momentum() (loops table
-- or cron) every ~15 min; cockpit reads growth_momentum_latest; Smarter reads growth_action_feed.
