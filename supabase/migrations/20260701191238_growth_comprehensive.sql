-- 0013_growth_comprehensive.sql
create table if not exists growth_competitor_intel (
  id uuid primary key default gen_random_uuid(), app text not null, competitor text not null,
  channel text, observation text, url text, captured_at timestamptz not null default now(), meta jsonb not null default '{}'
);
create index if not exists gci_app_idx on growth_competitor_intel (app, captured_at desc);

create table if not exists growth_synth_tests (
  id uuid primary key default gen_random_uuid(), proposal_id uuid references growth_proposals(id) on delete cascade,
  persona text, score numeric(5,4), verdict text, notes text, created_at timestamptz not null default now()
);
create or replace view growth_synth_summary as
select proposal_id, round(avg(score),4) avg_score, count(*) n_personas, bool_or(verdict='pass') any_pass
from growth_synth_tests group by proposal_id;
create or replace function synth_prescreen_ok(p_proposal_id uuid, p_min numeric default 0.5)
returns boolean language sql stable as $$
  select coalesce((select avg(score) from growth_synth_tests where proposal_id=p_proposal_id),0) >= p_min;
$$;

create table if not exists growth_wagers (
  id uuid primary key default gen_random_uuid(), tournament_id uuid references growth_tournaments(id) on delete cascade,
  proposal_id uuid references growth_proposals(id) on delete cascade,
  strategist_id uuid references growth_strategists(id) on delete set null,
  stake numeric(12,2) not null default 0, created_at timestamptz not null default now()
);
create or replace function market_price(p_tournament_id uuid)
returns table(proposal_id uuid, implied_prob numeric) language sql stable as $$
  with w as (select proposal_id, sum(stake) s from growth_wagers where tournament_id=p_tournament_id group by proposal_id),
       tot as (select sum(s) ts from w)
  select w.proposal_id, round(w.s/nullif((select ts from tot),0),4) from w;
$$;

create table if not exists growth_voc (
  id uuid primary key default gen_random_uuid(), app text not null, source text, phrase text not null,
  sentiment text, segment text, freq int default 1, created_at timestamptz not null default now()
);
create index if not exists voc_app_seg_idx on growth_voc (app, segment);
create or replace view growth_voc_top as
select app, segment, phrase, sum(freq) freq from growth_voc group by app, segment, phrase order by sum(freq) desc;

create or replace view growth_retention_metrics as
select app,
  count(*) filter (where event_type='activate'  and ts>=now()-interval '30 days') as activations_30d,
  count(*) filter (where event_type='churn'     and ts>=now()-interval '30 days') as churn_30d,
  count(*) filter (where event_type='signup'    and ts>=now()-interval '30 days') as signups_30d,
  coalesce(sum(value) filter (where event_type='expansion' and ts>=now()-interval '30 days'),0) as expansion_rev_30d
from growth_events group by app;

create table if not exists growth_assets (
  id uuid primary key default gen_random_uuid(), arm_id uuid references growth_arms(id) on delete cascade,
  kind text not null, content jsonb not null default '{}', url text, quality_score numeric(6,3),
  status text not null default 'draft', created_at timestamptz not null default now()
);
create index if not exists growth_assets_arm_idx on growth_assets (arm_id);

create or replace view growth_pricing_results as
select s.app, s.path, a.arm, (a.variant->>'price')::numeric as price, a.impressions, a.conversions,
       a.reward_sum, round(a.reward_sum/nullif(a.impressions,0),2) as rev_per_visitor, a.status
from growth_arms a join growth_segments s on s.id=a.segment_id
where a.variant ? 'price';

create or replace view growth_channel_attribution as
with conv as (
  select actor_hash, sum(value) val from growth_events
   where event_type='revenue' and actor_hash is not null group by actor_hash
),
touches as (
  select actor_hash, channel, count(*) c from growth_events
   where actor_hash is not null and channel is not null
     and event_type in ('visit','signup','qualified_lead','activate','content_published','referral')
   group by actor_hash, channel
),
tot as (select actor_hash, sum(c) tc from touches group by actor_hash)
select t.channel,
       round(sum((t.c::numeric/nullif(tot.tc,0)) * conv.val),2) as attributed_revenue,
       count(distinct conv.actor_hash) as converters
from conv join touches t on t.actor_hash=conv.actor_hash join tot on tot.actor_hash=conv.actor_hash
group by t.channel order by attributed_revenue desc;

create or replace function discover_segments(p_app text, p_min_conversions int default 5)
returns int language plpgsql as $$
declare rec record; n int := 0; p text;
begin
  for rec in
    select e.channel, e.source,
           count(*) filter (where e.event_type in ('signup','revenue')) as conv, count(*) as total
    from growth_events e where e.app = p_app and e.channel is not null
    group by e.channel, e.source
    having count(*) filter (where e.event_type in ('signup','revenue')) >= p_min_conversions
  loop
    p := p_app||'/discovered/'||coalesce(rec.channel,'na')||'/'||coalesce(rec.source,'na');
    if not exists (select 1 from growth_segments where path = p) then
      insert into growth_segments(app, path, positioning, status, curated_by, meta)
      values (p_app, p, 'auto-discovered high-converting cohort', 'proposed', 'icp-discovery',
        jsonb_build_object('channel',rec.channel,'source',rec.source,'conversions',rec.conv,'total',rec.total));
      n := n + 1;
    end if;
  end loop;
  return n;
end $$;

create table if not exists growth_governance (
  key text primary key, value jsonb not null default '{}', updated_at timestamptz not null default now()
);
insert into growth_governance(key,value) values
  ('autonomy_threshold','{"min_autonomy":0.6,"max_auto_spend":500}') on conflict (key) do nothing;
create or replace function required_approval(p_strategist_id uuid, p_spend numeric)
returns boolean language plpgsql stable as $$
declare au numeric; cfg jsonb;
begin
  select value into cfg from growth_governance where key='autonomy_threshold';
  select autonomy into au from growth_strategists where id = p_strategist_id;
  if au >= coalesce((cfg->>'min_autonomy')::numeric,0.6) and p_spend <= coalesce((cfg->>'max_auto_spend')::numeric,500) then
    return false;
  end if;
  return true;
end $$;

do $$
declare tbl text;
begin
  foreach tbl in array array['growth_competitor_intel','growth_synth_tests','growth_wagers','growth_voc','growth_assets','growth_governance'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;
grant execute on function synth_prescreen_ok(uuid,numeric) to authenticated, service_role;
grant execute on function market_price(uuid) to authenticated, service_role;
grant execute on function discover_segments(text,int) to authenticated, service_role;
grant execute on function required_approval(uuid,numeric) to authenticated, service_role;;
