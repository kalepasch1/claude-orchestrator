-- Outcome-first Hivemind control plane. The service stores bounded receipts and
-- aggregate decisions; private payloads, source code, prompts, and raw evidence
-- remain outside the network plane.

alter table public.hivemind_rebate_ledger
  add column if not exists available_at timestamptz,
  add column if not exists expires_at timestamptz,
  add column if not exists settled_at timestamptz,
  add column if not exists clearing_run_id uuid;

alter table public.hivemind_rebate_ledger alter column expires_at set default (now() + interval '24 months');

alter table public.hivemind_rebate_ledger drop constraint if exists hivemind_rebate_ledger_event_type_check;
alter table public.hivemind_rebate_ledger add constraint hivemind_rebate_ledger_event_type_check
  check(event_type in('verified_reuse','quality_bonus','negative_evidence_reward','attribution_credit','reserve_hold','expiration','clawback','reversal','settlement'));

alter table public.hivemind_executable_licenses
  add column if not exists proof_status text not null default 'pending' check(proof_status in('pending','verified','failed','stale')),
  add column if not exists last_verified_at timestamptz,
  add column if not exists suspended_reason text;

create table if not exists public.hivemind_license_execution_proofs (
  id uuid primary key default gen_random_uuid(),
  license_id uuid not null references public.hivemind_executable_licenses(id) on delete cascade,
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  execution_ref text not null,
  claims jsonb not null,
  policy_evaluation jsonb not null,
  input_commitment text not null,
  output_commitment text not null,
  previous_proof_digest text,
  proof_digest text not null unique,
  signature text not null,
  verdict text not null check(verdict in('verified','denied','breach')),
  created_at timestamptz not null default now(),
  unique(license_id,execution_ref)
);

create table if not exists public.hivemind_opportunity_derivations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  parent_opportunity_id uuid references public.hivemind_opportunities(id) on delete cascade,
  parent_bundle_id uuid references public.hivemind_execution_bundles(id) on delete cascade,
  child_opportunity_id uuid not null references public.hivemind_opportunities(id) on delete cascade,
  generation int not null default 1 check(generation between 1 and 3),
  causal_basis jsonb not null,
  guardrails jsonb not null,
  derivation_digest text not null unique,
  created_at timestamptz not null default now(),
  unique(parent_bundle_id)
);

create table if not exists public.hivemind_credit_accounts (
  organization_id uuid primary key references public.orchestrator_organizations(id) on delete cascade,
  accrued_cents bigint not null default 0,
  available_cents bigint not null default 0,
  reserved_cents bigint not null default 0,
  pending_settlement_cents bigint not null default 0,
  lifetime_earned_cents bigint not null default 0,
  lifetime_used_cents bigint not null default 0,
  next_expiry_at timestamptz,
  risk_tier text not null default 'standard' check(risk_tier in('low','standard','elevated','restricted')),
  snapshot_digest text not null,
  updated_at timestamptz not null default now()
);

create table if not exists public.hivemind_credit_clearing_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  period_start timestamptz not null,
  period_end timestamptz not null,
  gross_credit_cents bigint not null default 0,
  reserve_cents bigint not null default 0,
  expired_cents bigint not null default 0,
  clawback_cents bigint not null default 0,
  net_available_cents bigint not null default 0,
  accounting_export jsonb not null,
  clearing_digest text not null unique,
  status text not null default 'cleared' check(status in('cleared','review','settled','reversed')),
  created_at timestamptz not null default now(),
  unique(organization_id,period_start,period_end)
);

create table if not exists public.hivemind_governance_simulations (
  id uuid primary key default gen_random_uuid(),
  proposal_id uuid not null references public.hivemind_governance_proposals(id) on delete cascade,
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  archetype_results jsonb not null,
  rights_impact jsonb not null,
  capture_risk jsonb not null,
  minority_safeguards jsonb not null,
  recommendation text not null check(recommendation in('proceed','revise','reject')),
  simulation_digest text not null unique,
  created_at timestamptz not null default now(),
  unique(proposal_id)
);

create table if not exists public.hivemind_governance_conflicts (
  id uuid primary key default gen_random_uuid(),
  proposal_id uuid not null references public.hivemind_governance_proposals(id) on delete cascade,
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  relationship_class text not null,
  material_interest boolean not null default false,
  disclosure_digest text not null,
  recusal_required boolean not null default false,
  created_at timestamptz not null default now(),
  unique(proposal_id,organization_id)
);

create table if not exists public.hivemind_negative_evidence_intelligence (
  id uuid primary key default gen_random_uuid(),
  negative_evidence_id uuid not null unique references public.hivemind_negative_evidence(id) on delete cascade,
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  classification text not null check(classification in('portable_failure','context_mismatch','insufficient_evidence')),
  causal_factors jsonb not null,
  applicable_contexts jsonb not null,
  excluded_contexts jsonb not null,
  confidence numeric not null check(confidence between 0 and 1),
  recommendation text not null,
  intelligence_digest text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists public.hivemind_immune_response_receipts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  signal_id uuid not null references public.hivemind_immune_signals(id) on delete cascade,
  license_id uuid references public.hivemind_executable_licenses(id) on delete set null,
  contribution_id uuid references public.hivemind_capability_contributions(id) on delete set null,
  actions jsonb not null,
  affected_scope jsonb not null,
  customer_impact text not null,
  rollback_ready boolean not null default true,
  response_digest text not null unique,
  status text not null check(status in('contained','review_required','released')),
  created_at timestamptz not null default now(),
  unique(signal_id,organization_id,license_id)
);

create table if not exists public.hivemind_autopilot_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  trigger text not null check(trigger in('session','schedule','event','operator')),
  outcomes jsonb not null default '[]',
  exceptions jsonb not null default '[]',
  operations jsonb not null default '{}',
  run_digest text not null unique,
  status text not null check(status in('completed','attention_required','failed')),
  started_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists idx_hive_execution_proofs_license on public.hivemind_license_execution_proofs(license_id,created_at desc);
create index if not exists idx_hive_derivations_org on public.hivemind_opportunity_derivations(organization_id,created_at desc);
create index if not exists idx_hive_credit_clearing_org on public.hivemind_credit_clearing_runs(organization_id,period_end desc);
create index if not exists idx_hive_simulations_proposal on public.hivemind_governance_simulations(proposal_id);
create index if not exists idx_hive_immune_receipts_org on public.hivemind_immune_response_receipts(organization_id,status,created_at desc);
create index if not exists idx_hive_autopilot_org on public.hivemind_autopilot_runs(organization_id,started_at desc);

alter table public.hivemind_license_execution_proofs enable row level security;
alter table public.hivemind_opportunity_derivations enable row level security;
alter table public.hivemind_credit_accounts enable row level security;
alter table public.hivemind_credit_clearing_runs enable row level security;
alter table public.hivemind_governance_simulations enable row level security;
alter table public.hivemind_governance_conflicts enable row level security;
alter table public.hivemind_negative_evidence_intelligence enable row level security;
alter table public.hivemind_immune_response_receipts enable row level security;
alter table public.hivemind_autopilot_runs enable row level security;

comment on table public.hivemind_license_execution_proofs is 'Signed policy-evaluation receipts over commitments; no execution payloads are stored.';
comment on table public.hivemind_autopilot_runs is 'Outcome and exception summaries for invisible network operations; operation internals are not a primary user surface.';
