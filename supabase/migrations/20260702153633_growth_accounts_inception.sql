-- 0026_growth_accounts_inception.sql
alter table growth_mailbox add column if not exists label text;
alter table growth_mailbox add column if not exists purpose text not null default 'outreach';
alter table growth_mailbox add column if not exists owner text not null default 'user';
alter table growth_mailbox add column if not exists enabled boolean not null default true;

create table if not exists growth_mailbox_provision (
  id uuid primary key default gen_random_uuid(),
  provider text not null default 'gmail', method text not null default 'workspace_user',
  domain text, desired_local text, display_name text, purpose text default 'outreach', owner text default 'bots',
  status text not null default 'requested', created_address text, detail text, created_at timestamptz not null default now()
);
create table if not exists growth_offering (
  id uuid primary key default gen_random_uuid(), app text not null, name text not null,
  kind text not null default 'service', description text, status text not null default 'active',
  created_at timestamptz not null default now(), unique (app, name)
);
create or replace function incept_campaign(p_spec jsonb)
returns jsonb language plpgsql as $$
declare app_ text; seg text; mid uuid; cid uuid; brand text; title text;
begin
  app_ := coalesce(p_spec->>'app','apparently');
  seg  := coalesce(p_spec->>'segment', app_||'/incepted/'||left(regexp_replace(lower(coalesce(p_spec->>'name','campaign')),'[^a-z0-9]+','-','g'),40));
  brand := coalesce(p_spec->>'brand_mode','none');
  title := coalesce(p_spec->>'name','New campaign');
  if p_spec ? 'offering_name' then
    insert into growth_offering(app, name, kind, description)
    values (app_, p_spec->>'offering_name', coalesce(p_spec->>'offering_kind','service'), p_spec->>'positioning')
    on conflict (app, name) do nothing;
  end if;
  insert into growth_segments(app, path, positioning, message, status, curated_by, meta)
  values (app_, seg, p_spec->>'positioning', p_spec->>'message', 'proposed', 'nl-inception',
          jsonb_build_object('icp', p_spec->>'icp', 'brand_mode', brand))
  on conflict (path) do update set positioning=excluded.positioning, updated_at=now();
  mid := register_master(app_, seg, title||' — key visual',
    coalesce(p_spec->>'master_prompt', p_spec->>'positioning','')||' | brand mode: '||brand, null, 'nl-inception');
  perform request_derivatives(mid, 3, 'nl-inception');
  insert into growth_campaign(app, segment, name, objective, master_id, status)
  values (app_, seg, title, coalesce(p_spec->>'objective','acquisition'), mid, 'draft') returning id into cid;
  return jsonb_build_object('campaign_id', cid, 'segment', seg, 'master_id', mid, 'brand_mode', brand,
    'note', 'Staged as DRAFT. Review the creative, then launch in Approval mode. Global switch still governs.');
end $$;
do $$
declare tbl text;
begin
  foreach tbl in array array['growth_mailbox_provision','growth_offering'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;
grant execute on function incept_campaign(jsonb) to authenticated, service_role;;
