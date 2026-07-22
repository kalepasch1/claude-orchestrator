-- Contract-to-operations compiler and governed autonomous business fabric.
create table if not exists autonomous_operating_workflows (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 contract_id uuid not null references legal_contracts(id) on delete cascade, source_version integer not null,
 compiler_digest text not null, state text not null default 'draft' check(state in('draft','active','paused','completed','blocked')),
 autonomy_mode text not null default 'prepare' check(autonomy_mode in('observe','prepare','execute_reversible','exception_only')),
 controls jsonb not null default '{}', created_by uuid not null references auth.users(id), created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 unique(organization_id,contract_id,source_version,compiler_digest)
);
create table if not exists autonomous_operating_actions (
 id uuid primary key default gen_random_uuid(), workflow_id uuid not null references autonomous_operating_workflows(id) on delete cascade,
 organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 domain text not null check(domain in('workforce','finance','tax','security','procurement','crm','renewal','payment','legal')),
 action_type text not null, title text not null, payload jsonb not null default '{}', dependency_keys text[] not null default '{}',
 risk text not null default 'medium' check(risk in('low','medium','high','critical')), reversible boolean not null default true,
 external_effect boolean not null default false, status text not null default 'planned' check(status in('planned','ready','approval_required','approved','executing','completed','blocked','skipped')),
 due_at timestamptz, owner_role text, idempotency_key text not null, evidence jsonb not null default '{}', outcome jsonb not null default '{}',
 attempt_count integer not null default 0, claimed_at timestamptz, completed_at timestamptz, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 unique(organization_id,idempotency_key)
);
create table if not exists matter_information_barriers (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 contract_id uuid not null references legal_contracts(id) on delete cascade, classification text not null default 'confidential',
 allowed_roles text[] not null default '{}', model_policy jsonb not null default '{"training":false,"retention":"matter_scoped","cross_tenant":false}',
 selective_disclosure jsonb not null default '{}', created_by uuid not null references auth.users(id), created_at timestamptz not null default now(), unique(organization_id,contract_id)
);
create table if not exists authority_change_events (
 id uuid primary key default gen_random_uuid(), policy_source_id uuid not null references legal_policy_sources(id) on delete cascade,
 jurisdiction text not null, domain text not null, effective_at date not null, source_digest text not null,
 status text not null default 'detected' check(status in('detected','impact_mapped','recompiled','review_required','closed')),
 impact_summary jsonb not null default '{}', created_by uuid references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists authority_impact_edges (
 id uuid primary key default gen_random_uuid(), event_id uuid not null references authority_change_events(id) on delete cascade,
 organization_id uuid references orchestrator_organizations(id) on delete cascade, target_type text not null check(target_type in('policy_snapshot','contract','workflow')),
 target_id uuid not null, impact text not null, recompile_status text not null default 'pending' check(recompile_status in('pending','not_required','queued','completed','blocked')),
 evidence jsonb not null default '{}', created_at timestamptz not null default now(), unique(event_id,target_type,target_id)
);
create table if not exists clause_genome_patterns (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 clause_type text not null, structural_features jsonb not null default '{}', approved_positions jsonb not null default '{}', fallback_ladder jsonb not null default '[]',
 aggregated_outcomes jsonb not null default '{}', sample_size integer not null default 0, privilege_policy jsonb not null default '{"raw_text_export":false,"cross_tenant":false}',
 pattern_digest text not null, created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique(organization_id,clause_type,pattern_digest)
);
create table if not exists negotiation_twin_runs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 contract_id uuid not null references legal_contracts(id) on delete cascade, version integer not null, scenarios jsonb not null default '[]',
 affected_operations jsonb not null default '[]', recommendation jsonb not null default '{}', lower_confidence numeric not null default 0,
 run_digest text not null, created_by uuid not null references auth.users(id), created_at timestamptz not null default now(), unique(contract_id,version,run_digest)
);
create table if not exists contract_causal_outcomes (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 contract_id uuid references legal_contracts(id) on delete cascade, clause_type text not null, metric text not null,
 treatment jsonb not null default '{}', control jsonb not null default '{}', estimated_effect numeric, confidence numeric not null default 0,
 sample_size integer not null default 0, privacy jsonb not null default '{"minimum_cohort":5,"raw_text":false}', evidence_digest text not null,
 created_by uuid references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists execution_finality_receipts (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 contract_id uuid not null references legal_contracts(id) on delete cascade, version integer not null,
 receipt_type text not null check(receipt_type in('identity','authority','signature','delivery','timestamp','archive','payment','filing')),
 provider text not null, external_ref text, content_digest text not null, receipt_digest text not null,
 status text not null check(status in('prepared','verified','rejected','revoked')), evidence jsonb not null default '{}', verified_at timestamptz,
 created_by uuid references auth.users(id), created_at timestamptz not null default now(), unique(organization_id,receipt_digest)
);
create table if not exists legal_benchmark_snapshots (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 contract_id uuid references legal_contracts(id) on delete cascade, version integer, corpus_name text not null, license_evidence jsonb not null default '{}',
 metrics jsonb not null default '{}', percentile_summary jsonb not null default '{}', contains_verbatim_language boolean not null default false,
 snapshot_digest text not null, created_by uuid references auth.users(id), created_at timestamptz not null default now(), unique(organization_id,snapshot_digest)
);
create table if not exists legal_conflict_checks (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 contract_id uuid not null references legal_contracts(id) on delete cascade, normalized_entities text[] not null default '{}',
 authority_findings jsonb not null default '[]', obligation_collisions jsonb not null default '[]', status text not null check(status in('clear','attention','blocked')),
 check_digest text not null, created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create index if not exists autonomous_actions_ready_idx on autonomous_operating_actions(organization_id,status,external_effect,created_at);
create index if not exists authority_edges_target_idx on authority_impact_edges(target_type,target_id,recompile_status);
create index if not exists finality_contract_idx on execution_finality_receipts(contract_id,version,status);
alter table autonomous_operating_workflows enable row level security; alter table autonomous_operating_actions enable row level security;
alter table matter_information_barriers enable row level security; alter table authority_change_events enable row level security;
alter table authority_impact_edges enable row level security; alter table clause_genome_patterns enable row level security;
alter table negotiation_twin_runs enable row level security; alter table contract_causal_outcomes enable row level security;
alter table execution_finality_receipts enable row level security; alter table legal_benchmark_snapshots enable row level security;
alter table legal_conflict_checks enable row level security;

create or replace function compile_contract_operations(p_organization_id uuid,p_contract_id uuid,p_source_version integer,p_compiler_digest text,p_autonomy_mode text,p_controls jsonb,p_actions jsonb,p_created_by uuid)
returns autonomous_operating_workflows language plpgsql security definer set search_path=public as $$
declare v_workflow autonomous_operating_workflows; v_action jsonb;
begin
 if not exists(select 1 from legal_contracts where id=p_contract_id and organization_id=p_organization_id and current_version=p_source_version) then
  raise exception 'organization_contract_version_mismatch';
 end if;
 insert into autonomous_operating_workflows(organization_id,contract_id,source_version,compiler_digest,autonomy_mode,controls,created_by)
 values(p_organization_id,p_contract_id,p_source_version,p_compiler_digest,p_autonomy_mode,p_controls,p_created_by)
 on conflict(organization_id,contract_id,source_version,compiler_digest) do update set controls=excluded.controls,updated_at=now()
 returning * into v_workflow;
 for v_action in select * from jsonb_array_elements(p_actions) loop
  insert into autonomous_operating_actions(workflow_id,organization_id,domain,action_type,title,payload,dependency_keys,risk,reversible,external_effect,status,due_at,owner_role,idempotency_key,evidence)
  values(v_workflow.id,p_organization_id,v_action->>'domain',v_action->>'action_type',v_action->>'title',coalesce(v_action->'payload','{}'),coalesce(array(select jsonb_array_elements_text(v_action->'dependency_keys')),'{}'),v_action->>'risk',coalesce((v_action->>'reversible')::boolean,true),coalesce((v_action->>'external_effect')::boolean,false),v_action->>'status',nullif(v_action->>'due_at','')::timestamptz,v_action->>'owner_role',v_action->>'idempotency_key',coalesce(v_action->'evidence','{}'))
  on conflict(organization_id,idempotency_key) do nothing;
 end loop;
 if p_autonomy_mode in ('execute_reversible','exception_only') then
  update autonomous_operating_actions set status='completed',completed_at=now(),updated_at=now(),
   evidence=evidence||jsonb_build_object('executor','database_control_plane','effect','internal_operating_artifact_materialized','completed_at',now()),
   outcome=jsonb_build_object('status','completed','external_effect',false,'exception_only',p_autonomy_mode='exception_only')
  where workflow_id=v_workflow.id and status='ready' and external_effect=false and reversible=true;
  update autonomous_operating_workflows set state='active',updated_at=now() where id=v_workflow.id returning * into v_workflow;
 end if;
 return v_workflow;
end $$;
revoke all on function compile_contract_operations(uuid,uuid,integer,text,text,jsonb,jsonb,uuid) from public;
grant execute on function compile_contract_operations(uuid,uuid,integer,text,text,jsonb,jsonb,uuid) to service_role;

comment on table autonomous_operating_actions is 'Proof-carrying action graph. External, irreversible, regulated, employment, payment, filing, and signature effects remain authority gated.';
comment on table clause_genome_patterns is 'Tenant-scoped structural learning. Raw privileged clause text may not be exported or pooled.';
