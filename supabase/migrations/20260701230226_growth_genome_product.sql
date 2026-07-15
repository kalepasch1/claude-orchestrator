-- 0019_growth_genome_product.sql
create or replace function export_growth_genome(p_app text)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'app', p_app, 'exported_at', now(),
    'brand_kit', (select spec from growth_brand_kit where app=p_app),
    'segments', (select coalesce(jsonb_agg(jsonb_build_object('path',path,'positioning',positioning,'message',message,'channel',channel,'offer',offer)),'[]') from growth_segments where app=p_app),
    'plays', (select coalesce(jsonb_agg(jsonb_build_object('name',name,'kind',kind,'spec',spec)),'[]') from growth_plays where status='proven'),
    'playbooks', (select coalesce(jsonb_agg(jsonb_build_object('segment',segment,'channel',channel,'sequence',sequence,'score',score)),'[]') from growth_bd_playbook where status='active'),
    'policy', (select compiled from growth_autonomy_policy where active order by created_at desc limit 1)
  );
$$;
create or replace function import_growth_genome(p_target_app text, p_genome jsonb)
returns int language plpgsql as $$
declare s jsonb; pb jsonb; n int := 0; newpath text;
begin
  if p_genome ? 'brand_kit' and p_genome->'brand_kit' is not null then
    perform bump_brand_kit(p_target_app, p_genome->'brand_kit', 'genome-import');
  end if;
  for s in select * from jsonb_array_elements(coalesce(p_genome->'segments','[]')) loop
    newpath := p_target_app || '/' || split_part(s->>'path','/',2) || '/imported';
    insert into growth_segments(app, path, positioning, message, channel, offer, status, curated_by)
    values (p_target_app, newpath, s->>'positioning', s->>'message', s->>'channel', s->>'offer', 'proposed','genome')
    on conflict (path) do nothing;
    n := n + 1;
  end loop;
  for pb in select * from jsonb_array_elements(coalesce(p_genome->'playbooks','[]')) loop
    insert into growth_bd_playbook(segment, channel, sequence, status)
    values (null, coalesce(pb->>'channel','email'), coalesce(pb->'sequence','[]'), 'active')
    on conflict (segment, channel) do nothing;
  end loop;
  return n;
end $$;
create table if not exists growth_product_backlog (
  id uuid primary key default gen_random_uuid(), app text not null, source text, item text not null,
  impact numeric(10,2) default 0, status text not null default 'proposed', created_at timestamptz not null default now()
);
create or replace function build_product_backlog(p_app text)
returns int language plpgsql as $$
declare n int := 0; rec record;
begin
  for rec in select phrase, sum(freq) f from growth_voc where app=p_app group by phrase order by sum(freq) desc limit 10 loop
    insert into growth_product_backlog(app, source, item, impact) values (p_app,'voc', rec.phrase, rec.f); n := n+1;
  end loop;
  for rec in select reason, count(*) c from growth_autopsy, jsonb_array_elements_text(reasons) reason
             where app=p_app and outcome='loss' group by reason order by count(*) desc limit 10 loop
    insert into growth_product_backlog(app, source, item, impact) values (p_app,'loss_reason', rec.reason, rec.c*3); n := n+1;
  end loop;
  for rec in select topic, gap_demand from growth_content where app=p_app and status <> 'published' order by gap_demand desc limit 10 loop
    insert into growth_product_backlog(app, source, item, impact) values (p_app,'demand_gap', rec.topic, rec.gap_demand); n := n+1;
  end loop;
  return n;
end $$;
create or replace function promote_creative_to_play(p_creative_id uuid, p_name text)
returns uuid language plpgsql as $$
declare cr growth_creative; pid uuid;
begin
  select * into cr from growth_creative where id=p_creative_id and status in ('approved','published');
  if not found then raise exception 'creative % not approved', p_creative_id; end if;
  insert into growth_plays(name, kind, origin_app, origin_segment, spec, status)
  values (p_name, 'creative', cr.app, cr.segment,
    jsonb_build_object('asset_url',cr.asset_url,'gen_prompt',cr.gen_prompt,'kind',cr.kind,'brand_score',cr.brand_score), 'proven')
  returning id into pid;
  return pid;
end $$;
create table if not exists growth_sim (
  id uuid primary key default gen_random_uuid(), app text, segment text, variant jsonb,
  predicted_conv numeric(6,4), personas jsonb not null default '[]', created_at timestamptz not null default now()
);
create table if not exists growth_board_memo (
  id uuid primary key default gen_random_uuid(), for_week text, memo jsonb not null default '{}',
  recommendations jsonb not null default '[]', created_at timestamptz not null default now()
);
do $$
declare tbl text;
begin
  foreach tbl in array array['growth_product_backlog','growth_sim','growth_board_memo'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;
grant execute on function export_growth_genome(text) to authenticated, service_role;
grant execute on function import_growth_genome(text,jsonb) to authenticated, service_role;
grant execute on function build_product_backlog(text) to authenticated, service_role;
grant execute on function promote_creative_to_play(uuid,text) to authenticated, service_role;;
