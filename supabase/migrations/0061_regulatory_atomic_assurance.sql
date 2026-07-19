-- Atomic regulatory assurance: verifier-backed ZK envelopes, atomic execution,
-- purpose/consent inheritance, adversarial proof review, liability attribution,
-- regulatory unit economics, customer remedies, and capacity reliability.

create table if not exists public.regulatory_zk_verifier_registry (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  circuit_key text not null, circuit_version text not null, proof_system text not null, verifier_ref text not null, verifier_digest text not null,
  supported_predicates jsonb not null default '[]', trusted_setup_manifest jsonb not null default '{}', audit_manifest jsonb not null default '{}',
  status text not null default 'shadow' check (status in ('shadow','approved','active','suspended','retired')), created_at timestamptz not null default now(),
  unique(organization_id,circuit_key,circuit_version)
);
create table if not exists public.regulatory_zk_proof_envelopes (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  verifier_registry_id uuid not null references public.regulatory_zk_verifier_registry(id) on delete restrict, subject_ref text not null,
  predicate text not null, public_inputs jsonb not null default '{}', proof_blob_ref text not null, proof_digest text not null,
  verification_result jsonb not null default '{}', verified_at timestamptz, expires_at timestamptz not null, envelope_digest text not null unique,
  status text not null default 'pending' check (status in ('pending','valid','invalid','expired','revoked')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_atomic_transactions (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  transaction_ref text not null, steps jsonb not null default '[]', preconditions jsonb not null default '[]', compensation_plan jsonb not null default '[]',
  evidence_plan jsonb not null default '[]', authorization_result jsonb not null default '{}', execution_receipts jsonb not null default '[]',
  failed_step text, atomicity_digest text not null unique, status text not null default 'prepared' check (status in ('prepared','authorized','executing','committed','compensating','rolled_back','held')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_consent_graph_edges (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  grantor_ref text not null, grantee_ref text not null, resource_ref text not null, purposes jsonb not null default '[]', allowed_actions jsonb not null default '[]',
  inherited_from uuid references public.regulatory_consent_graph_edges(id) on delete cascade, attenuation jsonb not null default '{}',
  expires_at timestamptz not null, revoked_at timestamptz, edge_digest text not null unique,
  status text not null default 'active' check (status in ('active','expired','revoked','superseded')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_proof_challenges (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  proof_ref text not null, challenger_ref text not null, challenge_types jsonb not null default '[]', findings jsonb not null default '[]',
  severity text not null, stake jsonb not null default '{}', resolution jsonb not null default '{}', reward_cents bigint not null default 0,
  challenge_digest text not null unique, status text not null default 'open' check (status in ('open','validated','rejected','remediated','paid')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_liability_attribution (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  outcome_ref text not null, contributors jsonb not null default '[]', causal_chain jsonb not null default '[]', allocation jsonb not null default '[]',
  remediation_cost_cents bigint not null default 0, recoverable_cost_cents bigint not null default 0, uncertainty jsonb not null default '{}',
  attribution_digest text not null unique, status text not null default 'modeled' check (status in ('modeled','review','accepted','disputed','settled')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_unit_economics (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  product_ref text not null, jurisdiction text not null, authority_route text not null, volume_assumptions jsonb not null default '{}',
  revenue_model jsonb not null default '{}', regulatory_costs jsonb not null default '{}', contribution_model jsonb not null default '{}',
  break_even jsonb not null default '{}', sensitivity jsonb not null default '[]', recommendation text not null,
  economics_digest text not null unique, status text not null default 'modeled' check (status in ('modeled','selected','active','superseded')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_customer_remedies (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  incident_ref text not null, affected_cohort jsonb not null default '{}', eligibility_rules jsonb not null default '[]', calculations jsonb not null default '[]',
  total_proposed_cents bigint not null default 0, evidence_manifest jsonb not null default '[]', notification_plan jsonb not null default '[]',
  execution_controls jsonb not null default '{}', remedy_digest text not null unique,
  status text not null default 'prepared' check (status in ('prepared','review','approved','executing','completed','cancelled')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_capacity_performance (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  provider_ref text not null, capability text not null, jurisdiction text not null, reserved_minutes int not null default 0, delivered_minutes int not null default 0,
  response_minutes numeric not null default 0, quality_score numeric not null default 0, examination_outcomes jsonb not null default '[]',
  reliability_score numeric not null default 0, pricing_adjustment jsonb not null default '{}', performance_digest text not null unique,
  status text not null default 'current' check (status in ('current','watch','suspended','retired')), measured_at timestamptz not null default now(), created_at timestamptz not null default now()
);

create index if not exists idx_reg_zk_registry_org on public.regulatory_zk_verifier_registry(organization_id,status,created_at desc);
create index if not exists idx_reg_zk_envelope_org on public.regulatory_zk_proof_envelopes(organization_id,status,expires_at);
create index if not exists idx_reg_atomic_tx_org on public.regulatory_atomic_transactions(organization_id,status,created_at desc);
create index if not exists idx_reg_consent_graph_org on public.regulatory_consent_graph_edges(organization_id,status,expires_at);
create index if not exists idx_reg_proof_challenge_org on public.regulatory_proof_challenges(organization_id,status,created_at desc);
create index if not exists idx_reg_liability_org on public.regulatory_liability_attribution(organization_id,status,created_at desc);
create index if not exists idx_reg_unit_economics_org on public.regulatory_unit_economics(organization_id,status,created_at desc);
create index if not exists idx_reg_remedy_org on public.regulatory_customer_remedies(organization_id,status,created_at desc);
create index if not exists idx_reg_capacity_performance_org on public.regulatory_capacity_performance(organization_id,status,reliability_score desc);

alter table public.regulatory_zk_verifier_registry enable row level security;
alter table public.regulatory_zk_proof_envelopes enable row level security;
alter table public.regulatory_atomic_transactions enable row level security;
alter table public.regulatory_consent_graph_edges enable row level security;
alter table public.regulatory_proof_challenges enable row level security;
alter table public.regulatory_liability_attribution enable row level security;
alter table public.regulatory_unit_economics enable row level security;
alter table public.regulatory_customer_remedies enable row level security;
alter table public.regulatory_capacity_performance enable row level security;

comment on table public.regulatory_zk_proof_envelopes is 'Proofs remain pending unless an active approved verifier produces a valid cryptographic verification result.';
comment on table public.regulatory_customer_remedies is 'Prepared remedy proposals; payments, admissions, and customer communications require separately recorded approval.';
