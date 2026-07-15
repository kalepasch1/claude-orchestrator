-- 0015_growth_autonomy_gating.sql
create table if not exists growth_autonomy_switch (
  scope text not null, key text not null default '', mode text not null default 'off',
  require_first_n int not null default 0, updated_by text, updated_at timestamptz not null default now(),
  primary key (scope, key)
);
create table if not exists growth_contact_approval (
  actor_hash text not null, segment text not null default '', status text not null default 'approved',
  approved_by text, created_at timestamptz not null default now(), primary key (actor_hash, segment)
);
create table if not exists growth_suppression (
  match text primary key, reason text, created_at timestamptz not null default now()
);

create or replace function outreach_allowed(p_app text, p_segment text, p_actor_hash text)
returns table(allowed boolean, reason text) language plpgsql stable as $$
declare g text; a text; c text; eff text; ramp int; sent bigint; appr text;
begin
  select mode into g from growth_autonomy_switch where scope='global' and key='';
  g := coalesce(g,'off');
  if g = 'off' then return query select false, 'global switch off'; return; end if;
  select mode into a from growth_autonomy_switch where scope='app' and key=p_app;
  if a = 'off' then return query select false, 'app switch off'; return; end if;
  select mode, require_first_n into c, ramp from growth_autonomy_switch where scope='campaign' and key=coalesce(p_segment,'');
  if c = 'off' then return query select false, 'campaign switch off'; return; end if;
  if exists (select 1 from growth_suppression where match = p_actor_hash) then
    return query select false, 'contact suppressed'; return; end if;
  if exists (select 1 from growth_contact_approval where actor_hash=p_actor_hash
             and segment in (coalesce(p_segment,''),'') and status='blocked') then
    return query select false, 'contact blocked'; return; end if;
  eff := coalesce(c, a, g);
  appr := (select status from growth_contact_approval where actor_hash=p_actor_hash
           and segment in (coalesce(p_segment,''),'') and status='approved' limit 1);
  if eff = 'approval' then
    if appr = 'approved' then return query select true, 'contact approved';
    else return query select false, 'awaiting contact approval'; end if;
    return;
  end if;
  if coalesce(ramp,0) > 0 and appr is distinct from 'approved' then
    select count(*) into sent from growth_events where app=p_app and event_type='outreach_sent' and segment=p_segment;
    if sent < ramp then return query select false, format('ramp: first %s need approval (%s sent)', ramp, sent); return; end if;
  end if;
  return query select true, 'auto';
end $$;

create or replace function set_autonomy(p_scope text, p_key text, p_mode text, p_first_n int default 0, p_by text default 'human')
returns void language sql as $$
  insert into growth_autonomy_switch(scope,key,mode,require_first_n,updated_by,updated_at)
  values (p_scope, coalesce(p_key,''), p_mode, coalesce(p_first_n,0), p_by, now())
  on conflict (scope,key) do update set mode=excluded.mode, require_first_n=excluded.require_first_n,
    updated_by=excluded.updated_by, updated_at=now();
$$;
create or replace function approve_contact(p_actor_hash text, p_segment text default '', p_by text default 'human')
returns void language sql as $$
  insert into growth_contact_approval(actor_hash,segment,status,approved_by)
  values (p_actor_hash, coalesce(p_segment,''), 'approved', p_by)
  on conflict (actor_hash,segment) do update set status='approved', approved_by=excluded.approved_by;
$$;
create or replace function suppress_contact(p_match text, p_reason text default null)
returns void language sql as $$
  insert into growth_suppression(match,reason) values (p_match,p_reason) on conflict (match) do nothing;
$$;
create or replace function pause_all_outreach(p_by text default 'human')
returns void language sql as $$ select set_autonomy('global','','off',0,p_by); $$;

do $$
declare tbl text;
begin
  foreach tbl in array array['growth_autonomy_switch','growth_contact_approval','growth_suppression'] loop
    execute format('alter table %I enable row level security', tbl);
    execute format('drop policy if exists %I_sel on %I', tbl, tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)', tbl, tbl);
    execute format('drop policy if exists %I_ins on %I', tbl, tbl);
    execute format('create policy %I_ins on %I for insert to authenticated with check (true)', tbl, tbl);
    execute format('drop policy if exists %I_upd on %I', tbl, tbl);
    execute format('create policy %I_upd on %I for update to authenticated using (true) with check (true)', tbl, tbl);
  end loop;
end $$;
grant execute on function outreach_allowed(text,text,text) to authenticated, service_role;
grant execute on function set_autonomy(text,text,text,int,text) to authenticated, service_role;
grant execute on function approve_contact(text,text,text) to authenticated, service_role;
grant execute on function suppress_contact(text,text) to authenticated, service_role;
grant execute on function pause_all_outreach(text) to authenticated, service_role;

insert into growth_autonomy_switch(scope,key,mode) values ('global','','off') on conflict do nothing;;
