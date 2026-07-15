-- 0023_growth_capstones.sql
create table if not exists growth_campaign (
  id uuid primary key default gen_random_uuid(), app text not null, segment text, name text not null,
  objective text default 'acquisition', master_id uuid, status text not null default 'draft', created_at timestamptz not null default now()
);
create or replace function launch_campaign(p_campaign_id uuid, p_mode text default 'approval', p_first_n int default 25)
returns text language plpgsql as $$
declare cmp growth_campaign;
begin
  select * into cmp from growth_campaign where id = p_campaign_id;
  if not found then raise exception 'campaign % not found', p_campaign_id; end if;
  if cmp.segment is not null then perform set_autonomy('campaign', cmp.segment, p_mode, p_first_n, 'launch_campaign'); end if;
  update growth_campaign set status = case when p_mode='off' then 'paused' else 'active' end where id = p_campaign_id;
  return format('campaign %s -> %s (segment switch=%s, ramp=%s). Global switch still governs.', cmp.name, cmp.status, p_mode, p_first_n);
end $$;
create table if not exists growth_eval_case (
  id uuid primary key default gen_random_uuid(), suite text not null, input jsonb not null, expected jsonb not null, created_at timestamptz not null default now()
);
create table if not exists growth_eval_run (
  id bigint generated always as identity primary key, suite text, score numeric(5,3), passed int, total int, detail jsonb not null default '{}', created_at timestamptz not null default now()
);
create or replace function counterfactual_value()
returns numeric language sql stable as $$
  with seg as (
    select s.id, s.path,
      max(case when a.arm='control' and a.impressions>0 then a.conversions::numeric/a.impressions end) as base_rate,
      avg(case when a.impressions>0 then a.conversions::numeric/a.impressions end) as pooled_rate
    from growth_arms a join growth_segments s on s.id=a.segment_id group by s.id, s.path
  )
  select round(coalesce(sum(
     greatest((case when a.impressions>0 then a.conversions::numeric/a.impressions else 0 end)
              - coalesce(seg.base_rate, seg.pooled_rate), 0) * a.impressions), 0), 1)
  from growth_arms a join growth_segments s on s.id=a.segment_id join seg on seg.id=s.id
  where a.status in ('winner','active');
$$;
create or replace function compounding_dividend()
returns int language plpgsql as $$
declare pl record; ap record; n int := 0; wk text := to_char(now(),'IYYY-"W"IW');
begin
  for pl in select id, name, origin_app from growth_plays where status='proven' order by created_at desc limit 5 loop
    for ap in select app from growth_apps where enabled and tier<>'infra' and app <> pl.origin_app loop
      if not exists (select 1 from growth_operator_agenda where for_week=wk and ref=pl.id::text||':'||ap.app) then
        insert into growth_operator_agenda(for_week, priority, kind, title, why, ref)
        values (wk, 2, 'dividend', 'Apply proven play "'||pl.name||'" to '||ap.app,
                'Won in '||pl.origin_app||'; propose adapting it here.', pl.id::text||':'||ap.app);
        n := n + 1;
      end if;
    end loop;
  end loop;
  return n;
end $$;
create or replace function propose_budget(p_factor numeric default 0.3)
returns jsonb language plpgsql stable as $$
declare rev numeric; mom numeric; proposed numeric;
begin
  select coalesce(sum(value),0) into rev from growth_events where event_type in ('revenue','expansion') and ts >= now()-interval '30 days';
  select coalesce(avg(score),0) into mom from growth_momentum_latest where tier<>'infra';
  proposed := round(rev * p_factor, 2);
  return jsonb_build_object('proposed_total', proposed, 'basis_revenue_30d', rev, 'avg_momentum', round(mom,1),
    'note', 'human approves before spend; circuit breaker + switches still apply');
end $$;
do $$
declare tbl text;
begin
  foreach tbl in array array['growth_campaign','growth_eval_case','growth_eval_run'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;
grant execute on function launch_campaign(uuid,text,int) to authenticated, service_role;
grant execute on function counterfactual_value() to authenticated, service_role;
grant execute on function compounding_dividend() to authenticated, service_role;
grant execute on function propose_budget(numeric) to authenticated, service_role;;
