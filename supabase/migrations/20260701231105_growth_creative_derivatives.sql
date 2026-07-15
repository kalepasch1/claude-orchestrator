-- 0020_growth_creative_derivatives.sql
alter table growth_creative add column if not exists master_id uuid references growth_creative(id) on delete set null;
alter table growth_creative add column if not exists role text not null default 'standalone';
alter table growth_creative add column if not exists derivative_kind text;
alter table growth_creative add column if not exists cost_usd numeric(10,4) default 0;
create index if not exists growth_creative_master_idx on growth_creative (master_id);

create table if not exists growth_format_matrix (
  id uuid primary key default gen_random_uuid(),
  channel text not null, width int, height int, locale text default 'en', kind text, active boolean not null default true
);
insert into growth_format_matrix (channel, width, height, locale, kind)
select * from (values
  ('instagram_post',1080,1080,'en','social'),
  ('instagram_story',1080,1920,'en','social'),
  ('x_post',1600,900,'en','social'),
  ('linkedin',1200,627,'en','social'),
  ('email_hero',1200,600,'en','banner'),
  ('landing_hero',2400,1200,'en','banner'),
  ('display_ad',728,90,'en','ad'),
  ('og_card',1200,630,'en','social')
) v(channel,width,height,locale,kind)
where not exists (select 1 from growth_format_matrix);

create or replace function register_master(p_app text, p_segment text, p_title text, p_gen_prompt text,
  p_asset_url text default null, p_by text default 'designer')
returns uuid language sql as $$
  insert into growth_creative(app, segment, role, kind, title, gen_prompt, asset_url, source, status, created_by)
  values (p_app, p_segment, 'master', 'brand_asset', p_title, p_gen_prompt, p_asset_url,
          case when p_asset_url is null then 'ai' else 'human' end, 'approved', p_by)
  returning id;
$$;

create or replace function request_derivatives(p_master_id uuid, p_novel int default 3, p_by text default 'designer')
returns int language plpgsql as $$
declare m growth_creative; f record; n int := 0; pid uuid; i int;
begin
  select * into m from growth_creative where id = p_master_id;
  if not found then raise exception 'master % not found', p_master_id; end if;
  select id into pid from projects where name = m.app;
  for f in select * from growth_format_matrix where active loop
    insert into growth_creative(app, segment, master_id, role, kind, derivative_kind, title, gen_prompt, source, status, created_by)
    values (m.app, m.segment, p_master_id, 'derivative', coalesce(f.kind,m.kind), f.channel,
            m.title||' — '||f.channel,
            coalesce(m.gen_prompt,'')||format(' | derivative for %s at %sx%s, locale %s, strictly on-brand per the active brand kit', f.channel, f.width, f.height, f.locale),
            'ai','draft',p_by);
    n := n + 1;
  end loop;
  for i in 1..greatest(p_novel,0) loop
    insert into growth_creative(app, segment, master_id, role, kind, derivative_kind, title, gen_prompt, source, status, created_by)
    values (m.app, m.segment, p_master_id, 'derivative', 'image', 'novel_extension',
            m.title||' — novel extension #'||i,
            coalesce(m.gen_prompt,'')||' | invent a NOVEL on-brand extension/derivative of this master (unexpected format, motif remix, or campaign spin-off) that stays true to the brand kit',
            'ai','draft',p_by);
    n := n + 1;
  end loop;
  if pid is not null then
    insert into tasks(project_id, slug, prompt, kind, state, note)
    values (pid, 'creative-derivatives-'||left(p_master_id::text,8),
      format('Generate %s on-brand derivatives + novel extensions from master creative %s (app %s). Use the active brand kit; set each derivative status=in_review for the designer.', n, p_master_id, m.app),
      'gtm','QUEUED','auto-filed by request_derivatives') on conflict do nothing;
  end if;
  return n;
end $$;

create table if not exists growth_brand_feedback (
  id bigint generated always as identity primary key, creative_id uuid, app text,
  signal text, features jsonb not null default '{}', reviewer text, created_at timestamptz not null default now()
);

create or replace view growth_brand_health as
select app,
  round(avg(brand_score) filter (where status in ('approved','published')),3) as avg_brand_score,
  count(*) filter (where status in ('approved','published') and brand_score < 0.6) as off_brand_live,
  count(*) filter (where role='master') as masters,
  count(*) filter (where role='derivative') as derivatives
from growth_creative group by app;

create or replace view growth_creative_perf as
select c.id, c.app, c.segment, c.kind, c.role, c.status, c.brand_score, c.cost_usd,
       a.impressions, a.conversions,
       case when a.impressions>0 then round(a.conversions::numeric/a.impressions,4) else null end as conv_rate
from growth_creative c left join growth_arms a on a.id = c.arm_id;

create table if not exists growth_role_route (kind text primary key, role text not null);
insert into growth_role_route (kind, role) values
 ('image','designer'),('logo','designer'),('banner','designer'),('ad','designer'),
 ('social','designer'),('deck','designer'),('brand_asset','designer')
on conflict (kind) do nothing;

do $$
declare tbl text;
begin
  foreach tbl in array array['growth_format_matrix','growth_brand_feedback','growth_role_route'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;
grant execute on function register_master(text,text,text,text,text,text) to authenticated, service_role;
grant execute on function request_derivatives(uuid,int,text) to authenticated, service_role;;
