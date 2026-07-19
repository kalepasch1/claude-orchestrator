-- 0011_growth_os_improvements.sql
-- Applies the approved 20-500X improvements on top of 0010 (excludes cross-app rewards currency).
--   1  GTM plays as reusable capabilities (compounding across apps)
--   3  Attestation as a conversion asset
--   5  Consented identity graph + event-driven warm handoffs (default-deny consent)
--   6  Confidence-gated bandit arms (Wilson interval)
--   7  Momentum -> auto-staged weekly GTM plan
--   8  "Answered-demand" north-star KPI
-- (Improvement 2, triage-routed generation, is orchestrator runtime — see growth-os/lib/generate.py)
-- Idempotent.

-- ============================================================ 1. GTM PLAYS ===
-- A portfolio-level playbook registry. A winning arm in one app becomes a proven play any app
-- can instantiate in one call. Mirrors the code capability registry (embedding for semantic reuse).
create table if not exists growth_plays (
  id           uuid primary key default gen_random_uuid(),
  name         text not null,
  kind         text not null,                 -- landing | sequence | content_template | pricing_test | offer | creative
  origin_app   text,
  origin_segment text,
  spec         jsonb not null default '{}',   -- the reusable variant/definition
  win_evidence jsonb not null default '{}',   -- stats that justified promotion
  status       text not null default 'candidate', -- candidate | proven | retired
  version      int not null default 1,
  embedding    vector(1536),                  -- nullable; semantic dedup/search
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (name, version)
);
create index if not exists growth_plays_kind_idx on growth_plays (kind, status);

-- Snapshot a winning arm into a proven play.
create or replace function promote_arm_to_play(p_arm_id uuid, p_name text, p_kind text)
returns uuid language plpgsql as $$
declare a growth_arms; s growth_segments; pid uuid;
begin
  select * into a from growth_arms where id = p_arm_id;
  if not found then raise exception 'arm % not found', p_arm_id; end if;
  select * into s from growth_segments where id = a.segment_id;
  insert into growth_plays(name, kind, origin_app, origin_segment, spec, win_evidence, status)
  values (p_name, p_kind, s.app, s.path, a.variant,
    jsonb_build_object('impressions',a.impressions,'conversions',a.conversions,
      'reward_sum',a.reward_sum,
      'conv_rate', case when a.impressions>0 then round(a.conversions::numeric/a.impressions,4) else 0 end),
    'proven')
  returning id into pid;
  return pid;
end $$;

-- Instantiate a proven play into a target app/segment (creates the segment + a seed arm).
create or replace function instantiate_play(p_play_id uuid, p_app text, p_segment_path text, p_product text default null)
returns uuid language plpgsql as $$
declare pl growth_plays; seg_id uuid;
begin
  select * into pl from growth_plays where id = p_play_id;
  if not found then raise exception 'play % not found', p_play_id; end if;
  insert into growth_segments(app, product, path, positioning, status, curated_by, meta)
  values (p_app, p_product, p_segment_path, pl.name, 'proposed', 'play:'||pl.id,
          jsonb_build_object('from_play', pl.id, 'from_app', pl.origin_app))
  on conflict (path) do update set updated_at=now()
  returning id into seg_id;
  insert into growth_arms(segment_id, arm, variant, status)
  values (seg_id, 'play-'||left(pl.id::text,8), pl.spec, 'active')
  on conflict (segment_id, arm) do nothing;
  return seg_id;
end $$;

-- ==================================================== 3. ATTESTATION ASSET ===
-- Verifiable, signed claims (cite-N-authorities, market-neutral, etc.). Signing is done by the
-- Darwin kernel with the shared PROOF_SIGNING key off-DB; we store the signed payload + verifier url.
create table if not exists growth_attestations (
  id           uuid primary key default gen_random_uuid(),
  app          text not null,
  subject_kind text not null,               -- content | opinion | claim | hedge
  subject_id   text,                        -- growth_content.id / opinion id / etc.
  claim        text not null,
  evidence     jsonb not null default '{}', -- corpus doc ids / proof references
  signature    text,                        -- detached signature from darwin kernel
  signed_at    timestamptz,
  verifier_url text,                        -- public verify endpoint
  status       text not null default 'draft', -- draft | signed | published | revoked
  created_at   timestamptz not null default now()
);
create index if not exists growth_attestations_app_idx on growth_attestations (app, status);

-- =============================================== 5. CONSENT + WARM HANDOFFS ===
-- Default-DENY consent: a handoff to another app only fires if an explicit consent row exists.
create table if not exists growth_consent (
  actor_hash text not null,
  scope      text not null,                 -- target app or 'portfolio'
  granted_at timestamptz not null default now(),
  source     text,
  primary key (actor_hash, scope)
);

create or replace function has_cross_sell_consent(p_actor_hash text, p_to_app text)
returns boolean language sql stable as $$
  select exists(
    select 1 from growth_consent
    where actor_hash = p_actor_hash and scope in (p_to_app, 'portfolio')
  );
$$;

-- Rules: "when this event happens on from_app in this segment, that person fits to_app".
create table if not exists growth_handoff_rules (
  id            uuid primary key default gen_random_uuid(),
  from_app      text not null,
  when_event    text not null default 'qualified_lead',
  segment_like  text,                        -- ILIKE pattern on event.segment (nullable = any)
  to_app        text not null,
  to_segment    text,
  reason        text,
  min_value     numeric default 0,
  enabled       boolean not null default true,
  created_at    timestamptz not null default now()
);

create table if not exists growth_handoffs (
  id             uuid primary key default gen_random_uuid(),
  from_app       text not null,
  to_app         text not null,
  actor_hash     text,
  reason         text,
  source_event_id bigint,
  status         text not null default 'created', -- created | consented_skip | routed
  created_at     timestamptz not null default now()
);

-- Scan recent events against rules; for CONSENTED actors, create a handoff + a qualified_lead on
-- the target app. No consent -> record the miss as 'consented_skip' (no cross-app data movement).
create or replace function detect_cross_sell(p_lookback interval default interval '1 day')
returns int language plpgsql as $$
declare rec record; n int := 0; consented boolean;
begin
  for rec in
    select e.id, e.app, e.event_type, e.segment, e.actor_hash, e.value, r.to_app, r.to_segment, r.reason
    from growth_events e
    join growth_handoff_rules r
      on r.enabled and r.from_app = e.app and r.when_event = e.event_type
     and (r.segment_like is null or e.segment ilike r.segment_like)
     and coalesce(e.value,0) >= r.min_value
    where e.ts >= now() - p_lookback
      and not exists (
        select 1 from growth_handoffs h
        where h.source_event_id = e.id and h.to_app = r.to_app)
  loop
    consented := rec.actor_hash is not null and has_cross_sell_consent(rec.actor_hash, rec.to_app);
    insert into growth_handoffs(from_app, to_app, actor_hash, reason, source_event_id, status)
    values (rec.app, rec.to_app, rec.actor_hash, rec.reason, rec.id,
            case when consented then 'routed' else 'consented_skip' end);
    if consented then
      insert into growth_events(app, event_type, segment, channel, source, actor_hash, props)
      values (rec.to_app, 'qualified_lead', rec.to_segment, 'referral',
              'handoff:'||rec.app, rec.actor_hash,
              jsonb_build_object('reason', rec.reason, 'from_app', rec.app));
      n := n + 1;
    end if;
  end loop;
  return n;
end $$;

-- ============================================ 6. CONFIDENCE-GATED ARMS ======
-- Wilson score interval on conversion rate. Graduate winners, kill clear losers.
create or replace view growth_arm_stats as
select a.id, a.segment_id, a.arm, a.status, a.impressions, a.conversions,
  case when a.impressions>0 then a.conversions::numeric/a.impressions else 0 end as rate,
  case when a.impressions>0 then
    ( (a.conversions::numeric/a.impressions) + (1.96^2)/(2*a.impressions)
      - 1.96*sqrt( ((a.conversions::numeric/a.impressions)*(1-(a.conversions::numeric/a.impressions)) + (1.96^2)/(4*a.impressions)) / a.impressions ) )
    / (1 + (1.96^2)/a.impressions)
  else 0 end as wilson_lb,
  case when a.impressions>0 then
    ( (a.conversions::numeric/a.impressions) + (1.96^2)/(2*a.impressions)
      + 1.96*sqrt( ((a.conversions::numeric/a.impressions)*(1-(a.conversions::numeric/a.impressions)) + (1.96^2)/(4*a.impressions)) / a.impressions ) )
    / (1 + (1.96^2)/a.impressions)
  else 1 end as wilson_ub
from growth_arms a;

-- For each segment: an arm whose Wilson lower bound beats every other arm's Wilson upper bound
-- (with enough samples) becomes 'winner'; arms whose upper bound trails the leader's lower bound
-- are 'killed'. Returns count of status changes.
create or replace function evaluate_growth_arms(p_min_impressions bigint default 200)
returns int language plpgsql as $$
declare seg uuid; leader record; n int := 0; rc int;
begin
  for seg in select distinct segment_id from growth_arms where status='active' loop
    select * into leader from growth_arm_stats
      where segment_id=seg and impressions >= p_min_impressions
      order by wilson_lb desc limit 1;
    if leader.id is null then continue; end if; -- not enough data yet; keep exploring
    -- promote clear leader
    if (select count(*) from growth_arm_stats s
        where s.segment_id=seg and s.id<>leader.id and s.wilson_ub >= leader.wilson_lb) = 0 then
      update growth_arms set status='winner' where id=leader.id and status<>'winner';
      if found then n := n+1; end if;
    end if;
    -- kill clear losers
    update growth_arms a set status='killed'
      from growth_arm_stats s
     where a.id=s.id and a.segment_id=seg and a.status='active' and a.id<>leader.id
       and s.impressions >= p_min_impressions and s.wilson_ub < leader.wilson_lb;
    get diagnostics rc = row_count;
    n := n + rc;
  end loop;
  return n;
end $$;

-- ============================================= 7. MOMENTUM -> WEEKLY PLAN ====
-- Stage concrete gtm tasks for the top-momentum apps this week (idempotent per ISO week).
create or replace function plan_growth_week(p_top int default 2)
returns int language plpgsql as $$
declare rec record; pid uuid; wk text := to_char(now(),'IYYY-"W"IW'); n int := 0; sl text;
begin
  for rec in
    select ml.app, ml.display_name, ml.rank, ml.score, ml.trend, ml.north_star
    from growth_momentum_latest ml
    where ml.tier <> 'infra'
    order by ml.rank limit p_top
  loop
    select id into pid from projects where name = rec.app;
    if pid is null then continue; end if;
    sl := 'gtm-week-'||rec.app||'-'||wk;
    if exists (select 1 from tasks where project_id=pid and slug=sl) then continue; end if;
    insert into tasks(project_id, slug, prompt, kind, state, note)
    values (pid, sl,
      format('WEEKLY GTM FOCUS (%s) for %s — momentum rank #%s, score %s, trend %s. North star: %s.'
        || E'\nDecompose this week into concrete growth experiments: (1) refresh/launch the top segments'
        || ' and their bandit arms, (2) publish the highest-demand corpus-fed content, (3) run the'
        || ' inbound->AI-draft loop, (4) review losing arms for kill/iterate. File each as a gtm sub-task'
        || ' and route human approvals to Smarter.',
        wk, rec.display_name, rec.rank, rec.score, rec.trend, coalesce(rec.north_star,'n/a')),
      'gtm','QUEUED', 'auto-planned by plan_growth_week');
    n := n + 1;
  end loop;
  return n;
end $$;

-- ============================================ 8. ANSWERED-DEMAND KPI =========
create or replace view growth_answered_demand as
select app,
  count(*) filter (where status='published')                          as published,
  count(*) filter (where status not in ('published','rejected'))      as in_pipeline,
  count(*)                                                            as total_tracked,
  round( 100.0 * count(*) filter (where status='published')
         / nullif(count(*) filter (where status <> 'rejected'),0), 1) as answered_rate_pct,
  coalesce(sum(gap_demand) filter (where status='published'),0)       as demand_answered,
  coalesce(sum(gap_demand) filter (where status <> 'rejected'),0)     as demand_total
from growth_content group by app;

-- ==================================================== RLS + GRANTS ==========
do $$
declare tbl text;
begin
  foreach tbl in array array['growth_plays','growth_attestations','growth_consent',
                             'growth_handoff_rules','growth_handoffs'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;

grant execute on function promote_arm_to_play(uuid,text,text) to authenticated, service_role;
grant execute on function instantiate_play(uuid,text,text,text) to authenticated, service_role;
grant execute on function has_cross_sell_consent(text,text) to authenticated, service_role;
grant execute on function detect_cross_sell(interval) to authenticated, service_role;
grant execute on function evaluate_growth_arms(bigint) to authenticated, service_role;
grant execute on function plan_growth_week(int) to authenticated, service_role;

-- Seed a couple of cross-sell rules (fire only for consented actors) so the graph is live.
insert into growth_handoff_rules (from_app, when_event, segment_like, to_app, to_segment, reason, min_value)
values
  ('apparently','revenue','%gaming%','racefeed','racefeed/b2b/operator','Gaming operator -> white-label ADW',0),
  ('pareto-2080','qualified_lead',null,'tomorrow','tomorrow/insurance-replacement/hnw','HNW planner -> parametric insurance replacement',0)
on conflict do nothing;
