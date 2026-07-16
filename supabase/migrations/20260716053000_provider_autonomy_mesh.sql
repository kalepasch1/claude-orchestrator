-- Provider autonomy mesh: privacy-preserving federation, counterfactual routes,
-- synthetic conformance, workload identity, sequential evidence, settlement
-- dependencies, regulatory twin rules, and proof-carrying adapter capabilities.
create table if not exists provider_federated_mapping_contributions (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 provider text not null, operation text not null, schema_fingerprint text not null, source_leaf_hash text not null, target_path text not null,
 value_type text not null, support integer not null default 1, confidence numeric not null check(confidence between 0 and 1),
 privacy_epoch date not null default current_date, contribution_digest text not null, created_at timestamptz not null default now(),
 unique(organization_id,provider,operation,schema_fingerprint,source_leaf_hash,target_path,privacy_epoch)
);
create table if not exists provider_counterfactual_routes (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 saga_id uuid not null references agentic_business_sagas(id) on delete cascade, step_id uuid not null references agentic_business_saga_steps(id) on delete cascade,
 operation text not null, jurisdiction text not null default '*', candidates jsonb not null, selected_connector_account_id uuid references connector_accounts(id) on delete set null,
 selection_digest text not null, mutation_count integer not null default 0 check(mutation_count=0), created_at timestamptz not null default now(), unique(step_id,selection_digest)
);
create table if not exists provider_synthetic_sandbox_runs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 adapter_id uuid not null references provider_adapter_manifests(id) on delete cascade, case_count integer not null, passed integer not null, failed integer not null,
 coverage jsonb not null default '{}', evidence_digest text not null, status text not null check(status in('passed','failed')), created_at timestamptz not null default now()
);
create table if not exists provider_workload_attestations (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 connector_account_id uuid not null references connector_accounts(id) on delete cascade, lease_id text not null, issuer text not null, subject_hash text not null,
 audience text not null, token_id_hash text, expires_at timestamptz not null, broker_key_id text not null, verified boolean not null default false,
 created_at timestamptz not null default now(), unique(connector_account_id,lease_id)
);
create table if not exists provider_sequential_analyses (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 experiment_key text not null, analysis_version text not null default 'provider-sequential/v1', sample_size integer not null,
 information_fraction numeric not null check(information_fraction between 0 and 1), adjusted_effects jsonb not null, alpha_spent numeric not null,
 decision text not null check(decision in('continue','promote','stop_harm')), evidence_digest text not null, created_at timestamptz not null default now()
);
create table if not exists provider_settlement_dependencies (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 upstream_provider text not null, downstream_provider text not null, operation text not null, jurisdiction text not null default '*',
 observations integer not null default 0, cascade_failures integer not null default 0, conditional_failure_rate numeric not null default 0 check(conditional_failure_rate between 0 and 1),
 alternate_connector_account_id uuid references connector_accounts(id) on delete set null, updated_at timestamptz not null default now(),
 unique(organization_id,upstream_provider,downstream_provider,operation,jurisdiction)
);
create table if not exists provider_regulatory_twin_rules (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 jurisdiction text not null, provider text not null default '*', operation text not null default '*', rule_key text not null,
 effective_from date not null, effective_until date, source_uri text not null, source_digest text not null,
 invariant jsonb not null, severity text not null check(severity in('block','review')), professional_reviewed boolean not null default false,
 status text not null default 'draft' check(status in('draft','active','retired')), created_by uuid references auth.users(id), created_at timestamptz not null default now(),
 check(status<>'active' or professional_reviewed=true),
 unique(organization_id,jurisdiction,provider,operation,rule_key,effective_from)
);
create table if not exists provider_adapter_capability_proofs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 adapter_id uuid not null references provider_adapter_manifests(id) on delete cascade, proof_version text not null default 'adapter-capability/v1',
 manifest_digest text not null,
 declared_origins text[] not null, declared_methods text[] not null, declared_operations text[] not null, declared_data_paths text[] not null default '{}',
 network_default_deny boolean not null default true, filesystem_default_deny boolean not null default true, subprocess_default_deny boolean not null default true,
 proof_digest text not null, signature text not null, signing_key_id text not null, verified boolean not null default false, created_at timestamptz not null default now(),
 unique(adapter_id,proof_digest)
);

create index if not exists provider_federated_mapping_idx on provider_federated_mapping_contributions(provider,operation,schema_fingerprint,privacy_epoch);
create index if not exists provider_counterfactual_step_idx on provider_counterfactual_routes(step_id,created_at desc);
create index if not exists provider_regulatory_twin_lookup_idx on provider_regulatory_twin_rules(organization_id,jurisdiction,provider,operation,effective_from);
create index if not exists provider_settlement_graph_idx on provider_settlement_dependencies(organization_id,operation,jurisdiction,conditional_failure_rate desc);
do $$ declare t text; begin foreach t in array array['provider_federated_mapping_contributions','provider_counterfactual_routes','provider_synthetic_sandbox_runs','provider_workload_attestations','provider_sequential_analyses','provider_settlement_dependencies','provider_regulatory_twin_rules','provider_adapter_capability_proofs'] loop execute format('alter table %I enable row level security',t); end loop; end $$;
comment on table provider_federated_mapping_contributions is 'Schema-only, organization-isolated contributions. No field values or reversible source paths are stored.';
comment on table provider_counterfactual_routes is 'Non-mutating route comparison; database constraint guarantees zero provider mutations.';
comment on table provider_adapter_capability_proofs is 'Signed default-deny capability declaration required in addition to sandbox conformance before adapter activation.';
