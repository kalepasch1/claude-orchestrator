-- 0021_growth_creative_advanced.sql
-- Style-consistent generation, brand genome for visuals, multi-modal Colosseum, creative fatigue,
-- closed brand-safety gate, unified role inbox, creative ROI, campaign kits, cross-app transfer,
-- motion/audio. Idempotent.

-- Style reference for consistent generation (LoRA/IP-adapter seed, ref images) on the brand kit.
alter table growth_brand_kit add column if not exists style_ref jsonb not null default '{}';
-- Medium for the format matrix (image|video|audio) + seed a few motion/audio forms.
alter table growth_format_matrix add column if not exists medium text not null default 'image';
insert into growth_format_matrix (channel, width, height, locale, kind, medium)
select * from (values
  ('reel_video',1080,1920,'en','video','video'),
  ('youtube_pre_roll',1920,1080,'en','video','video'),
  ('podcast_audio',0,0,'en','audio','audio')
) v(channel,width,height,locale,kind,medium)
where not exists (select 1 from growth_format_matrix where medium in ('video','audio'));

-- A) BRAND GENOME FOR VISUALS: fold brand kit + approved masters into the exportable genome.
create or replace function export_growth_genome(p_app text)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'app', p_app, 'exported_at', now(),
    'brand_kit', (select spec from growth_brand_kit where app=p_app),
    'brand_style_ref', (select style_ref from growth_brand_kit where app=p_app),
    'brand_masters', (select coalesce(jsonb_agg(jsonb_build_object('title',title,'gen_prompt',gen_prompt,
                        'asset_url',asset_url,'kind',kind)),'[]')
                      from growth_creative where app=p_app and role='master' and status in ('approved','published')),
    'segments', (select coalesce(jsonb_agg(jsonb_build_object('path',path,'positioning',positioning,
                    'message',message,'channel',channel,'offer',offer)),'[]') from growth_segments where app=p_app),
    'plays', (select coalesce(jsonb_agg(jsonb_build_object('name',name,'kind',kind,'spec',spec)),'[]')
              from growth_plays where status='proven'),
    'playbooks', (select coalesce(jsonb_agg(jsonb_build_object('segment',segment,'channel',channel,
                    'sequence',sequence,'score',score)),'[]') from growth_bd_playbook where status='active'),
    'policy', (select compiled from growth_autonomy_policy where active order by created_at desc limit 1)
  );
$$;

-- B) CLOSED BRAND-SAFETY GATE: automated checks must pass before a creative can go live.
create table if not exists growth_safety_check (
  id bigint generated always as identity primary key, creative_id uuid references growth_creative(id) on delete cascade,
  check_type text not null,          -- contrast|alt_text|claims|trademark|nsfw
  result text not null,              -- pass|fail|warn
  detail text, created_at timestamptz not null default now()
);
create or replace function safety_ok(p_creative_id uuid)
returns boolean language sql stable as $$
  select not exists (select 1 from growth_safety_check where creative_id=p_creative_id and result='fail');
$$;
-- gate now also requires safety: a visual arm serves only if its creative is approved AND safety-clean
create or replace function creative_gate(p_arm_id uuid)
returns boolean language sql stable as $$
  select not exists (
    select 1 from growth_creative c
    where c.arm_id = p_arm_id
      and (c.status not in ('approved','published') or not safety_ok(c.id))
  );
$$;

-- C) MULTI-MODAL COLOSSEUM: enter an approved creative as a bandit arm in a segment.
create or replace function enter_creative_arm(p_creative_id uuid)
returns uuid language plpgsql as $$
declare cr growth_creative; seg uuid; aid uuid;
begin
  select * into cr from growth_creative where id=p_creative_id and status in ('approved','published');
  if not found then raise exception 'creative % not approved', p_creative_id; end if;
  select id into seg from growth_segments where path = cr.segment;
  if seg is null then raise exception 'segment % not found for creative', cr.segment; end if;
  insert into growth_arms(segment_id, arm, variant)
  values (seg, 'creative-'||left(p_creative_id::text,8),
          jsonb_build_object('creative_id',p_creative_id,'asset_url',cr.asset_url,'kind',cr.kind))
  on conflict (segment_id, arm) do update set variant=excluded.variant
  returning id into aid;
  update growth_creative set arm_id = aid where id = p_creative_id;
  return aid;
end $$;

-- D) CREATIVE FATIGUE: approved visuals whose backing arm underperforms the segment average.
create or replace view growth_creative_fatigue as
with seg as (
  select s.id as seg_id, avg(case when a.impressions>0 then a.conversions::numeric/a.impressions end) as seg_rate
  from growth_arms a join growth_segments s on s.id=a.segment_id group by s.id
)
select c.id, c.app, c.segment, c.title, a.impressions, a.conversions,
  round(case when a.impressions>0 then a.conversions::numeric/a.impressions else 0 end,4) as conv_rate,
  round(seg.seg_rate,4) as seg_avg
from growth_creative c join growth_arms a on a.id=c.arm_id
join growth_segments s on s.path=c.segment join seg on seg.seg_id=s.id
where c.status in ('approved','published') and a.impressions > 500
  and (a.conversions::numeric/nullif(a.impressions,0)) < 0.6*seg.seg_rate;

-- E) CREATIVE ROI dashboard (per app).
create or replace view growth_creative_roi as
select app,
  count(*) filter (where role='master') as masters,
  count(*) filter (where status in ('approved','published')) as live_assets,
  round(sum(cost_usd),2) as total_cost,
  round(avg(brand_score) filter (where status in ('approved','published')),3) as avg_brand_score
from growth_creative group by app;

-- F) UNIFIED ROLE INBOX: one queue routed by role (designer/operator/copywriter/compliance).
create or replace view growth_unified_inbox as
select 'creative'::text as item_kind, coalesce(rr.role,'designer') as role, dq.id::text as item_id,
       dq.app, dq.title, 'awaiting design review' as detail, dq.created_at
from growth_design_queue dq left join growth_role_route rr on rr.kind = dq.kind
union all
select 'human:'||h.kind,
       case h.kind when 'email_material' then 'copywriter' when 'approval' then 'operator' else 'operator' end,
       h.id::text, h.app, h.title, h.why, h.created_at
from growth_human_queue h where h.status='open'
union all
select 'task', 'operator', t.id::text, p.name, t.slug, t.note, t.created_at
from tasks t join projects p on p.id=t.project_id where t.kind='gtm' and t.state in ('QUEUED','WAITING')
order by created_at desc;

-- G) CAMPAIGN KITS: assemble all derivatives of a master into a versioned, exportable kit.
create table if not exists growth_campaign_kit (
  id uuid primary key default gen_random_uuid(), app text, master_id uuid, version int not null default 1,
  assets jsonb not null default '[]', export_url text, created_at timestamptz not null default now()
);
create or replace function assemble_kit(p_master_id uuid)
returns uuid language plpgsql as $$
declare kid uuid; app_ text; assets jsonb;
begin
  select app into app_ from growth_creative where id=p_master_id;
  select coalesce(jsonb_agg(jsonb_build_object('id',id,'kind',kind,'derivative_kind',derivative_kind,
           'asset_url',asset_url,'status',status)),'[]')
    into assets from growth_creative
   where (master_id = p_master_id or id = p_master_id) and status in ('approved','published');
  insert into growth_campaign_kit(app, master_id, assets) values (app_, p_master_id, assets) returning id into kid;
  return kid;
end $$;

-- H) CROSS-APP CREATIVE TRANSFER: adapt a proven creative play into a master for another app.
create or replace function adapt_creative_play(p_play_id uuid, p_target_app text, p_segment text default null)
returns uuid language plpgsql as $$
declare pl growth_plays; mid uuid;
begin
  select * into pl from growth_plays where id=p_play_id and kind='creative';
  if not found then raise exception 'creative play % not found', p_play_id; end if;
  mid := register_master(p_target_app, p_segment,
    'Adapted: '||pl.name,
    coalesce(pl.spec->>'gen_prompt','')||' | adapt this proven creative to '||p_target_app||' brand kit', null, 'genome');
  return mid;
end $$;

-- ---- RLS + grants ----
do $$
declare tbl text;
begin
  foreach tbl in array array['growth_safety_check','growth_campaign_kit'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;
grant execute on function safety_ok(uuid) to authenticated, service_role;
grant execute on function enter_creative_arm(uuid) to authenticated, service_role;
grant execute on function assemble_kit(uuid) to authenticated, service_role;
grant execute on function adapt_creative_play(uuid,text,text) to authenticated, service_role;
