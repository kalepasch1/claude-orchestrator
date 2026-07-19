-- 0040_growth_crm_routing.sql
-- Privacy-preserving portfolio CRM routing. Product databases retain contact PII;
-- the control plane stores only an opaque source reference plus operating metadata.

begin;

create table if not exists growth_crm_ownership_rules (
  app text not null,
  lead_type text not null,
  owner_id text not null,
  owner_label text not null,
  sla_hours int not null default 24,
  priority int not null default 50,
  active boolean not null default true,
  primary key (app, lead_type)
);

create table if not exists growth_crm_templates (
  app text not null,
  lead_type text not null,
  step int not null,
  template_key text not null,
  subject_template text not null,
  body_template text not null,
  wait_hours int not null default 72,
  primary key (app, lead_type, step)
);

create table if not exists growth_crm_leads (
  id uuid primary key default gen_random_uuid(),
  app text not null,
  source_ref text not null,
  lead_type text not null,
  actor_hash text,
  segment text,
  region text,
  intent text,
  channel text not null default 'direct',
  quantity numeric,
  frequency text,
  next_step text,
  owner_id text not null,
  owner_label text not null,
  status text not null default 'new',
  priority int not null default 50,
  response_due_at timestamptz not null,
  next_action_at timestamptz,
  sequence_step int not null default 0,
  last_touch_at timestamptz,
  last_outcome text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (app, source_ref)
);

create index if not exists growth_crm_leads_owner_due_idx
  on growth_crm_leads(owner_id, status, response_due_at);
create index if not exists growth_crm_leads_app_status_idx
  on growth_crm_leads(app, status, created_at desc);

create table if not exists growth_crm_touches (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references growth_crm_leads(id) on delete cascade,
  step int not null,
  template_key text not null,
  status text not null default 'scheduled',
  scheduled_at timestamptz not null,
  completed_at timestamptz,
  outcome text,
  created_at timestamptz not null default now(),
  unique (lead_id, step)
);

create index if not exists growth_crm_touches_due_idx
  on growth_crm_touches(status, scheduled_at);

insert into growth_crm_ownership_rules(app, lead_type, owner_id, owner_label, sla_hours, priority) values
  ('sustainable-barks', 'hotel_order', 'hotel-partnerships', 'Hotel partnerships', 4, 90),
  ('sustainable-barks', 'hotel_inquiry', 'hotel-partnerships', 'Hotel partnerships', 8, 80),
  ('sustainable-barks', 'shelter', 'shelter-network', 'Shelter network', 24, 70),
  ('sustainable-barks', 'volunteer', 'community', 'Community operations', 48, 50),
  ('sustainable-barks', 'donation', 'community', 'Community operations', 24, 60),
  ('sustainable-barks', 'contact', 'partnerships', 'Partnerships', 24, 65)
on conflict (app, lead_type) do update set
  owner_id=excluded.owner_id, owner_label=excluded.owner_label,
  sla_hours=excluded.sla_hours, priority=excluded.priority, active=true;

insert into growth_crm_templates(app, lead_type, step, template_key, subject_template, body_template, wait_hours) values
  ('sustainable-barks','hotel_order',1,'hotel_order_confirm','Your Sustainable Barks starter program','Thanks for reserving a starter program. Here is the proposed quantity, delivery plan, and next step.',24),
  ('sustainable-barks','hotel_order',2,'hotel_order_proof','A practical dog-welcome rollout','Here is a concise implementation plan and the reporting your property will receive.',72),
  ('sustainable-barks','hotel_order',3,'hotel_order_close','Ready to confirm delivery?','Reply with the best delivery window and we will finalize the first program.',120),
  ('sustainable-barks','hotel_inquiry',1,'hotel_intro','A simpler dog-welcome program','Thanks for reaching out. We can recommend a starter size based on your dog-friendly stays.',48),
  ('sustainable-barks','hotel_inquiry',2,'hotel_followup','A suggested Sustainable Barks starter plan','Here is the lowest-work way to test the program at one property.',96),
  ('sustainable-barks','shelter',1,'shelter_welcome','Sustainable Barks shelter partnership','Thanks for registering. We will match your stated need with the most practical next step.',72),
  ('sustainable-barks','shelter',2,'shelter_followup','Your first partnership opportunity','Here is the supply, volunteer, or hotel-support path that best fits your organization.',120),
  ('sustainable-barks','volunteer',1,'volunteer_welcome','You are on the Sustainable Barks volunteer list','Thanks for joining. We will contact you only when a nearby role matches your availability.',168),
  ('sustainable-barks','donation',1,'donation_instructions','Your Sustainable Barks donation handoff','Thanks for offering useful pet supplies. Here are the safest next-step instructions.',72),
  ('sustainable-barks','contact',1,'contact_response','Following up from Sustainable Barks','Thanks for contacting us. Your message has been routed to the person best able to help.',72)
on conflict (app, lead_type, step) do update set
  template_key=excluded.template_key, subject_template=excluded.subject_template,
  body_template=excluded.body_template, wait_hours=excluded.wait_hours;

create or replace function ingest_growth_lead(
  p_app text,
  p_source_ref text,
  p_lead_type text,
  p_actor_hash text default null,
  p_region text default null,
  p_intent text default null,
  p_channel text default 'direct',
  p_quantity numeric default null,
  p_frequency text default null,
  p_next_step text default null
) returns uuid
language plpgsql security definer set search_path=public as $$
declare
  rule growth_crm_ownership_rules;
  v_lead_id uuid;
  template growth_crm_templates;
  segment_value text;
begin
  if p_app is null or length(trim(p_app)) < 2 or p_source_ref is null or length(trim(p_source_ref)) < 8 then
    raise exception 'app and opaque source_ref are required';
  end if;
  if p_actor_hash is not null and (position('@' in p_actor_hash) > 0 or length(p_actor_hash) < 16) then
    raise exception 'actor_hash must be opaque';
  end if;
  if position('@' in p_source_ref) > 0 then raise exception 'source_ref must not contain PII'; end if;

  select * into rule from growth_crm_ownership_rules
   where app=p_app and lead_type=p_lead_type and active=true;
  if not found then
    rule := row(p_app,p_lead_type,'partnerships','Partnerships',24,50,true)::growth_crm_ownership_rules;
  end if;
  segment_value := p_app||'/'||replace(p_lead_type,'_','-');

  insert into growth_crm_leads(
    app, source_ref, lead_type, actor_hash, segment, region, intent, channel,
    quantity, frequency, next_step, owner_id, owner_label, priority,
    response_due_at, next_action_at
  ) values (
    p_app, trim(p_source_ref), p_lead_type, p_actor_hash, segment_value,
    nullif(trim(coalesce(p_region,'')),''), nullif(trim(coalesce(p_intent,'')),''),
    coalesce(nullif(trim(p_channel),''),'direct'), p_quantity,
    nullif(trim(coalesce(p_frequency,'')),''), nullif(trim(coalesce(p_next_step,'')),''),
    rule.owner_id, rule.owner_label, rule.priority,
    now() + make_interval(hours=>rule.sla_hours), now()
  )
  on conflict(app, source_ref) do update set
    intent=coalesce(excluded.intent,growth_crm_leads.intent),
    region=coalesce(excluded.region,growth_crm_leads.region),
    quantity=coalesce(excluded.quantity,growth_crm_leads.quantity),
    frequency=coalesce(excluded.frequency,growth_crm_leads.frequency),
    next_step=coalesce(excluded.next_step,growth_crm_leads.next_step),
    updated_at=now()
  returning id into v_lead_id;

  select * into template from growth_crm_templates
   where app=p_app and lead_type=p_lead_type and step=1;
  if found then
    insert into growth_crm_touches(lead_id,step,template_key,scheduled_at)
    values(v_lead_id,1,template.template_key,now()) on conflict(lead_id,step) do nothing;
    update growth_crm_leads set sequence_step=1 where id=v_lead_id;
  end if;

  perform emit_growth_event(
    p_app,'qualified_lead',segment_value,p_channel,'crm-intake',p_actor_hash,
    coalesce(p_quantity,0),
    jsonb_build_object('lead_type',p_lead_type,'owner',rule.owner_id,'next_step',p_next_step),
    'crm:'||p_app||':'||trim(p_source_ref)
  );

  if not exists(select 1 from growth_human_queue where app=p_app and prepared->>'lead_id'=v_lead_id::text and status='open') then
    insert into growth_human_queue(app,kind,actor_hash,segment,title,why,prepared)
    values(p_app,'lead_followup',p_actor_hash,segment_value,
      'Review new '||replace(p_lead_type,'_',' ')||' lead',
      'New registration requires an owner response before its SLA.',
      jsonb_build_object('lead_id',v_lead_id,'owner',rule.owner_id,'due_at',now()+make_interval(hours=>rule.sla_hours)));
  end if;
  return v_lead_id;
end $$;

create or replace function update_growth_crm_lead(
  p_lead_id uuid,
  p_status text default null,
  p_owner_id text default null,
  p_owner_label text default null,
  p_next_action_at timestamptz default null,
  p_outcome text default null
) returns growth_crm_leads
language plpgsql security definer set search_path=public as $$
declare lead growth_crm_leads; next_template growth_crm_templates;
begin
  if p_status is not null and p_status not in ('new','working','waiting','won','lost') then
    raise exception 'invalid CRM status';
  end if;
  update growth_crm_leads set
    status=coalesce(p_status,status), owner_id=coalesce(nullif(p_owner_id,''),owner_id),
    owner_label=coalesce(nullif(p_owner_label,''),owner_label),
    next_action_at=coalesce(p_next_action_at,next_action_at),
    last_outcome=coalesce(nullif(p_outcome,''),last_outcome),
    last_touch_at=case when p_outcome is not null then now() else last_touch_at end,
    updated_at=now()
  where id=p_lead_id returning * into lead;
  if not found then raise exception 'lead not found'; end if;

  if p_outcome is not null then
    update growth_crm_touches set status='completed',completed_at=now(),outcome=p_outcome
     where lead_id=p_lead_id and status='scheduled' and scheduled_at<=now();
    if lead.status not in ('won','lost') then
      select * into next_template from growth_crm_templates
       where app=lead.app and lead_type=lead.lead_type and step=lead.sequence_step+1;
      if found then
        insert into growth_crm_touches(lead_id,step,template_key,scheduled_at)
        values(lead.id,next_template.step,next_template.template_key,now()+make_interval(hours=>next_template.wait_hours))
        on conflict(lead_id,step) do nothing;
        update growth_crm_leads set sequence_step=next_template.step,
          next_action_at=now()+make_interval(hours=>next_template.wait_hours),updated_at=now()
         where id=lead.id returning * into lead;
      end if;
    end if;
  end if;
  return lead;
end $$;

create or replace view growth_crm_feed as
select l.*,
  (l.status in ('new','working','waiting') and l.response_due_at < now()) as overdue,
  t.id as touch_id, t.step as touch_step, t.template_key, t.scheduled_at as touch_due_at,
  tm.subject_template, tm.body_template
from growth_crm_leads l
left join lateral (
  select * from growth_crm_touches x where x.lead_id=l.id and x.status='scheduled'
  order by x.scheduled_at limit 1
) t on true
left join growth_crm_templates tm
  on tm.app=l.app and tm.lead_type=l.lead_type and tm.step=t.step;

create or replace view growth_action_feed as
select 'task'::text as item_kind, t.id::text as item_id, p.name as app, t.slug as title,
       t.state::text as status, t.note as detail, t.created_at
from tasks t join projects p on p.id=t.project_id
where t.kind='gtm' and t.state in ('QUEUED','WAITING','BLOCKED','RETRY')
union all
select 'approval',a.id::text,a.project,a.title,a.status::text,a.why,a.created_at
from approvals a where a.status='pending' and a.kind in ('gtm','proposal','material')
union all
select 'human:'||h.kind,h.id::text,h.app,h.title,h.status,h.why,h.created_at
from growth_human_queue h where h.status='open'
union all
select 'crm_lead',l.id::text,l.app,'Follow up: '||replace(l.lead_type,'_',' '),l.status,
       l.owner_label||' · due '||to_char(l.response_due_at,'YYYY-MM-DD HH24:MI'),l.created_at
from growth_crm_leads l where l.status in ('new','working','waiting')
order by created_at desc;

do $$ declare tbl text; begin
  foreach tbl in array array['growth_crm_ownership_rules','growth_crm_templates','growth_crm_leads','growth_crm_touches'] loop
    execute format('alter table %I enable row level security',tbl);
    execute format('drop policy if exists %I_sel on %I',tbl,tbl);
    execute format('create policy %I_sel on %I for select to authenticated using (true)',tbl,tbl);
  end loop;
end $$;

grant execute on function ingest_growth_lead(text,text,text,text,text,text,text,numeric,text,text) to anon,authenticated,service_role;
grant execute on function update_growth_crm_lead(uuid,text,text,text,timestamptz,text) to authenticated,service_role;
grant select on growth_crm_feed to authenticated,service_role;

commit;
