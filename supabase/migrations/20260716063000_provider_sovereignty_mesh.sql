-- Provider sovereignty mesh: sealed federation, sandbox proof, atomic route
-- claims, safe contextual bandits, lifecycle fuzzing, TEE evidence, signed
-- authority snapshots, global mutation clearing, and liquidity forecasts.
create table if not exists provider_secure_mapping_envelopes (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 provider text not null, operation text not null, privacy_epoch date not null default current_date,
 aggregator_key_id text not null, envelope_ciphertext text not null, envelope_digest text not null,
 state text not null default 'sealed' check(state in('sealed','submitted','aggregated','expired')), created_at timestamptz not null default now(),
 unique(organization_id,envelope_digest)
);
create table if not exists provider_secure_mapping_aggregates (
 id uuid primary key default gen_random_uuid(), provider text not null, operation text not null, privacy_epoch date not null,
 schema_fingerprint text not null, source_leaf_hash text not null, target_path text not null, value_type text not null,
 organization_count integer not null check(organization_count>=5), support integer not null check(support>=5), confidence numeric not null check(confidence between .9 and 1),
 aggregate_digest text not null, attestation text not null, aggregator_key_id text not null, verified_at timestamptz not null default now(),
 unique(provider,operation,privacy_epoch,schema_fingerprint,source_leaf_hash,target_path)
);
create table if not exists provider_wasm_modules (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 adapter_id uuid references provider_adapter_manifests(id) on delete cascade, module_digest text not null, sandbox_module_ref text not null,
 capability_proof_digest text not null, imports jsonb not null default '[]', exports jsonb not null default '[]', byte_size integer not null,
 sandbox_attestation jsonb not null default '{}', status text not null default 'pending' check(status in('pending','active','rejected','retired')),
 created_at timestamptz not null default now(), unique(organization_id,module_digest)
);
create table if not exists provider_atomic_route_claims (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 saga_id uuid not null references agentic_business_sagas(id) on delete cascade, step_id uuid not null references agentic_business_saga_steps(id) on delete cascade,
 selection_digest text not null, connector_account_id uuid not null references connector_accounts(id) on delete restrict,
 state text not null default 'claimed' check(state in('claimed','committed','released','failed')), claim_owner text not null,
 claimed_at timestamptz not null default now(), committed_at timestamptz, unique(step_id)
);
create table if not exists provider_bandit_decisions (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 saga_id uuid not null references agentic_business_sagas(id) on delete cascade, step_id uuid not null references agentic_business_saga_steps(id) on delete cascade,
 policy_version text not null default 'safe-linucb/v1', context_digest text not null, candidates jsonb not null,
 selected_connector_account_id uuid references connector_accounts(id) on delete set null, propensity numeric not null check(propensity>0 and propensity<=1),
 exploration boolean not null default false, safety_constraints jsonb not null default '{}', created_at timestamptz not null default now(), unique(step_id,policy_version)
);
create table if not exists provider_lifecycle_fuzz_runs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 adapter_id uuid references provider_adapter_manifests(id) on delete cascade, provider text not null, operation text not null,
 seed text not null, scenarios integer not null, transitions integer not null, invariant_violations integer not null,
 coverage jsonb not null, evidence_digest text not null, status text not null check(status in('passed','failed')), created_at timestamptz not null default now()
);
create table if not exists provider_tee_attestations (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 connector_account_id uuid not null references connector_accounts(id) on delete cascade, lease_id text not null,
 measurement text not null, platform text not null, nonce text not null, attestation_digest text not null,
 verifier_key_id text not null, issued_at timestamptz not null, expires_at timestamptz not null, verified boolean not null default false,
 created_at timestamptz not null default now(), unique(connector_account_id,lease_id)
);
create table if not exists provider_authority_sources (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 jurisdiction text not null, source_uri text not null, verification_key text not null, status text not null default 'active' check(status in('active','paused','retired')),
 created_by uuid references auth.users(id), created_at timestamptz not null default now(), unique(organization_id,jurisdiction,source_uri)
);
create table if not exists provider_authority_snapshots (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 source_id uuid not null references provider_authority_sources(id) on delete cascade, effective_at timestamptz not null,
 content_digest text not null, source_signature text not null, source_key_id text not null, rule_manifest jsonb not null,
 previous_snapshot_id uuid references provider_authority_snapshots(id) on delete set null, verified boolean not null default false, created_at timestamptz not null default now(),
 unique(source_id,content_digest)
);
create table if not exists provider_authority_rule_proposals (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 snapshot_id uuid not null references provider_authority_snapshots(id) on delete cascade, rule_key text not null,
 change_type text not null check(change_type in('added','changed','retired')), proposed_rule jsonb not null,
 state text not null default 'professional_review' check(state in('professional_review','accepted','rejected','superseded')),
 proposal_digest text not null, created_at timestamptz not null default now(), unique(snapshot_id,rule_key)
);
create table if not exists provider_global_mutation_clearance (
 id uuid primary key default gen_random_uuid(), global_key text not null unique, provider text not null, operation text not null,
 organization_id uuid not null references orchestrator_organizations(id) on delete cascade, execution_id uuid references business_provider_executions(id) on delete set null,
 owner_token text not null, state text not null default 'claimed' check(state in('claimed','committed','failed','expired')),
 external_ref text, receipt_digest text, lease_expires_at timestamptz not null, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists provider_liquidity_forecasts (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 currency text not null, jurisdiction text not null default '*', horizon_at timestamptz not null,
 expected_outflow numeric not null default 0, stressed_outflow numeric not null default 0, available_liquidity numeric,
 required_buffer numeric not null default 0, shortfall numeric not null default 0, confidence numeric not null check(confidence between 0 and 1),
 assumptions jsonb not null default '{}', forecast_digest text not null, created_at timestamptz not null default now(), unique(organization_id,currency,jurisdiction,horizon_at)
);

create or replace function claim_provider_route(p_organization_id uuid,p_saga_id uuid,p_step_id uuid,p_selection_digest text,p_connector_account_id uuid,p_claim_owner text)
returns provider_atomic_route_claims language plpgsql security definer set search_path=public as $$
declare r provider_atomic_route_claims;
begin
 perform pg_advisory_xact_lock(hashtextextended(p_step_id::text,41));
 select * into r from provider_atomic_route_claims where step_id=p_step_id;
 if r.id is not null then
  if r.selection_digest<>p_selection_digest or r.connector_account_id<>p_connector_account_id then raise exception 'route_already_claimed'; end if;
  return r;
 end if;
 insert into provider_atomic_route_claims(organization_id,saga_id,step_id,selection_digest,connector_account_id,claim_owner)
 values(p_organization_id,p_saga_id,p_step_id,p_selection_digest,p_connector_account_id,p_claim_owner) returning * into r;
 return r;
end $$;

create or replace function claim_global_provider_mutation(p_global_key text,p_provider text,p_operation text,p_organization_id uuid,p_execution_id uuid,p_owner_token text,p_lease_seconds integer default 120)
returns provider_global_mutation_clearance language plpgsql security definer set search_path=public as $$
declare r provider_global_mutation_clearance;
begin
 perform pg_advisory_xact_lock(hashtextextended(p_global_key,43));
 select * into r from provider_global_mutation_clearance where global_key=p_global_key for update;
 if r.id is not null and r.state='committed' then return r; end if;
 if r.id is not null and r.state='claimed' and r.lease_expires_at>now() and r.owner_token<>p_owner_token then raise exception 'global_mutation_in_progress'; end if;
 insert into provider_global_mutation_clearance(global_key,provider,operation,organization_id,execution_id,owner_token,state,lease_expires_at)
 values(p_global_key,p_provider,p_operation,p_organization_id,p_execution_id,p_owner_token,'claimed',now()+make_interval(secs=>least(greatest(p_lease_seconds,30),900)))
 on conflict(global_key) do update set execution_id=excluded.execution_id,owner_token=excluded.owner_token,state='claimed',lease_expires_at=excluded.lease_expires_at,updated_at=now()
 returning * into r; return r;
end $$;

create or replace function commit_global_provider_mutation(p_global_key text,p_owner_token text,p_external_ref text,p_receipt_digest text)
returns provider_global_mutation_clearance language plpgsql security definer set search_path=public as $$
declare r provider_global_mutation_clearance;
begin
 update provider_global_mutation_clearance set state='committed',external_ref=p_external_ref,receipt_digest=p_receipt_digest,updated_at=now()
 where global_key=p_global_key and owner_token=p_owner_token and state='claimed' returning * into r;
 if r.id is null then raise exception 'global_mutation_claim_missing'; end if; return r;
end $$;

revoke all on function claim_provider_route(uuid,uuid,uuid,text,uuid,text) from public;
revoke all on function claim_global_provider_mutation(text,text,text,uuid,uuid,text,integer) from public;
revoke all on function commit_global_provider_mutation(text,text,text,text) from public;
grant execute on function claim_provider_route(uuid,uuid,uuid,text,uuid,text) to service_role;
grant execute on function claim_global_provider_mutation(text,text,text,uuid,uuid,text,integer) to service_role;
grant execute on function commit_global_provider_mutation(text,text,text,text) to service_role;

create index if not exists provider_secure_aggregate_lookup_idx on provider_secure_mapping_aggregates(provider,operation,privacy_epoch desc);
create index if not exists provider_global_clearance_state_idx on provider_global_mutation_clearance(state,lease_expires_at);
create index if not exists provider_liquidity_latest_idx on provider_liquidity_forecasts(organization_id,currency,horizon_at desc);
do $$ declare t text; begin foreach t in array array['provider_secure_mapping_envelopes','provider_secure_mapping_aggregates','provider_wasm_modules','provider_atomic_route_claims','provider_bandit_decisions','provider_lifecycle_fuzz_runs','provider_tee_attestations','provider_authority_sources','provider_authority_snapshots','provider_authority_rule_proposals','provider_global_mutation_clearance','provider_liquidity_forecasts'] loop execute format('alter table %I enable row level security',t); end loop; end $$;
comment on table provider_secure_mapping_envelopes is 'Control-plane opaque encrypted mapping contributions; only an independent aggregate verifier can decrypt.';
comment on table provider_global_mutation_clearance is 'Cross-runner, cross-organization clearing ledger for globally unique provider mutations.';
