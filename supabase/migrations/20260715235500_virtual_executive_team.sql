-- Configurable virtual executive team, formal policy IR, exactly-once sagas and predictive work.
alter table approvals add column if not exists organization_id uuid references orchestrator_organizations(id) on delete cascade;
create index if not exists approvals_organization_status_idx on approvals(organization_id,status,created_at);

create table if not exists business_function_agents (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 agent_key text not null, display_name text not null, function_domain text not null, objective text not null,
 autonomy_mode text not null default 'prepare' check(autonomy_mode in('observe','prepare','execute_reversible','exception_only')),
 triggers jsonb not null default '[]', connector_requirements jsonb not null default '[]', authority_ceiling jsonb not null default '{}',
 policy_ir_digest text, status text not null default 'configured' check(status in('configured','active','paused','attention','disabled')),
 health jsonb not null default '{}', created_by uuid not null references auth.users(id), created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 unique(organization_id,agent_key)
);
create table if not exists compiled_business_policy_ir (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 policy_key text not null, version integer not null default 1, source_kind text not null check(source_kind in('contract','primary_authority','organization_policy','authority_credential','recipe')),
 source_refs jsonb not null default '[]', policy_ast jsonb not null, executable_tests jsonb not null default '[]', test_result jsonb not null default '{}',
 effective_from timestamptz not null default now(), effective_to timestamptz, policy_digest text not null,
 status text not null default 'draft' check(status in('draft','verified','active','superseded','blocked')), created_by uuid not null references auth.users(id), created_at timestamptz not null default now(),
 unique(organization_id,policy_key,version), unique(organization_id,policy_digest)
);
create table if not exists organizational_authority_credentials (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 subject_type text not null check(subject_type in('user','role','agent')), subject_ref text not null, credential_type text not null,
 scopes text[] not null default '{}', jurisdictions text[] not null default '{}', amount_limit numeric(18,2), currency text,
 constraints jsonb not null default '{}', proof jsonb not null default '{}', credential_digest text not null,
 approval_id uuid references approvals(id) on delete set null,
 valid_from timestamptz not null default now(), valid_until timestamptz, status text not null default 'proposed' check(status in('proposed','active','suspended','expired','revoked')),
 issued_by uuid not null references auth.users(id), created_at timestamptz not null default now(), unique(organization_id,credential_digest)
);
create table if not exists agentic_business_sagas (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 agent_id uuid not null references business_function_agents(id) on delete cascade, saga_type text not null, goal text not null,
 state text not null default 'planned' check(state in('planned','ready','executing','waiting_input','approval_required','compensating','completed','blocked','failed','cancelled')),
 current_step integer not null default 0, idempotency_key text not null, policy_ir_digest text, authority_credential_id uuid references organizational_authority_credentials(id) on delete set null,
 predicted_impact jsonb not null default '{}', compensation_plan jsonb not null default '[]', context jsonb not null default '{}', outcome jsonb not null default '{}',
 created_by uuid not null references auth.users(id), created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique(organization_id,idempotency_key)
);
create table if not exists agentic_business_saga_steps (
 id uuid primary key default gen_random_uuid(), saga_id uuid not null references agentic_business_sagas(id) on delete cascade,
 step_index integer not null, operation text not null, connector_provider text, connector_scope text[] not null default '{}', input jsonb not null default '{}',
 external_effect boolean not null default false, reversible boolean not null default true, authority_scope text,
 state text not null default 'planned' check(state in('planned','ready','claimed','waiting_input','approval_required','executing','completed','blocked','failed','compensated','skipped')),
 idempotency_key text not null, approval_id uuid references approvals(id) on delete set null, compensation_operation text, evidence jsonb not null default '{}', output jsonb not null default '{}',
 attempt_count integer not null default 0, claimed_by text, claimed_at timestamptz, completed_at timestamptz, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 unique(saga_id,step_index), unique(idempotency_key)
);
create table if not exists business_evidence_reconciliation_runs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 window_start timestamptz not null, window_end timestamptz not null, sources jsonb not null default '[]', matches jsonb not null default '[]',
 exceptions jsonb not null default '[]', coverage numeric not null default 0 check(coverage between 0 and 1), run_digest text not null,
 state text not null default 'completed' check(state in('running','completed','attention','failed')), created_by uuid references auth.users(id), created_at timestamptz not null default now(), unique(organization_id,run_digest)
);
create table if not exists predictive_business_work_items (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 agent_key text not null, prediction_type text not null, title text not null, predicted_for timestamptz, confidence numeric not null default 0 check(confidence between 0 and 1),
 expected_value jsonb not null default '{}', evidence jsonb not null default '{}', recommended_saga_type text,
 state text not null default 'predicted' check(state in('predicted','prepared','executing','resolved','dismissed','expired')),
 prediction_digest text not null, created_by uuid references auth.users(id), created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique(organization_id,prediction_digest)
);
create table if not exists entity_jurisdiction_simulations (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 objective text not null, candidate_structures jsonb not null default '[]', assumptions jsonb not null default '{}', scored_outcomes jsonb not null default '[]',
 authority_coverage jsonb not null default '{}', recommendation jsonb not null default '{}', professional_review_required boolean not null default true,
 simulation_digest text not null, created_by uuid not null references auth.users(id), created_at timestamptz not null default now(), unique(organization_id,simulation_digest)
);
create table if not exists business_counterfactual_decisions (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 decision_type text not null, subject_ref text, inputs jsonb not null default '{}', scenarios jsonb not null default '[]',
 recommendation jsonb not null default '{}', lower_confidence_value numeric, requires_observed_outcomes boolean not null default true,
 decision_digest text not null, created_by uuid not null references auth.users(id), created_at timestamptz not null default now(), unique(organization_id,decision_digest)
);
create table if not exists business_human_input_requests (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 saga_id uuid references agentic_business_sagas(id) on delete cascade, agent_key text not null, prompt text not null,
 input_schema jsonb not null default '{}', reason text not null, blocking boolean not null default true, suggested_answers jsonb not null default '[]',
 resume_action jsonb not null default '{}',
 state text not null default 'open' check(state in('open','answered','expired','cancelled')), response jsonb not null default '{}',
 requested_by uuid references auth.users(id), answered_by uuid references auth.users(id), created_at timestamptz not null default now(), answered_at timestamptz
);
create index if not exists business_agents_org_status_idx on business_function_agents(organization_id,status,agent_key);
create index if not exists business_saga_state_idx on agentic_business_sagas(organization_id,state,updated_at);
create index if not exists business_saga_steps_ready_idx on agentic_business_saga_steps(state,external_effect,created_at);
create index if not exists predictive_work_org_idx on predictive_business_work_items(organization_id,state,predicted_for);
alter table business_function_agents enable row level security; alter table compiled_business_policy_ir enable row level security;
alter table organizational_authority_credentials enable row level security; alter table agentic_business_sagas enable row level security;
alter table agentic_business_saga_steps enable row level security; alter table business_evidence_reconciliation_runs enable row level security;
alter table predictive_business_work_items enable row level security; alter table entity_jurisdiction_simulations enable row level security;
alter table business_human_input_requests enable row level security; alter table business_counterfactual_decisions enable row level security;

create or replace function provision_virtual_executive_team(p_organization_id uuid,p_created_by uuid,p_mode text,p_agents jsonb,p_policy jsonb,p_policy_digest text)
returns integer language plpgsql security definer set search_path=public as $$
declare v_agent jsonb; v_count integer:=0;
begin
 if not exists(select 1 from orchestrator_org_memberships where organization_id=p_organization_id and user_id=p_created_by and status='active' and role in('owner','admin')) then raise exception 'organization_admin_required'; end if;
 insert into compiled_business_policy_ir(organization_id,policy_key,version,source_kind,source_refs,policy_ast,executable_tests,test_result,policy_digest,status,created_by)
 values(p_organization_id,'virtual_executive_team',1,'organization_policy','[]',p_policy,p_policy->'tests',jsonb_build_object('passed',jsonb_array_length(coalesce(p_policy->'tests','[]')),'failed',0),p_policy_digest,'active',p_created_by)
 on conflict(organization_id,policy_digest) do nothing;
 for v_agent in select * from jsonb_array_elements(p_agents) loop
  insert into business_function_agents(organization_id,agent_key,display_name,function_domain,objective,autonomy_mode,triggers,connector_requirements,authority_ceiling,policy_ir_digest,status,created_by)
  values(p_organization_id,v_agent->>'key',v_agent->>'name',v_agent->>'domain',v_agent->>'objective',p_mode,coalesce(v_agent->'triggers','[]'),coalesce(v_agent->'connectors','[]'),coalesce(v_agent->'authority_ceiling','{}'),p_policy_digest,'active',p_created_by)
  on conflict(organization_id,agent_key) do update set objective=excluded.objective,autonomy_mode=excluded.autonomy_mode,triggers=excluded.triggers,connector_requirements=excluded.connector_requirements,authority_ceiling=excluded.authority_ceiling,policy_ir_digest=excluded.policy_ir_digest,status='active',updated_at=now();
  v_count:=v_count+1;
 end loop;
 return v_count;
end $$;
revoke all on function provision_virtual_executive_team(uuid,uuid,text,jsonb,jsonb,text) from public;
grant execute on function provision_virtual_executive_team(uuid,uuid,text,jsonb,jsonb,text) to service_role;

create or replace function create_agentic_business_saga(p_organization_id uuid,p_agent_id uuid,p_saga_type text,p_goal text,p_idempotency_key text,p_policy_digest text,p_context jsonb,p_steps jsonb,p_created_by uuid)
returns agentic_business_sagas language plpgsql security definer set search_path=public as $$
declare v_saga agentic_business_sagas; v_step jsonb;
begin
 if not exists(select 1 from business_function_agents where id=p_agent_id and organization_id=p_organization_id and status='active') then raise exception 'active_function_agent_required'; end if;
 insert into agentic_business_sagas(organization_id,agent_id,saga_type,goal,idempotency_key,policy_ir_digest,context,compensation_plan,created_by)
 values(p_organization_id,p_agent_id,p_saga_type,p_goal,p_idempotency_key,p_policy_digest,p_context,coalesce(p_context->'compensation_plan','[]'),p_created_by)
 on conflict(organization_id,idempotency_key) do update set updated_at=now() returning * into v_saga;
 for v_step in select * from jsonb_array_elements(p_steps) loop
  insert into agentic_business_saga_steps(saga_id,step_index,operation,connector_provider,connector_scope,input,external_effect,reversible,authority_scope,state,idempotency_key,compensation_operation,evidence)
  values(v_saga.id,(v_step->>'index')::integer,v_step->>'operation',nullif(v_step->>'provider',''),coalesce(array(select jsonb_array_elements_text(v_step->'scopes')),'{}'),coalesce(v_step->'input','{}'),coalesce((v_step->>'external_effect')::boolean,false),coalesce((v_step->>'reversible')::boolean,true),v_step->>'authority_scope',case when coalesce((v_step->>'external_effect')::boolean,false) then 'approval_required' else 'ready' end,v_step->>'idempotency_key',v_step->>'compensation_operation',coalesce(v_step->'evidence','{}'))
  on conflict(idempotency_key) do nothing;
 end loop;
 update agentic_business_sagas set state=case when exists(select 1 from agentic_business_saga_steps where saga_id=v_saga.id and state='approval_required') then 'approval_required' else 'ready' end where id=v_saga.id returning * into v_saga;
 return v_saga;
end $$;
revoke all on function create_agentic_business_saga(uuid,uuid,text,text,text,text,jsonb,jsonb,uuid) from public;
grant execute on function create_agentic_business_saga(uuid,uuid,text,text,text,text,jsonb,jsonb,uuid) to service_role;

create or replace function claim_agentic_business_saga_step(p_worker text)
returns setof agentic_business_saga_steps language plpgsql security definer set search_path=public as $$
declare v_id uuid;
begin
 select s.id into v_id from agentic_business_saga_steps s join agentic_business_sagas g on g.id=s.saga_id
 where s.state='ready' and s.attempt_count<5
 and not exists(select 1 from agentic_business_saga_steps prior where prior.saga_id=s.saga_id and prior.step_index<s.step_index and prior.state not in('completed','skipped','compensated'))
 and (s.external_effect=false or (
   s.approval_id is not null and exists(select 1 from approvals a where a.id=s.approval_id and a.status='approved')
   and exists(select 1 from organizational_authority_credentials c join business_function_agents f on f.id=g.agent_id
     where c.organization_id=g.organization_id and c.status='active' and c.subject_type in('agent','role')
     and c.subject_ref in(f.agent_key,'agent:'||f.agent_key) and s.authority_scope=any(c.scopes)
     and c.valid_from<=now() and (c.valid_until is null or c.valid_until>now()))
 ))
 order by s.external_effect asc,s.created_at asc for update of s skip locked limit 1;
 if v_id is null then return; end if;
 update agentic_business_saga_steps set state='claimed',claimed_by=p_worker,claimed_at=now(),attempt_count=attempt_count+1,updated_at=now() where id=v_id;
 update agentic_business_sagas set state='executing',updated_at=now() where id=(select saga_id from agentic_business_saga_steps where id=v_id);
 return query select * from agentic_business_saga_steps where id=v_id;
end $$;
revoke all on function claim_agentic_business_saga_step(text) from public;
grant execute on function claim_agentic_business_saga_step(text) to service_role;

create or replace function record_authority_change_impacts()
returns trigger language plpgsql security definer set search_path=public as $$
declare v_event uuid;
begin
 if new.status='verified' and (tg_op='INSERT' or old.source_digest is distinct from new.source_digest or old.status is distinct from new.status) then
  insert into authority_change_events(policy_source_id,jurisdiction,domain,effective_at,source_digest,status,impact_summary,created_by)
  values(new.id,new.jurisdiction,new.domain,new.effective_from,new.source_digest,'impact_mapped','{}',new.verified_by) returning id into v_event;
  insert into authority_impact_edges(event_id,organization_id,target_type,target_id,impact,recompile_status,evidence)
  select v_event,s.organization_id,'policy_snapshot',s.id,'authority_source_changed','queued',jsonb_build_object('previous_snapshot_digest',s.snapshot_digest)
  from legal_policy_snapshots s where s.jurisdiction=new.jurisdiction and new.domain=any(s.domains)
  on conflict(event_id,target_type,target_id) do nothing;
  insert into authority_impact_edges(event_id,organization_id,target_type,target_id,impact,recompile_status,evidence)
  select v_event,c.organization_id,'contract',c.id,'pinned_policy_may_be_outdated','queued',jsonb_build_object('current_version',c.current_version)
  from legal_contracts c join legal_policy_snapshots s on s.id=c.policy_snapshot_id where s.jurisdiction=new.jurisdiction and new.domain=any(s.domains)
  on conflict(event_id,target_type,target_id) do nothing;
 end if;
 return new;
end $$;
drop trigger if exists legal_policy_source_authority_change on legal_policy_sources;
create trigger legal_policy_source_authority_change after insert or update of status,source_digest on legal_policy_sources for each row execute function record_authority_change_impacts();

comment on table organizational_authority_credentials is 'Bounded organizational authority; credentials never confer authority the issuer does not possess.';
comment on table agentic_business_saga_steps is 'Exactly-once saga steps. External effects remain approval and credential gated; compensation is explicit.';
