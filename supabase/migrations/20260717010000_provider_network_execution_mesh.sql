-- Network execution mesh. No table stores threshold key shares, private plaintext,
-- credentials, or an executable money-movement instruction.
create table if not exists provider_clearing_consensus_rounds (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 semantic_key text not null references provider_semantic_mutation_intents(semantic_key), obligation_digest text not null,
 quorum integer not null check(quorum>=3), certificate jsonb, certificate_digest text,
 state text not null default 'collecting' check(state in('collecting','certified','rejected','expired')),
 expires_at timestamptz not null, created_at timestamptz not null default now(), unique(semantic_key)
);
create table if not exists provider_clearing_consensus_votes (
 id uuid primary key default gen_random_uuid(), round_id uuid not null references provider_clearing_consensus_rounds(id) on delete cascade,
 institution_id text not null, region text not null, key_id text not null, decision text not null check(decision in('accept','reject')),
 signature text not null, vote_digest text not null, created_at timestamptz not null default now(), unique(round_id,institution_id)
);
create table if not exists provider_threshold_ceremonies (
 id uuid primary key default gen_random_uuid(), organization_id uuid references orchestrator_organizations(id) on delete cascade,
 purpose text not null, public_key_digest text not null, threshold integer not null check(threshold>=2), ceremony_digest text not null unique,
 transcript_digest text, state text not null default 'collecting' check(state in('collecting','verified','revoked','failed')), created_at timestamptz not null default now()
);
create table if not exists provider_threshold_ceremony_attestations (
 id uuid primary key default gen_random_uuid(), ceremony_id uuid not null references provider_threshold_ceremonies(id) on delete cascade,
 custodian_id text not null, region text not null, key_id text not null, measurement text not null, signature text not null,
 attestation_digest text not null, created_at timestamptz not null default now(), unique(ceremony_id,custodian_id)
);
create table if not exists provider_formal_verification_runs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 saga_id uuid references agentic_business_sagas(id) on delete cascade, module_name text not null, model_digest text not null,
 source text not null, config text not null, verifier_receipt jsonb, receipt_digest text,
 state text not null check(state in('generated','verified','failed')), created_at timestamptz not null default now(), unique(organization_id,model_digest)
);
create table if not exists provider_chaos_market_runs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 adapter_id uuid references provider_adapter_manifests(id) on delete cascade, environment text not null check(environment='sandbox'),
 experiments jsonb not null, results jsonb not null default '[]', market_digest text not null, state text not null check(state in('proposed','running','passed','failed')),
 created_at timestamptz not null default now(), unique(organization_id,market_digest)
);
create table if not exists provider_private_optimization_runs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 purpose text not null, ciphertext_digest text not null, request_digest text not null, result_ciphertext_digest text,
 verifier_receipt jsonb, receipt_digest text, scheme text, state text not null check(state in('submitted','verified','failed')),
 created_at timestamptz not null default now(), unique(organization_id,request_digest)
);
create table if not exists provider_causal_treasury_assignments (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 subject_key text not null, experiment_key text not null, arm text not null check(arm in('holdout','optimized')), bucket numeric not null,
 assignment_digest text not null, outcome jsonb, observed_at timestamptz, created_at timestamptz not null default now(), unique(organization_id,experiment_key,subject_key)
);
create table if not exists business_obligation_graphs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 graph_digest text not null, nodes jsonb not null, edges jsonb not null, duplicate_clusters jsonb not null,
 source_counts jsonb not null, created_at timestamptz not null default now(), unique(organization_id,graph_digest)
);
create table if not exists provider_authority_rule_packages (
 id uuid primary key default gen_random_uuid(), authority_source_id uuid not null references provider_authority_sources(id) on delete cascade,
 jurisdiction text not null, package_version text not null, effective_at timestamptz not null, package_digest text not null unique,
 rules jsonb not null, signer_key_id text not null, signature text not null, verification_receipt jsonb,
 state text not null check(state in('received','verified','superseded','rejected')), created_at timestamptz not null default now()
);
create table if not exists provider_compiler_synthesis_runs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 provider text not null, version text not null, evidence_artifacts jsonb not null, missing_required text[] not null,
 compiler_digest text not null, adapter_id uuid references provider_adapter_manifests(id) on delete set null,
 conformance_receipt jsonb, state text not null check(state in('evidence_incomplete','generated','conformant','rejected')),
 created_at timestamptz not null default now(), unique(organization_id,compiler_digest)
);
create table if not exists provider_liquidity_netting_rounds (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 participants jsonb not null, net_positions jsonb not null, gross_notional numeric not null, net_settlement_notional numeric not null,
 saved_notional numeric not null, round_digest text not null, approval_id uuid references approvals(id) on delete set null,
 state text not null default 'approval_required' check(state in('approval_required','approved','expired','settled')),
 created_by uuid references auth.users(id), created_at timestamptz not null default now(), unique(organization_id,round_digest)
);

create or replace function certify_provider_clearing_round(p_round_id uuid,p_certificate jsonb,p_certificate_digest text)
returns provider_clearing_consensus_rounds language plpgsql security definer set search_path=public as $$
declare r provider_clearing_consensus_rounds; votes integer; regions integer;
begin
 perform pg_advisory_xact_lock(hashtextextended(p_round_id::text,71));
 select count(*),count(distinct region) into votes,regions from provider_clearing_consensus_votes where round_id=p_round_id and decision='accept';
 select * into r from provider_clearing_consensus_rounds where id=p_round_id for update;
 if r.id is null or r.expires_at<=now() or votes<r.quorum or regions<2 then raise exception 'clearing_consensus_not_certifiable'; end if;
 update provider_clearing_consensus_rounds set state='certified',certificate=p_certificate,certificate_digest=p_certificate_digest where id=p_round_id returning * into r;
 return r;
end $$;
revoke all on function certify_provider_clearing_round(uuid,jsonb,text) from public;
grant execute on function certify_provider_clearing_round(uuid,jsonb,text) to service_role;

create index if not exists provider_clearing_round_state_idx on provider_clearing_consensus_rounds(state,expires_at);
create index if not exists obligation_graph_latest_idx on business_obligation_graphs(organization_id,created_at desc);
do $$ declare t text; begin foreach t in array array['provider_clearing_consensus_rounds','provider_clearing_consensus_votes','provider_threshold_ceremonies','provider_threshold_ceremony_attestations','provider_formal_verification_runs','provider_chaos_market_runs','provider_private_optimization_runs','provider_causal_treasury_assignments','business_obligation_graphs','provider_authority_rule_packages','provider_compiler_synthesis_runs','provider_liquidity_netting_rounds'] loop execute format('alter table %I enable row level security',t); end loop; end $$;
