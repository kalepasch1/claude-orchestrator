-- 0017_growth_advanced_autonomy.sql
create table if not exists growth_autonomy_policy (
  id uuid primary key default gen_random_uuid(), policy_text text not null, compiled jsonb not null default '[]',
  active boolean not null default true, created_by text, created_at timestamptz not null default now()
);
create or replace function policy_effect(p_app text, p_segment text, p_value numeric default 0, p_text text default '')
returns text language plpgsql stable as $$
declare rules jsonb; r jsonb; kw text;
begin
  select compiled into rules from growth_autonomy_policy where active order by created_at desc limit 1;
  if rules is null then return 'allow'; end if;
  for r in select * from jsonb_array_elements(rules) loop
    if (r->>'segment_like') is not null and p_segment not ilike (r->>'segment_like') then continue; end if;
    if (r->>'max_value') is not null and p_value > (r->>'max_value')::numeric then
      if (r->>'effect')='allow' then continue; end if; end if;
    for kw in select jsonb_array_elements_text(coalesce(r->'block_keywords','[]')) loop
      if p_text ilike '%'||kw||'%' then return 'deny'; end if;
    end loop;
    return coalesce(r->>'effect','allow');
  end loop;
  return 'allow';
end $$;

create table if not exists growth_action_log (
  id uuid primary key default gen_random_uuid(), app text, kind text, ref text, undo_until timestamptz,
  undone boolean not null default false, meta jsonb not null default '{}', created_at timestamptz not null default now()
);
create or replace function campaign_health(p_segment text, p_window interval default interval '3 days')
returns numeric language sql stable as $$
  with e as (select event_type from growth_events where segment=p_segment and ts >= now()-p_window)
  select round(1.0 - (
     (select count(*) from e where event_type in ('churn','negative_reply','unsubscribe'))::numeric
     / greatest((select count(*) from e where event_type in ('outreach_sent','visit')),1)), 3);
$$;
create or replace function auto_rollback_check(p_min_sent int default 20, p_health_floor numeric default 0.7)
returns int language plpgsql as $$
declare rec record; n int := 0; sent int;
begin
  for rec in select key from growth_autonomy_switch where scope='campaign' and mode <> 'off' loop
    select count(*) into sent from growth_events where segment=rec.key and event_type='outreach_sent';
    if sent >= p_min_sent and campaign_health(rec.key) < p_health_floor then
      perform set_autonomy('campaign', rec.key, 'off', 0, 'auto-rollback');
      insert into growth_action_log(app, kind, ref, meta) values (null,'auto_rollback', rec.key, jsonb_build_object('health', campaign_health(rec.key)));
      insert into growth_human_queue(app, kind, title, why, segment, prepared)
        values ('portfolio','approval','Auto-paused campaign: '||rec.key,'Health fell below floor; review before resuming.', rec.key, jsonb_build_object('health', campaign_health(rec.key)));
      n := n + 1;
    end if;
  end loop; return n;
end $$;

create or replace function strategist_can_send(p_strategist_id uuid, p_min_autonomy numeric default 0.6, p_min_calibration numeric default 0.55)
returns boolean language sql stable as $$
  select coalesce((select autonomy >= p_min_autonomy and calibration >= p_min_calibration from growth_strategists where id = p_strategist_id), false);
$$;

create table if not exists growth_meetings (
  id uuid primary key default gen_random_uuid(), app text, segment text, actor_hash text, scheduled_at timestamptz,
  status text not null default 'proposed', brief jsonb not null default '{}', transcript text, followup_draft text,
  created_at timestamptz not null default now()
);
create or replace function meeting_followup(p_meeting_id uuid)
returns uuid language plpgsql as $$
declare m growth_meetings; oid uuid;
begin
  select * into m from growth_meetings where id = p_meeting_id;
  if not found then return null; end if;
  update growth_meetings set status='held' where id=p_meeting_id;
  insert into growth_outreach(app, actor_hash, segment, state, next_action_at, last_channel, meta)
  values (m.app, m.actor_hash, m.segment, 'queued', now(), 'email', jsonb_build_object('reason','post_meeting_followup','meeting', p_meeting_id))
  returning id into oid;
  return oid;
end $$;

create table if not exists growth_reply_triage (
  id bigint generated always as identity primary key, outreach_id uuid, app text, segment text,
  intent text, confidence numeric(4,3), auto_handled boolean, human_edited boolean default false,
  edit_distance numeric, created_at timestamptz not null default now()
);
create or replace view growth_triage_calibration as
select app, count(*) filter (where auto_handled) as auto_handled,
  count(*) filter (where auto_handled and human_edited) as auto_overridden,
  round(1.0 - count(*) filter (where auto_handled and human_edited)::numeric / greatest(count(*) filter (where auto_handled),1), 3) as auto_precision,
  round(greatest(0.6, 1.0 - (count(*) filter (where auto_handled and human_edited)::numeric / greatest(count(*) filter (where auto_handled),1))), 3) as recommended_min_confidence
from growth_reply_triage group by app;

create table if not exists growth_autopsy (
  id uuid primary key default gen_random_uuid(), app text, segment text, outcome text,
  reasons jsonb not null default '[]', value numeric default 0, created_at timestamptz not null default now()
);
create or replace view growth_loss_reasons as
select app, segment, jsonb_array_elements_text(reasons) as reason, count(*) as freq
from growth_autopsy where outcome='loss' group by app, segment, jsonb_array_elements_text(reasons) order by count(*) desc;

create or replace function rebalance_by_profit(p_total numeric, p_window interval default interval '30 days')
returns int language plpgsql as $$
declare tot numeric; n int := 0; rec record;
begin
  create temp table _p on commit drop as
    select app, coalesce(sum(value),0) as rev from growth_events where event_type in ('revenue','expansion') and ts >= now()-p_window group by app;
  select sum(rev) into tot from _p;
  if coalesce(tot,0) = 0 then return rebalance_budget(p_total); end if;
  for rec in select app, rev from _p where rev > 0 loop
    insert into growth_budget(scope,key,allocation,updated_at) values ('app', rec.app, round(p_total*rec.rev/tot,2), now())
    on conflict (scope,key) do update set allocation=excluded.allocation, updated_at=now() where growth_budget.status='active';
    n := n + 1;
  end loop; return n;
end $$;

create table if not exists growth_operator_agenda (
  id uuid primary key default gen_random_uuid(), for_week text, priority int, kind text, title text, why text,
  ref text, est_value numeric default 0, created_at timestamptz not null default now()
);
create or replace function plan_operator_week()
returns int language plpgsql as $$
declare wk text := to_char(now(),'IYYY-"W"IW'); n int := 0; top text;
begin
  delete from growth_operator_agenda where for_week = wk;
  insert into growth_operator_agenda(for_week, priority, kind, title, why, ref)
  select wk, case h.kind when 'meeting' then 1 when 'presentation' then 2 else 3 end, h.kind, h.title, h.why, h.id::text
  from growth_human_queue h where h.status='open';
  get diagnostics n = row_count;
  select display_name into top from growth_momentum_latest where tier<>'infra' order by rank limit 1;
  if top is not null then
    insert into growth_operator_agenda(for_week, priority, kind, title, why) values (wk, 0, 'focus', 'Deep-work: '||top, 'Highest portfolio momentum this week');
    n := n + 1;
  end if;
  return n;
end $$;

do $$
declare tbl text;
begin
  foreach tbl in array array['growth_autonomy_policy','growth_action_log','growth_meetings','growth_reply_triage','growth_autopsy','growth_operator_agenda'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;
grant execute on function policy_effect(text,text,numeric,text) to authenticated, service_role;
grant execute on function campaign_health(text,interval) to authenticated, service_role;
grant execute on function auto_rollback_check(int,numeric) to authenticated, service_role;
grant execute on function strategist_can_send(uuid,numeric,numeric) to authenticated, service_role;
grant execute on function meeting_followup(uuid) to authenticated, service_role;
grant execute on function rebalance_by_profit(numeric,interval) to authenticated, service_role;
grant execute on function plan_operator_week() to authenticated, service_role;;
