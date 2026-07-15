-- 0022_growth_activation.sql
-- Closes the loop to dollars + the outside world: autonomous media-buy ingestion, serve-time
-- decisioning, revenue-attributed creative ROI, portfolio world-model priors, simulation-first gate,
-- voice-of-market listening, governance analytics, creative provenance, multi-tenant hook. Idempotent.

-- A) MEDIA BUYING: external ad accounts + per-campaign spend (connector fills these; we fold them in).
create table if not exists growth_ad_accounts (
  id uuid primary key default gen_random_uuid(), app text, platform text, external_id text,
  status text not null default 'connected', daily_cap numeric default 0, created_at timestamptz not null default now()
);
create table if not exists growth_ad_spend (
  id bigint generated always as identity primary key, app text, platform text, campaign text,
  arm_id uuid references growth_arms(id) on delete set null,
  spend numeric(14,2) default 0, impressions bigint default 0, clicks bigint default 0,
  conversions bigint default 0, revenue numeric(14,2) default 0,
  day date default current_date, synced boolean default false, created_at timestamptz not null default now()
);
-- Fold external ad performance into the event bus + budget spend, then update the arm's live counts.
create or replace function sync_ad_performance()
returns int language plpgsql as $$
declare rec record; n int := 0;
begin
  for rec in select * from growth_ad_spend where not synced loop
    if rec.conversions > 0 or rec.revenue > 0 then
      perform emit_growth_event(rec.app, 'revenue', null, rec.platform, rec.campaign, null,
                                coalesce(rec.revenue,0), jsonb_build_object('conversions',rec.conversions), 'ad-'||rec.id);
    end if;
    update growth_budget set spend = spend + coalesce(rec.spend,0), updated_at=now()
      where scope='app' and key=rec.app;
    if rec.arm_id is not null then
      update growth_arms set impressions = impressions + rec.impressions,
        conversions = conversions + rec.conversions, reward_sum = reward_sum + coalesce(rec.revenue,0)
        where id = rec.arm_id;
    end if;
    update growth_ad_spend set synced = true where id = rec.id;
    n := n + 1;
  end loop;
  perform check_cac_circuit();   -- trip breaker if spend has zero conversions
  return n;
end $$;

-- B) SERVE-TIME DECISION: pick the arm to serve a visitor (respects the creative gate + personalizes).
create or replace function serve_variant(p_app text, p_segment text, p_actor_hash text default null)
returns jsonb language plpgsql stable as $$
declare seg uuid; arm growth_arms; served jsonb;
begin
  select id into seg from growth_segments where path = p_segment;
  if seg is null then return jsonb_build_object('error','segment not found'); end if;
  arm := pick_growth_arm(seg);
  -- if the chosen arm carries a not-yet-approved visual, don't serve it
  if arm.id is not null and not creative_gate(arm.id) then
    return jsonb_build_object('arm', null, 'reason','creative pending approval');
  end if;
  served := jsonb_build_object(
    'arm_id', arm.id, 'arm', arm.arm, 'variant', arm.variant,
    'personalization', jsonb_build_object(
      'lead_score', case when p_actor_hash is not null then score_lead(p_actor_hash) else null end,
      'next_best_product', case when p_actor_hash is not null then next_best_product(p_actor_hash) else null end)
  );
  return served;
end $$;

-- C) REVENUE-ATTRIBUTED CREATIVE ROI (dollars, not just conversion).
create or replace view growth_creative_revenue as
select c.id, c.app, c.segment, c.title, c.cost_usd,
       a.impressions, a.conversions, a.reward_sum as revenue,
       round(a.reward_sum - c.cost_usd, 2) as net,
       case when c.cost_usd>0 then round(a.reward_sum / c.cost_usd, 2) else null end as roas
from growth_creative c join growth_arms a on a.id = c.arm_id
where c.status in ('approved','published');

-- D) PORTFOLIO WORLD-MODEL: learned priors that seed every new experiment.
create table if not exists growth_world_model (
  feature_key text primary key, expected_lift numeric(8,4), samples bigint default 0, updated_at timestamptz not null default now()
);
create or replace function refresh_world_model()
returns int language plpgsql as $$
declare n int := 0;
begin
  insert into growth_world_model(feature_key, expected_lift, samples, updated_at)
  select 'channel:'||coalesce(s.channel,'na'),
         round(avg(case when a.impressions>0 then a.conversions::numeric/a.impressions end),4),
         sum(a.impressions), now()
  from growth_arms a join growth_segments s on s.id=a.segment_id
  group by coalesce(s.channel,'na')
  on conflict (feature_key) do update set expected_lift=excluded.expected_lift,
    samples=excluded.samples, updated_at=now();
  get diagnostics n = row_count; return n;
end $$;
create or replace function prior_for(p_feature_key text)
returns numeric language sql stable as $$
  select expected_lift from growth_world_model where feature_key = p_feature_key;
$$;

-- E) SIMULATION-FIRST GATE: only proposals that clear the digital-twin sim graduate to live traffic.
create or replace function sim_gate(p_segment text, p_min_conv numeric default 0.02)
returns boolean language sql stable as $$
  select exists (select 1 from growth_sim where segment = p_segment and predicted_conv >= p_min_conv);
$$;

-- F) VOICE-OF-MARKET listening: trending external signals -> auto-spawn segments/campaigns.
create table if not exists growth_market_signal (
  id uuid primary key default gen_random_uuid(), source text, topic text not null, sentiment text,
  volume int default 0, trend text, app text, created_at timestamptz not null default now()
);
create or replace function spawn_from_signal(p_signal_id uuid)
returns text language plpgsql as $$
declare sig growth_market_signal; p text;
begin
  select * into sig from growth_market_signal where id = p_signal_id;
  if not found then raise exception 'signal % not found', p_signal_id; end if;
  p := coalesce(sig.app,'portfolio')||'/discovered/market-signal/'||left(regexp_replace(lower(sig.topic),'[^a-z0-9]+','-','g'),40);
  insert into growth_segments(app, path, positioning, status, curated_by, meta)
  values (coalesce(sig.app,'portfolio'), p, 'trending: '||sig.topic, 'proposed','market-listening',
          jsonb_build_object('signal', p_signal_id,'volume',sig.volume,'trend',sig.trend))
  on conflict (path) do nothing;
  return p;
end $$;

-- G) GOVERNANCE ANALYTICS: how often autonomy is right vs overridden, per surface.
create or replace view growth_governance_analytics as
select 'reply_triage' as surface,
       count(*) filter (where auto_handled) as auto_actions,
       count(*) filter (where auto_handled and human_edited) as overridden,
       round(1 - count(*) filter (where auto_handled and human_edited)::numeric
             / greatest(count(*) filter (where auto_handled),1),3) as accuracy
from growth_reply_triage
union all
select 'creative_auto_triage',
       count(*) filter (where source='ai'),
       count(*) filter (where source='ai' and status='rejected'),
       round(1 - count(*) filter (where source='ai' and status='rejected')::numeric
             / greatest(count(*) filter (where source='ai'),1),3)
from growth_creative;

-- H) CREATIVE PROVENANCE: sign each published asset with its brand-kit version + approval chain.
create table if not exists growth_provenance (
  id uuid primary key default gen_random_uuid(), creative_id uuid, app text, brand_kit_version int,
  approval_chain jsonb not null default '[]', signature text, created_at timestamptz not null default now()
);
create or replace function sign_asset(p_creative_id uuid)
returns uuid language plpgsql as $$
declare cr growth_creative; v int; chain jsonb; pid uuid;
begin
  select * into cr from growth_creative where id=p_creative_id;
  select version into v from growth_brand_kit where app=cr.app;
  select coalesce(jsonb_agg(jsonb_build_object('reviewer',reviewer,'decision',decision,'at',created_at)),'[]')
    into chain from growth_creative_review where creative_id=p_creative_id;
  insert into growth_provenance(creative_id, app, brand_kit_version, approval_chain, signature)
  values (p_creative_id, cr.app, v, chain, encode(sha256((p_creative_id::text||coalesce(v,0)::text)::bytea),'hex'))
  returning id into pid;
  return pid;
end $$;

-- I) MULTI-TENANT HOOK (externalize the Growth OS as a product).
create table if not exists growth_tenant (
  id uuid primary key default gen_random_uuid(), name text unique, plan text default 'internal',
  config jsonb not null default '{}', created_at timestamptz not null default now()
);
insert into growth_tenant(name, plan) values ('portfolio-internal','internal') on conflict do nothing;

-- ---- RLS + grants ----
do $$
declare tbl text;
begin
  foreach tbl in array array['growth_ad_accounts','growth_ad_spend','growth_world_model',
                             'growth_market_signal','growth_provenance','growth_tenant'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;
grant execute on function sync_ad_performance() to authenticated, service_role;
grant execute on function serve_variant(text,text,text) to authenticated, service_role;
grant execute on function refresh_world_model() to authenticated, service_role;
grant execute on function prior_for(text) to authenticated, service_role;
grant execute on function sim_gate(text,numeric) to authenticated, service_role;
grant execute on function spawn_from_signal(uuid) to authenticated, service_role;
grant execute on function sign_asset(uuid) to authenticated, service_role;
