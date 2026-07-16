-- Regulatory proof and capacity network: disclosure-minimized passports,
-- transaction authority coordination, permissioned counterparty matching,
-- swarm escalation, causal memory, customer outcomes, runtime receipts,
-- and supervisory capacity reservations.

create table if not exists public.regulatory_privacy_passports (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  subject_ref text not null, claim_commitments jsonb not null default '[]', disclosed_proofs jsonb not null default '[]', verifier_policy jsonb not null default '{}',
  evidence_retention jsonb not null default '{}', passport_root text not null, expires_at timestamptz not null, passport_digest text not null unique,
  status text not null default 'valid' check (status in ('draft','valid','expired','revoked')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_transaction_authorizations (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  transaction_ref text not null, parties jsonb not null default '[]', jurisdictions jsonb not null default '[]', activities jsonb not null default '[]',
  authority_checks jsonb not null default '[]', agreement_checks jsonb not null default '[]', limit_checks jsonb not null default '[]',
  routing_plan jsonb not null default '[]', missing_requirements jsonb not null default '[]', decision text not null, receipt_digest text not null unique,
  expires_at timestamptz not null, status text not null default 'evaluated' check (status in ('evaluated','allowed','rerouted','held','expired','revoked')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_counterparty_orders (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  order_type text not null, capability text not null, jurisdictions jsonb not null default '[]', requested_capacity jsonb not null default '{}',
  risk_profile jsonb not null default '{}', consent_policy jsonb not null default '{}', candidates jsonb not null default '[]', recommended_match jsonb,
  economics jsonb not null default '{}', conflicts jsonb not null default '[]', order_digest text not null unique,
  status text not null default 'modeled' check (status in ('modeled','permission_required','introduced','reserved','active','cancelled')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_swarm_escalations (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  subject_ref text not null, bounded_packet jsonb not null default '{}', provider_assessments jsonb not null default '[]', consensus jsonb not null default '{}',
  dissent jsonb not null default '[]', material_gaps jsonb not null default '[]', human_review_required boolean not null default true,
  routing_manifest jsonb not null default '[]', escalation_digest text not null unique,
  status text not null default 'evaluated' check (status in ('evaluated','human_review','resolved','superseded')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_causal_memory (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  intervention_key text not null, context_signature text not null, treated_outcomes jsonb not null default '[]', comparison_outcomes jsonb not null default '[]',
  estimated_effect jsonb not null default '{}', confounders jsonb not null default '[]', transfer_conditions jsonb not null default '[]',
  confidence numeric not null default 0, memory_digest text not null unique, status text not null default 'observational' check (status in ('observational','quasi_experimental','validated','retired')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_customer_outcome_twins (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  feature_ref text not null, segments jsonb not null default '[]', scenarios jsonb not null default '[]', outcome_metrics jsonb not null default '{}',
  disparity_findings jsonb not null default '[]', harm_findings jsonb not null default '[]', mitigations jsonb not null default '[]',
  launch_recommendation text not null, twin_digest text not null unique, status text not null default 'shadow' check (status in ('shadow','review','mitigated','accepted','superseded')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_runtime_receipts (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  transaction_ref text not null, authority_ref text, agreement_ref text, model_ref text, approval_ref text, fallback_ref text,
  policy_inputs_digest text not null, decision_digest text not null, receipt_chain_prev text, receipt_digest text not null unique,
  verification_manifest jsonb not null default '{}', expires_at timestamptz not null, status text not null default 'valid' check (status in ('valid','expired','revoked','invalid')), created_at timestamptz not null default now()
);
create table if not exists public.regulatory_capacity_reservations (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  capability text not null, jurisdiction text not null, forecast jsonb not null default '{}', shortage_windows jsonb not null default '[]',
  reservation_options jsonb not null default '[]', recommended_reservation jsonb, risk_transfer_terms jsonb not null default '{}',
  approval_requirements jsonb not null default '[]', reservation_digest text not null unique,
  status text not null default 'forecast' check (status in ('forecast','permission_required','reserved','active','expired','cancelled')), created_at timestamptz not null default now()
);

create index if not exists idx_reg_passport_org on public.regulatory_privacy_passports(organization_id,status,expires_at);
create index if not exists idx_reg_tx_auth_org on public.regulatory_transaction_authorizations(organization_id,status,created_at desc);
create index if not exists idx_reg_orders_org on public.regulatory_counterparty_orders(organization_id,status,created_at desc);
create index if not exists idx_reg_swarm_escalation_org on public.regulatory_swarm_escalations(organization_id,status,created_at desc);
create index if not exists idx_reg_causal_org on public.regulatory_causal_memory(organization_id,status,created_at desc);
create index if not exists idx_reg_outcome_twin_org on public.regulatory_customer_outcome_twins(organization_id,status,created_at desc);
create index if not exists idx_reg_runtime_receipt_org on public.regulatory_runtime_receipts(organization_id,status,created_at desc);
create index if not exists idx_reg_capacity_org on public.regulatory_capacity_reservations(organization_id,status,created_at desc);

alter table public.regulatory_privacy_passports enable row level security;
alter table public.regulatory_transaction_authorizations enable row level security;
alter table public.regulatory_counterparty_orders enable row level security;
alter table public.regulatory_swarm_escalations enable row level security;
alter table public.regulatory_causal_memory enable row level security;
alter table public.regulatory_customer_outcome_twins enable row level security;
alter table public.regulatory_runtime_receipts enable row level security;
alter table public.regulatory_capacity_reservations enable row level security;

comment on table public.regulatory_privacy_passports is 'Disclosure-minimized claim commitments and selective proofs; no claim of formal zero-knowledge circuit verification.';
comment on table public.regulatory_counterparty_orders is 'Matching and economics only; introductions, reservations, agreements, payments, and regulated activity require affirmative permission.';
comment on table public.regulatory_capacity_reservations is 'Operational capacity forecasting and permissioned reservations; not a security, insurance policy, or autonomous financial derivative.';
