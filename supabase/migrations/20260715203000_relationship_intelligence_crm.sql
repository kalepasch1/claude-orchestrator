-- Portfolio Relationship Intelligence CRM. Fail-closed: delivery ships OFF.
create extension if not exists pgcrypto;

create table if not exists crm_accounts(
 id uuid primary key default gen_random_uuid(), app text not null, name text not null, domain text,
 lifecycle_stage text not null default 'prospect', owner text, value_estimate numeric(14,2),
 relationship_health int not null default 50 check(relationship_health between 0 and 100),
 next_best_action text,next_action_at timestamptz,tags text[] not null default '{}',metadata jsonb not null default '{}',
 created_at timestamptz not null default now(),updated_at timestamptz not null default now(),unique(app,domain));

create table if not exists crm_contacts(
 id uuid primary key default gen_random_uuid(),account_id uuid references crm_accounts(id) on delete set null,app text not null,
 email text,phone text,first_name text,last_name text,title text,timezone text,preferred_channel text not null default 'email',
 preferred_tone text not null default 'adaptive',lifecycle_stage text not null default 'prospect',consent_status text not null default 'unknown',
 marketing_allowed boolean not null default false,do_not_contact boolean not null default false,consent_source text,consent_at timestamptz,
 last_contacted_at timestamptz,next_contact_at timestamptz,relationship_health int not null default 50 check(relationship_health between 0 and 100),
 response_propensity numeric(6,5),tags text[] not null default '{}',metadata jsonb not null default '{}',created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),unique(app,email));
create index if not exists crm_contacts_due_idx on crm_contacts(app,next_contact_at) where do_not_contact=false;

create table if not exists crm_campaigns(
 id uuid primary key default gen_random_uuid(),app text not null,name text not null,objective text,audience_definition jsonb not null default '{}',
 status text not null default 'draft',channel text not null default 'email',sequence jsonb not null default '[]',daily_cap int not null default 25,
 weekly_cap int not null default 75,quiet_hours jsonb not null default '{"start":20,"end":8}',experiment_plan jsonb not null default '{}',
 created_by text,created_at timestamptz not null default now(),updated_at timestamptz not null default now());

create table if not exists crm_delivery_control(
 scope text not null check(scope in('global','app','campaign')),key text not null default '',mode text not null default 'off' check(mode in('off','approval','auto')),
 require_first_n int not null default 25,daily_cap int not null default 25,commissioned_by text,commissioned_at timestamptz,reason text,
 updated_at timestamptz not null default now(),primary key(scope,key));
insert into crm_delivery_control(scope,key,mode,reason) values('global','','off','Default-deny: explicit commissioning required.') on conflict do nothing;

create table if not exists crm_suppressions(
 id uuid primary key default gen_random_uuid(),app text,email_hash text,phone_hash text,reason text not null,source text,created_at timestamptz not null default now(),
 unique nulls not distinct(app,email_hash,phone_hash));

create table if not exists crm_drafts(
 id uuid primary key default gen_random_uuid(),app text not null,campaign_id uuid references crm_campaigns(id) on delete set null,
 contact_id uuid not null references crm_contacts(id) on delete cascade,channel text not null default 'email',subject text,body_text text not null,body_html text,
 tone_profile jsonb not null default '{}',timing_rationale text,recommendation_rationale text,source_facts jsonb not null default '[]',attachments jsonb not null default '[]',
 status text not null default 'draft',risk_level text not null default 'unreviewed',review_receipt jsonb not null default '{}',
 content_hash text generated always as(encode(digest(coalesce(subject,'')||E'\n'||body_text,'sha256'),'hex')) stored,scheduled_at timestamptz,
 approved_by text,approved_at timestamptz,created_by text,created_at timestamptz not null default now(),updated_at timestamptz not null default now());
create index if not exists crm_drafts_queue_idx on crm_drafts(status,scheduled_at);

create table if not exists crm_interactions(
 id uuid primary key default gen_random_uuid(),app text not null,account_id uuid references crm_accounts(id) on delete set null,
 contact_id uuid references crm_contacts(id) on delete set null,campaign_id uuid references crm_campaigns(id) on delete set null,draft_id uuid references crm_drafts(id) on delete set null,
 direction text not null check(direction in('inbound','outbound','internal')),channel text not null,event_type text not null,provider text,provider_ref text,
 subject text,summary text,sentiment numeric(5,4),intent text,occurred_at timestamptz not null default now(),metadata jsonb not null default '{}',
 unique nulls not distinct(provider,provider_ref,event_type));
create index if not exists crm_interactions_contact_idx on crm_interactions(contact_id,occurred_at desc);

create table if not exists crm_relationship_facts(
 id uuid primary key default gen_random_uuid(),app text not null,account_id uuid references crm_accounts(id) on delete cascade,contact_id uuid references crm_contacts(id) on delete cascade,
 interaction_id uuid references crm_interactions(id) on delete set null,fact_type text not null,fact_key text not null,fact_value jsonb not null,
 confidence numeric(5,4) not null default .5,verification_status text not null default 'inferred',valid_from timestamptz not null default now(),valid_until timestamptz,
 superseded_by uuid references crm_relationship_facts(id),created_at timestamptz not null default now());

create table if not exists crm_recommendations(
 id uuid primary key default gen_random_uuid(),app text not null,account_id uuid references crm_accounts(id) on delete cascade,contact_id uuid references crm_contacts(id) on delete cascade,
 kind text not null,title text not null,rationale text not null,proposed_action jsonb not null default '{}',confidence numeric(5,4) not null default .5,
 expected_value numeric(14,2),due_at timestamptz,status text not null default 'open',created_at timestamptz not null default now(),resolved_at timestamptz);

create table if not exists crm_send_receipts(
 id uuid primary key default gen_random_uuid(),draft_id uuid not null references crm_drafts(id) on delete cascade,app text not null,provider text not null,
 provider_ref text,decision text not null,reasons jsonb not null default '[]',policy_version text not null default 'crm-send-v1',requested_by text,created_at timestamptz not null default now());

create or replace function crm_normalize_email(p_email text) returns text language sql immutable as $$select lower(trim(coalesce(p_email,'')))$$;
create or replace function crm_email_hash(p_email text) returns text language sql immutable as $$select encode(digest(crm_normalize_email(p_email),'sha256'),'hex')$$;
create or replace function crm_suppress_email(p_app text,p_email text,p_reason text,p_source text default 'provider') returns crm_suppressions language plpgsql security definer set search_path=public as $$
declare r crm_suppressions;begin
 insert into crm_suppressions(app,email_hash,reason,source) values(p_app,crm_email_hash(p_email),p_reason,p_source)
 on conflict(app,email_hash,phone_hash) do update set reason=excluded.reason,source=excluded.source returning * into r;
 update crm_contacts set do_not_contact=true,consent_status='opted_out',updated_at=now() where app=p_app and crm_email_hash(email)=crm_email_hash(p_email);
 return r;end$$;

create or replace function crm_commission(p_scope text,p_key text,p_mode text,p_by text,p_reason text default null,p_first_n int default 25,p_daily_cap int default 25)
returns crm_delivery_control language plpgsql security definer set search_path=public as $$declare r crm_delivery_control;begin
 if p_scope not in('global','app','campaign') or p_mode not in('off','approval','auto') then raise exception 'invalid commission';end if;
 insert into crm_delivery_control(scope,key,mode,require_first_n,daily_cap,commissioned_by,commissioned_at,reason,updated_at)
 values(p_scope,coalesce(p_key,''),p_mode,greatest(p_first_n,0),greatest(p_daily_cap,1),p_by,case when p_mode='off' then null else now() end,p_reason,now())
 on conflict(scope,key) do update set mode=excluded.mode,require_first_n=excluded.require_first_n,daily_cap=excluded.daily_cap,commissioned_by=excluded.commissioned_by,
 commissioned_at=excluded.commissioned_at,reason=excluded.reason,updated_at=now() returning * into r;return r;end$$;

create or replace function crm_send_allowed(p_draft_id uuid,p_now timestamptz default now()) returns table(allowed boolean,reasons jsonb)
language plpgsql stable security definer set search_path=public as $$declare d crm_drafts;c crm_contacts;camp crm_campaigns;g crm_delivery_control;a crm_delivery_control;cc crm_delivery_control;b jsonb:='[]';n int;begin
 select * into d from crm_drafts where id=p_draft_id;if not found then return query select false,'["draft not found"]'::jsonb;return;end if;
 select * into c from crm_contacts where id=d.contact_id;select * into camp from crm_campaigns where id=d.campaign_id;
 select * into g from crm_delivery_control where scope='global' and key='';select * into a from crm_delivery_control where scope='app' and key=d.app;
 if d.campaign_id is not null then select * into cc from crm_delivery_control where scope='campaign' and key=d.campaign_id::text;end if;
 if coalesce(g.mode,'off')='off' then b:=b||'"global delivery not commissioned"'::jsonb;end if;
 if coalesce(a.mode,'off')='off' then b:=b||'"app delivery not commissioned"'::jsonb;end if;
 if d.campaign_id is not null and coalesce(cc.mode,'off')='off' then b:=b||'"campaign delivery not commissioned"'::jsonb;end if;
 if d.status not in('approved','scheduled') or d.approved_at is null then b:=b||'"exact draft not approved"'::jsonb;end if;
 if d.scheduled_at is not null and d.scheduled_at>p_now then b:=b||'"scheduled time not reached"'::jsonb;end if;
 if c.do_not_contact or c.consent_status='opted_out' then b:=b||'"contact opted out"'::jsonb;end if;
 if not c.marketing_allowed then b:=b||'"marketing permission absent"'::jsonb;end if;
 if c.email is null or position('@' in c.email)=0 then b:=b||'"valid email absent"'::jsonb;end if;
 if exists(select 1 from crm_suppressions s where(s.app is null or s.app=d.app)and s.email_hash=crm_email_hash(c.email))then b:=b||'"suppression match"'::jsonb;end if;
 select count(*) into n from crm_interactions i where i.app=d.app and i.direction='outbound' and i.event_type='sent' and i.occurred_at>=date_trunc('day',p_now);
 if n>=least(coalesce(g.daily_cap,25),coalesce(a.daily_cap,25),coalesce(cc.daily_cap,2147483647))then b:=b||'"daily cap reached"'::jsonb;end if;
 return query select jsonb_array_length(b)=0,b;end$$;

create or replace view crm_relationship_cockpit as select c.id contact_id,c.app,c.first_name,c.last_name,c.email,c.title,c.lifecycle_stage,c.relationship_health,
 c.last_contacted_at,c.next_contact_at,c.response_propensity,c.marketing_allowed,c.do_not_contact,a.id account_id,a.name account_name,a.value_estimate,a.next_best_action,
 (select count(*) from crm_interactions i where i.contact_id=c.id) interaction_count,
 (select max(i.occurred_at) from crm_interactions i where i.contact_id=c.id and i.direction='inbound') last_inbound_at,
 (select count(*) from crm_recommendations r where r.contact_id=c.id and r.status='open') open_recommendations from crm_contacts c left join crm_accounts a on a.id=c.account_id;

do $$declare t text;begin foreach t in array array['crm_accounts','crm_contacts','crm_campaigns','crm_delivery_control','crm_suppressions','crm_drafts','crm_interactions','crm_relationship_facts','crm_recommendations','crm_send_receipts'] loop
 execute format('alter table %I enable row level security',t);execute format('drop policy if exists %I_ops_all on %I',t,t);
 execute format('create policy %I_ops_all on %I for all to authenticated using (exists(select 1 from fleet_approvers f where lower(f.email)=lower(auth.jwt()->>''email''))) with check (exists(select 1 from fleet_approvers f where lower(f.email)=lower(auth.jwt()->>''email'')))',t,t);end loop;end$$;
revoke all on function crm_send_allowed(uuid,timestamptz),crm_commission(text,text,text,text,text,int,int),crm_suppress_email(text,text,text,text) from public;
grant execute on function crm_send_allowed(uuid,timestamptz),crm_commission(text,text,text,text,text,int,int),crm_suppress_email(text,text,text,text) to authenticated,service_role;
grant select on crm_relationship_cockpit to authenticated,service_role;
