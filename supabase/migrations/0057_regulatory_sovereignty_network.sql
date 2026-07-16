-- Regulatory sovereignty network: proof-carrying product behavior, structural
-- scenarios, catastrophe resilience, launch tournaments, supervisory review
-- packets, authority option value, examiner forecasts, and review learning.

create table if not exists public.regulatory_product_attestations (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  project_ref text not null, feature_key text not null, jurisdiction text not null, release_ref text not null,
  authority_receipts jsonb not null default '[]', agreement_receipts jsonb not null default '[]', evidence_receipts jsonb not null default '[]',
  prediction_receipts jsonb not null default '[]', approval_receipts jsonb not null default '[]', fallback_receipt jsonb not null default '{}',
  rollback_receipt jsonb not null default '{}', effective_behavior jsonb not null default '{}', missing_proofs jsonb not null default '[]',
  attestation_digest text not null unique, expires_at timestamptz not null, status text not null default 'incomplete' check (status in ('incomplete','valid','expired','revoked')),
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_structuring_scenarios (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  objective text not null, assumptions jsonb not null default '{}', entity_graph jsonb not null default '{}', jurisdiction_plan jsonb not null default '[]',
  ownership_controls jsonb not null default '[]', intercompany_agreements jsonb not null default '[]', staffing_plan jsonb not null default '[]',
  authority_plan jsonb not null default '[]', tax_coordination_flags jsonb not null default '[]', timeline jsonb not null default '{}',
  costs jsonb not null default '{}', expected_value_cents bigint not null default 0, residual_risks jsonb not null default '[]', scenario_digest text not null unique,
  execution_requires_separate_approvals boolean not null default true,
  status text not null default 'modeled' check (status in ('modeled','selected','review','executing','active','dismissed')), created_at timestamptz not null default now()
);

create table if not exists public.regulatory_catastrophe_scenarios (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  scenario_name text not null, shocks jsonb not null default '[]', cascade jsonb not null default '[]', affected_capabilities jsonb not null default '[]',
  liquidity_effects jsonb not null default '{}', authority_effects jsonb not null default '[]', customer_effects jsonb not null default '[]',
  containment_plan jsonb not null default '[]', recovery_plan jsonb not null default '[]', expected_loss_cents bigint not null default 0,
  tail_loss_cents bigint not null default 0, recovery_hours numeric not null default 0, resilience_score int not null default 0,
  scenario_digest text not null unique, status text not null default 'current' check (status in ('current','accepted','activated','superseded')), created_at timestamptz not null default now()
);

create table if not exists public.regulatory_launch_tournaments (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  opportunity_id uuid references public.regulatory_counterfactual_opportunities(id) on delete cascade, jurisdiction text not null,
  candidates jsonb not null default '[]', evaluation_metrics jsonb not null default '{}', winner jsonb, promotion_receipt jsonb,
  tournament_digest text not null unique, status text not null default 'shadow' check (status in ('shadow','running','winner_ready','promoted','cancelled')),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);

create table if not exists public.regulatory_supervisory_packets (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  allocation_id uuid references public.regulatory_attention_allocations(id) on delete cascade, subject_ref text not null,
  issue_tree jsonb not null default '[]', bounded_facts jsonb not null default '{}', authority_refs jsonb not null default '[]',
  evidence_manifest jsonb not null default '[]', contradictions jsonb not null default '[]', options jsonb not null default '[]',
  recommended_questions jsonb not null default '[]', draft_determination jsonb not null default '{}', packet_digest text not null unique,
  human_judgment_required jsonb not null default '[]', status text not null default 'prepared' check (status in ('prepared','reviewed','accepted','superseded')),
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_option_value_ledger (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  asset_type text not null, asset_ref text not null, jurisdictions jsonb not null default '[]', enabled_paths jsonb not null default '[]',
  replacement_cost_cents bigint not null default 0, time_to_replace_days int not null default 0, annual_carry_cost_cents bigint not null default 0,
  probability_of_use numeric not null default 0, strategic_option_value_cents bigint not null default 0, decay_triggers jsonb not null default '[]',
  preservation_actions jsonb not null default '[]', valuation_digest text not null unique, valued_at timestamptz not null default now(),
  status text not null default 'current' check (status in ('current','decaying','exercised','expired','retired'))
);

create table if not exists public.regulatory_examiner_forecasts (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  target_capability text not null, jurisdiction text not null, examination_type text not null, predicted_questions jsonb not null default '[]',
  likely_findings jsonb not null default '[]', missing_evidence jsonb not null default '[]', answer_packets jsonb not null default '[]',
  confidence numeric not null default 0, invalidation_triggers jsonb not null default '[]', forecast_digest text not null unique,
  status text not null default 'current' check (status in ('current','rehearsed','superseded','realized')), created_at timestamptz not null default now()
);

create table if not exists public.regulatory_review_effectiveness (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  allocation_id uuid references public.regulatory_attention_allocations(id) on delete set null, reviewer_ref text, subject_ref text not null,
  minutes_spent int not null default 0, risk_before numeric not null default 0, risk_after numeric not null default 0,
  value_before_cents bigint not null default 0, value_after_cents bigint not null default 0, deficiency_delta int not null default 0,
  approval_probability_before numeric not null default 0, approval_probability_after numeric not null default 0, outcome_refs jsonb not null default '[]',
  effectiveness_score numeric not null default 0, lessons jsonb not null default '[]', measurement_digest text not null unique,
  measured_at timestamptz not null default now()
);

create index if not exists idx_reg_attest_org on public.regulatory_product_attestations(organization_id,status,expires_at);
create index if not exists idx_reg_structure_org on public.regulatory_structuring_scenarios(organization_id,status,created_at desc);
create index if not exists idx_reg_catastrophe_org on public.regulatory_catastrophe_scenarios(organization_id,status,created_at desc);
create index if not exists idx_reg_tournament_org on public.regulatory_launch_tournaments(organization_id,status,updated_at desc);
create index if not exists idx_reg_packet_org on public.regulatory_supervisory_packets(organization_id,status,created_at desc);
create index if not exists idx_reg_option_org on public.regulatory_option_value_ledger(organization_id,status,strategic_option_value_cents desc);
create index if not exists idx_reg_examiner_org on public.regulatory_examiner_forecasts(organization_id,status,created_at desc);
create index if not exists idx_reg_review_org on public.regulatory_review_effectiveness(organization_id,measured_at desc);

alter table public.regulatory_product_attestations enable row level security;
alter table public.regulatory_structuring_scenarios enable row level security;
alter table public.regulatory_catastrophe_scenarios enable row level security;
alter table public.regulatory_launch_tournaments enable row level security;
alter table public.regulatory_supervisory_packets enable row level security;
alter table public.regulatory_option_value_ledger enable row level security;
alter table public.regulatory_examiner_forecasts enable row level security;
alter table public.regulatory_review_effectiveness enable row level security;

comment on table public.regulatory_product_attestations is 'Short-lived proof manifest for effective product behavior; missing or expired proof fails closed at the affected feature boundary.';
comment on table public.regulatory_supervisory_packets is 'CADE-prepared bounded review packet; explicit human judgment fields cannot be auto-decided.';
comment on table public.regulatory_structuring_scenarios is 'Decision support only; tax, legal, regulator, ownership and counterparty approvals remain external authority.';
