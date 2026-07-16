-- Provider intelligence mesh: learned mappings, causal holdouts, signed adapters,
-- preflight twins, leased credentials, normalized finality, and outcome routing.
alter table business_provider_executions add column if not exists experiment_assignment_id uuid;
alter table business_provider_executions add column if not exists digital_twin_run_id uuid;
alter table business_provider_executions add column if not exists route_score numeric;
alter table business_provider_executions add column if not exists provider_started_at timestamptz;
alter table business_provider_executions add column if not exists finalized_at timestamptz;

create table if not exists provider_field_mappings (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 provider text not null, operation text not null, source_path text not null, target_path text not null,
 support integer not null default 1, successes integer not null default 1, confidence numeric not null default 1 check(confidence between 0 and 1),
 value_type text not null, last_verified_at timestamptz not null default now(), created_at timestamptz not null default now(),
 unique(organization_id,provider,operation,source_path,target_path)
);
create table if not exists provider_experiment_assignments (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 saga_id uuid not null references agentic_business_sagas(id) on delete cascade, experiment_key text not null,
 variant text not null check(variant in('control','treatment')), assignment_unit text not null,
 assignment_digest text not null, assigned_at timestamptz not null default now(), unique(saga_id,experiment_key)
);
create table if not exists provider_outcome_measurements (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 saga_id uuid not null references agentic_business_sagas(id) on delete cascade, assignment_id uuid references provider_experiment_assignments(id) on delete set null,
 provider text not null, operation text not null, variant text not null check(variant in('control','treatment')),
 automated_hours numeric not null default 0, baseline_hours numeric not null default 0, hours_saved numeric not null default 0,
 error_count integer not null default 0, settlement_latency_ms bigint, financial_value numeric not null default 0,
 currency text not null default 'USD', non_regressed boolean not null default true, evidence jsonb not null default '{}', measured_at timestamptz not null default now(),
 unique(saga_id,operation)
);
create table if not exists provider_adapter_manifests (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 provider text not null, version text not null, spec_digest text not null, manifest jsonb not null, signature text not null,
 signing_key_id text not null, status text not null default 'draft' check(status in('draft','conformance_pending','active','rejected','retired')),
 created_by uuid references auth.users(id), created_at timestamptz not null default now(), activated_at timestamptz,
 unique(organization_id,provider,version,spec_digest)
);
create table if not exists provider_adapter_conformance_runs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 adapter_id uuid not null references provider_adapter_manifests(id) on delete cascade, environment text not null default 'sandbox' check(environment='sandbox'),
 tests jsonb not null, passed integer not null default 0, failed integer not null default 0,
 status text not null check(status in('passed','failed')), evidence_digest text not null, created_at timestamptz not null default now()
);
create table if not exists provider_digital_twin_runs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 saga_id uuid not null references agentic_business_sagas(id) on delete cascade, step_id uuid not null references agentic_business_saga_steps(id) on delete cascade,
 provider text not null, operation text not null, request_digest text not null, scenario_digest text not null,
 verdict text not null check(verdict in('pass','block','review')), checks jsonb not null, predicted jsonb not null default '{}',
 created_at timestamptz not null default now(), unique(step_id,request_digest)
);
create table if not exists provider_credential_grants (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 connector_account_id uuid not null references connector_accounts(id) on delete cascade, credential_ref text not null,
 lease_id text not null, scopes text[] not null default '{}', expires_at timestamptz not null, broker_key_id text not null,
 lease_digest text not null, status text not null default 'active' check(status in('active','expired','revoked')), created_at timestamptz not null default now(),
 unique(connector_account_id,lease_id)
);
create table if not exists business_provider_finality_events (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 connector_account_id uuid not null references connector_accounts(id) on delete cascade,
 execution_id uuid references business_provider_executions(id) on delete set null, provider text not null,
 contract_version text not null default 'provider-finality/v1',
 provider_event_id text not null, external_ref text, canonical_status text not null check(canonical_status in('accepted','pending','succeeded','failed','cancelled','unknown')),
 event_type text not null, occurred_at timestamptz, payload_digest text not null, source text not null check(source in('webhook','poll','read_after_write')),
 verified boolean not null default false, normalized jsonb not null default '{}', received_at timestamptz not null default now(),
 unique(connector_account_id,provider_event_id)
);
create table if not exists provider_route_profiles (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
 connector_account_id uuid not null references connector_accounts(id) on delete cascade, provider text not null, operation text not null,
 jurisdiction text not null default '*', expected_fee_bps numeric not null default 0, p50_settlement_ms bigint not null default 0,
 failure_rate numeric not null default 0 check(failure_rate between 0 and 1), risk_score numeric not null default 0 check(risk_score between 0 and 1),
 sample_size integer not null default 0, updated_at timestamptz not null default now(), unique(connector_account_id,operation,jurisdiction)
);

create index if not exists provider_mapping_lookup_idx on provider_field_mappings(organization_id,provider,operation,confidence desc);
create index if not exists provider_outcome_variant_idx on provider_outcome_measurements(organization_id,operation,variant,measured_at desc);
create index if not exists provider_finality_execution_idx on business_provider_finality_events(execution_id,received_at desc);
create index if not exists provider_route_lookup_idx on provider_route_profiles(organization_id,operation,jurisdiction);
do $$ declare t text; begin foreach t in array array['provider_field_mappings','provider_experiment_assignments','provider_outcome_measurements','provider_adapter_manifests','provider_adapter_conformance_runs','provider_digital_twin_runs','provider_credential_grants','business_provider_finality_events','provider_route_profiles'] loop execute format('alter table %I enable row level security',t); end loop; end $$;
comment on table provider_experiment_assignments is 'Stable randomized holdout of provider-intelligence treatment versus the existing safe execution baseline; business work is never withheld.';
comment on table provider_credential_grants is 'Metadata-only record of a short-lived credential lease. Credential material is never persisted.';
comment on table business_provider_finality_events is 'One normalized, deduplicated finality contract across webhook, polling, and read-after-write sources.';
