-- Growth CRM autopilot: business-hour SLAs, outcome learning, matching,
-- portfolio rollups, and a no-PII Slack alert outbox.
begin;

alter table growth_crm_ownership_rules add column if not exists timezone text not null default 'America/New_York';
alter table growth_crm_ownership_rules add column if not exists business_start time not null default '09:00';
alter table growth_crm_ownership_rules add column if not exists business_end time not null default '17:00';
alter table growth_crm_ownership_rules add column if not exists escalation_minutes int not null default 60;
alter table growth_crm_ownership_rules add column if not exists slack_channel_id text;
update growth_crm_ownership_rules set slack_channel_id='C0BH7DF3P51' where app='sustainable-barks';

alter table growth_crm_leads add column if not exists account_key text;
alter table growth_crm_leads add column if not exists preferred_channel text not null default 'email';
alter table growth_crm_leads add column if not exists strategy_reason text;

create or replace function growth_business_due(p_start timestamptz, p_hours int, p_timezone text default 'America/New_York')
returns timestamptz language plpgsql immutable as $$
declare cursor_at timestamptz := date_trunc('hour',p_start); remaining int := greatest(p_hours,1); local_at timestamp; guard int := 0;
begin
  while remaining > 0 and guard < 1000 loop
    cursor_at := cursor_at + interval '1 hour'; guard := guard + 1;
    local_at := cursor_at at time zone p_timezone;
    if extract(isodow from local_at) between 1 and 5 and local_at::time >= time '09:00' and local_at::time < time '17:00' then remaining := remaining - 1; end if;
  end loop;
  return cursor_at;
end $$;

create table if not exists growth_crm_communications (
  id uuid primary key default gen_random_uuid(), lead_id uuid not null references growth_crm_leads(id) on delete cascade,
  event_type text not null check(event_type in ('prepared','sent','delivered','opened','replied','bounced','won','lost')),
  template_key text, channel text not null default 'email', provider_ref text, occurred_at timestamptz not null default now(),
  metadata jsonb not null default '{}', unique(provider_ref,event_type)
);
create index if not exists growth_crm_communications_lead_idx on growth_crm_communications(lead_id,occurred_at desc);

create table if not exists growth_crm_template_performance (
  app text not null, lead_type text not null, template_key text not null, channel text not null default 'email',
  sends int not null default 0, replies int not null default 0, wins int not null default 0, bounces int not null default 0,
  score numeric generated always as ((wins*5 + replies*2 + 1)::numeric / greatest(sends+bounces+2,2)) stored,
  updated_at timestamptz not null default now(), primary key(app,lead_type,template_key,channel)
);

create table if not exists growth_crm_partner_capacity (
  id uuid primary key default gen_random_uuid(), app text not null, source_kind text not null, source_ref text not null,
  region text, capabilities text[] not null default '{}', capacity int not null default 1, available boolean not null default true,
  updated_at timestamptz not null default now(), unique(app,source_kind,source_ref)
);
create table if not exists growth_crm_matches (
  id uuid primary key default gen_random_uuid(), lead_id uuid not null references growth_crm_leads(id) on delete cascade,
  capacity_id uuid not null references growth_crm_partner_capacity(id) on delete cascade, score int not null,
  reason text not null, status text not null default 'suggested', created_at timestamptz not null default now(),
  unique(lead_id,capacity_id)
);

create table if not exists growth_crm_accounts (
  id uuid primary key default gen_random_uuid(), app text not null, account_key text not null, account_type text not null default 'hotel_group',
  status text not null default 'prospect', property_count int not null default 0, lifetime_quantity numeric not null default 0,
  expansion_score int not null default 0, next_expansion_at timestamptz, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique(app,account_key)
);
create table if not exists growth_crm_properties (
  id uuid primary key default gen_random_uuid(), account_id uuid not null references growth_crm_accounts(id) on delete cascade,
  property_ref text not null, region text, status text not null default 'prospect', program_quantity numeric not null default 0,
  cadence text, created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique(account_id,property_ref)
);

create table if not exists growth_crm_alerts (
  id uuid primary key default gen_random_uuid(), app text not null, lead_id uuid references growth_crm_leads(id) on delete cascade,
  severity text not null, kind text not null, title text not null, detail text not null, destination text not null default 'slack',
  channel_id text, status text not null default 'pending', dedup_key text not null unique,
  created_at timestamptz not null default now(), delivered_at timestamptz
);

create or replace function growth_crm_prepare_lead() returns trigger language plpgsql as $$
declare rule growth_crm_ownership_rules; best growth_crm_template_performance;
begin
  select * into rule from growth_crm_ownership_rules where app=new.app and lead_type=new.lead_type;
  if found then new.response_due_at := growth_business_due(coalesce(new.created_at,now()),rule.sla_hours,rule.timezone); end if;
  new.account_key := coalesce(new.account_key,case when new.lead_type in ('hotel_order','hotel_inquiry') then new.actor_hash end);
  select * into best from growth_crm_template_performance where app=new.app and lead_type=new.lead_type order by score desc,sends asc limit 1;
  if found then new.preferred_channel:=best.channel; new.strategy_reason:='learned from '||best.sends||' sends; score '||round(best.score,2); else new.strategy_reason:='exploration baseline'; end if;
  return new;
end $$;
drop trigger if exists growth_crm_prepare_lead_trg on growth_crm_leads;
create trigger growth_crm_prepare_lead_trg before insert or update of lead_type,actor_hash on growth_crm_leads for each row execute function growth_crm_prepare_lead();

create or replace function record_growth_crm_communication(p_lead_id uuid,p_event_type text,p_template_key text default null,p_channel text default 'email',p_provider_ref text default null,p_metadata jsonb default '{}')
returns growth_crm_leads language plpgsql security definer set search_path=public as $$
declare lead growth_crm_leads; metric_event text;
begin
  insert into growth_crm_communications(lead_id,event_type,template_key,channel,provider_ref,metadata)
  values(p_lead_id,p_event_type,p_template_key,coalesce(p_channel,'email'),p_provider_ref,coalesce(p_metadata,'{}')) on conflict(provider_ref,event_type) do nothing;
  select * into lead from growth_crm_leads where id=p_lead_id; if not found then raise exception 'lead not found'; end if;
  if p_template_key is not null and p_event_type in ('sent','replied','won','bounced') then
    insert into growth_crm_template_performance(app,lead_type,template_key,channel,sends,replies,wins,bounces)
    values(lead.app,lead.lead_type,p_template_key,coalesce(p_channel,'email'),(p_event_type='sent')::int,(p_event_type='replied')::int,(p_event_type='won')::int,(p_event_type='bounced')::int)
    on conflict(app,lead_type,template_key,channel) do update set sends=growth_crm_template_performance.sends+excluded.sends,replies=growth_crm_template_performance.replies+excluded.replies,wins=growth_crm_template_performance.wins+excluded.wins,bounces=growth_crm_template_performance.bounces+excluded.bounces,updated_at=now();
  end if;
  update growth_crm_leads set status=case when p_event_type='replied' then 'working' when p_event_type='bounced' then 'waiting' when p_event_type='won' then 'won' when p_event_type='lost' then 'lost' else status end,
    last_touch_at=case when p_event_type in ('sent','delivered','opened','replied') then now() else last_touch_at end,last_outcome=p_event_type,updated_at=now() where id=p_lead_id returning * into lead;
  return lead;
end $$;

create or replace function refresh_growth_crm_matches(p_app text default 'sustainable-barks') returns int language plpgsql security definer set search_path=public as $$
declare changed int;
begin
  insert into growth_crm_partner_capacity(app,source_kind,source_ref,region,capabilities,capacity)
  select app,lead_type,source_ref,region,case when lead_type='shelter' then array['inventory','distribution','stories'] when lead_type='volunteer' then array[coalesce(intent,'general')] else array['hotel-program'] end,coalesce(quantity,1)::int
  from growth_crm_leads where app=p_app and lead_type in ('shelter','volunteer','hotel_order') and status not in ('lost')
  on conflict(app,source_kind,source_ref) do update set region=excluded.region,capabilities=excluded.capabilities,capacity=excluded.capacity,available=true,updated_at=now();
  insert into growth_crm_matches(lead_id,capacity_id,score,reason)
  select l.id,c.id,(case when l.region is not null and c.region=l.region then 80 else 35 end)+(case when l.lead_type='donation' and c.source_kind='shelter' then 15 when l.lead_type='hotel_order' and c.source_kind in ('shelter','volunteer') then 10 else 0 end),
    case when l.region is not null and c.region=l.region then 'Same-region capacity match' else 'Portfolio capacity match; confirm travel radius' end
  from growth_crm_leads l join growth_crm_partner_capacity c on c.app=l.app and c.available and c.source_ref<>l.source_ref
  where l.app=p_app and l.status in ('new','working','waiting') and ((l.lead_type='donation' and c.source_kind='shelter') or (l.lead_type='hotel_order' and c.source_kind in ('shelter','volunteer')) or (l.lead_type='volunteer' and c.source_kind='shelter'))
  on conflict(lead_id,capacity_id) do update set score=excluded.score,reason=excluded.reason;
  get diagnostics changed=row_count; return changed;
end $$;

create or replace function run_growth_crm_automation(p_app text default 'sustainable-barks') returns setof growth_crm_alerts language plpgsql security definer set search_path=public as $$
begin
  perform refresh_growth_crm_matches(p_app);
  insert into growth_crm_alerts(app,lead_id,severity,kind,title,detail,channel_id,dedup_key)
  select l.app,l.id,case when l.response_due_at<now() then 'critical' else 'warning' end,case when l.response_due_at<now() then 'sla_overdue' else 'sla_approaching' end,
    case when l.response_due_at<now() then 'Overdue ' else 'Due soon ' end||replace(l.lead_type,'_',' '),
    l.owner_label||' · P'||l.priority||' · '||coalesce(l.region,'region unknown'),r.slack_channel_id,
    'sla:'||l.id||':'||case when l.response_due_at<now() then 'overdue' else 'approaching' end
  from growth_crm_leads l join growth_crm_ownership_rules r on r.app=l.app and r.lead_type=l.lead_type
  where l.app=p_app and l.status in ('new','working','waiting') and l.response_due_at < now()+make_interval(mins=>r.escalation_minutes)
  on conflict(dedup_key) do nothing;
  insert into growth_crm_alerts(app,lead_id,severity,kind,title,detail,channel_id,dedup_key)
  select l.app,l.id,'info','expansion','Hotel account ready for expansion',a.property_count||' properties · '||a.lifetime_quantity||' total quantity',r.slack_channel_id,'expansion:'||a.id||':'||date_trunc('month',now())::date
  from growth_crm_accounts a join growth_crm_leads l on l.app=a.app and l.account_key=a.account_key join growth_crm_ownership_rules r on r.app=l.app and r.lead_type=l.lead_type
  where a.app=p_app and a.expansion_score>=70 on conflict(dedup_key) do nothing;
  return query select * from growth_crm_alerts where app=p_app and status='pending' order by created_at;
end $$;

create or replace function sync_growth_crm_accounts() returns trigger language plpgsql as $$
declare aid uuid;
begin
  if new.account_key is null or new.lead_type not in ('hotel_order','hotel_inquiry') then return new; end if;
  insert into growth_crm_accounts(app,account_key,property_count,lifetime_quantity,expansion_score,next_expansion_at)
  values(new.app,new.account_key,1,coalesce(new.quantity,0),least(100,20+coalesce(new.quantity,0)::int),now()+interval '30 days')
  on conflict(app,account_key) do update set lifetime_quantity=growth_crm_accounts.lifetime_quantity+coalesce(new.quantity,0),property_count=growth_crm_accounts.property_count+1,expansion_score=least(100,growth_crm_accounts.expansion_score+15),updated_at=now() returning id into aid;
  insert into growth_crm_properties(account_id,property_ref,region,status,program_quantity,cadence) values(aid,new.source_ref,new.region,case when new.lead_type='hotel_order' then 'active' else 'prospect' end,coalesce(new.quantity,0),new.frequency) on conflict(account_id,property_ref) do update set program_quantity=excluded.program_quantity,cadence=excluded.cadence,updated_at=now();
  return new;
end $$;
drop trigger if exists sync_growth_crm_accounts_trg on growth_crm_leads;
create trigger sync_growth_crm_accounts_trg after insert on growth_crm_leads for each row execute function sync_growth_crm_accounts();

create or replace view growth_crm_match_feed as select m.*,l.app,l.lead_type,l.region,c.source_kind,c.source_ref as match_source_ref,c.region as match_region,c.capabilities,c.capacity from growth_crm_matches m join growth_crm_leads l on l.id=m.lead_id join growth_crm_partner_capacity c on c.id=m.capacity_id;
create or replace view growth_crm_account_feed as select a.*,count(p.id) as tracked_properties,coalesce(sum(p.program_quantity),0) as tracked_quantity from growth_crm_accounts a left join growth_crm_properties p on p.account_id=a.id group by a.id;

alter table growth_crm_communications enable row level security; alter table growth_crm_template_performance enable row level security; alter table growth_crm_partner_capacity enable row level security; alter table growth_crm_matches enable row level security; alter table growth_crm_accounts enable row level security; alter table growth_crm_properties enable row level security; alter table growth_crm_alerts enable row level security;
grant execute on function record_growth_crm_communication(uuid,text,text,text,text,jsonb) to authenticated,service_role;
grant execute on function refresh_growth_crm_matches(text) to authenticated,service_role;
grant execute on function run_growth_crm_automation(text) to authenticated,service_role;
grant select on growth_crm_match_feed,growth_crm_account_feed,growth_crm_alerts,growth_crm_template_performance to authenticated,service_role;

commit;
