-- 0018_growth_creative_suite.sql
create table if not exists growth_brand_kit (
  app text primary key, spec jsonb not null default '{}', version int not null default 1,
  active boolean not null default true, updated_by text, updated_at timestamptz not null default now()
);
create table if not exists growth_creative (
  id uuid primary key default gen_random_uuid(), app text not null, segment text,
  arm_id uuid references growth_arms(id) on delete set null, kind text not null default 'image',
  title text, gen_prompt text, asset_url text, thumb_url text, source text not null default 'ai',
  brand_score numeric(5,3), status text not null default 'draft', meta jsonb not null default '{}',
  created_by text, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index if not exists growth_creative_status_idx on growth_creative (status, app);
create index if not exists growth_creative_arm_idx on growth_creative (arm_id);
create table if not exists growth_creative_review (
  id bigint generated always as identity primary key, creative_id uuid references growth_creative(id) on delete cascade,
  reviewer text, decision text not null, comments text, annotations jsonb not null default '[]',
  created_at timestamptz not null default now()
);
create or replace function review_creative(p_creative_id uuid, p_reviewer text, p_decision text,
  p_comments text default null, p_annotations jsonb default '[]')
returns void language plpgsql as $$
begin
  insert into growth_creative_review(creative_id, reviewer, decision, comments, annotations)
  values (p_creative_id, p_reviewer, p_decision, p_comments, coalesce(p_annotations,'[]'));
  update growth_creative set
    status = case p_decision when 'approve' then 'approved' when 'reject' then 'rejected' else 'changes_requested' end,
    updated_at = now() where id = p_creative_id;
end $$;
create or replace function auto_triage_creative(p_creative_id uuid, p_hi numeric default 0.85, p_lo numeric default 0.4)
returns text language plpgsql as $$
declare sc numeric; st text;
begin
  select brand_score into sc from growth_creative where id = p_creative_id;
  if sc is null then st := 'in_review';
  elsif sc >= p_hi then st := 'approved';
  elsif sc <= p_lo then st := 'rejected';
  else st := 'in_review'; end if;
  update growth_creative set status = st, updated_at = now() where id = p_creative_id;
  return st;
end $$;
create or replace function creative_gate(p_arm_id uuid)
returns boolean language sql stable as $$
  select not exists (select 1 from growth_creative where arm_id = p_arm_id and status not in ('approved','published'));
$$;
create or replace function bump_brand_kit(p_app text, p_spec jsonb, p_by text default 'designer')
returns int language plpgsql as $$
declare v int;
begin
  insert into growth_brand_kit(app, spec, version, updated_by, updated_at) values (p_app, p_spec, 1, p_by, now())
  on conflict (app) do update set spec=excluded.spec, version=growth_brand_kit.version+1, updated_by=excluded.updated_by, updated_at=now()
  returning version into v;
  return v;
end $$;
create or replace view growth_design_queue as
select c.id, c.app, c.segment, c.kind, c.title, c.asset_url, c.thumb_url, c.brand_score, c.status, c.gen_prompt, c.created_at,
  (select decision from growth_creative_review r where r.creative_id=c.id order by created_at desc limit 1) as last_decision
from growth_creative c where c.status in ('in_review','changes_requested')
order by c.brand_score asc nulls first, c.created_at desc;
do $$
declare tbl text;
begin
  foreach tbl in array array['growth_brand_kit','growth_creative','growth_creative_review'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;
grant execute on function review_creative(uuid,text,text,text,jsonb) to authenticated, service_role;
grant execute on function auto_triage_creative(uuid,numeric,numeric) to authenticated, service_role;
grant execute on function creative_gate(uuid) to authenticated, service_role;
grant execute on function bump_brand_kit(text,jsonb,text) to authenticated, service_role;
insert into growth_brand_kit(app, spec) values
 ('apparently','{"palette":["#0B0E14","#5B8CFF"],"tone":"authoritative, precise","distinctive_assets":["state-grid motif"],"donts":["no $0 admin-fee claims"]}'),
 ('tomorrow','{"palette":["#0B0E14","#39D98A"],"tone":"institutional, credible","distinctive_assets":["settlement-graph motif"]}')
on conflict (app) do nothing;;
