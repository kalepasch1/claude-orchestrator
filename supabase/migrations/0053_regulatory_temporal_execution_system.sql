-- Predictive regulatory operating system: temporal scenarios, executable
-- agreement controls, evidence rooms, feature boundaries, CADE settlement,
-- and decision-ready license economics.

create table if not exists public.regulatory_temporal_scenarios (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  project_ref text,
  scenario_type text not null check (scenario_type in ('law_change','license_expiry','ownership_change','enforcement','growth','jurisdiction_entry','combined')),
  assumptions jsonb not null default '{}',
  horizon_start timestamptz not null default now(),
  horizon_end timestamptz not null,
  jurisdiction_sequence jsonb not null default '[]',
  authority_timeline jsonb not null default '[]',
  cade_prediction jsonb not null default '{}',
  recommended_plan jsonb not null default '[]',
  invalidation_triggers jsonb not null default '[]',
  scenario_digest text not null unique,
  status text not null default 'current' check (status in ('current','superseded','accepted','dismissed')),
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_agreement_controls (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  relationship_id uuid references public.regulatory_relationships(id) on delete cascade,
  agreement_ref text not null,
  agreement_digest text not null,
  control_version int not null default 1,
  interpreted_terms jsonb not null default '{}',
  executable_controls jsonb not null default '[]',
  approval_gates jsonb not null default '[]',
  reporting_schedule jsonb not null default '[]',
  termination_rules jsonb not null default '[]',
  interpretation_confidence numeric not null check (interpretation_confidence between 0 and 1),
  activation_approved_at timestamptz,
  activated_by uuid,
  status text not null default 'shadow' check (status in ('draft','shadow','active','suspended','retired')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, agreement_digest, control_version)
);

create table if not exists public.regulatory_obligation_ledger (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  agreement_control_id uuid references public.regulatory_agreement_controls(id) on delete cascade,
  relationship_id uuid references public.regulatory_relationships(id) on delete cascade,
  obligor_ref text not null,
  beneficiary_ref text,
  obligation_key text not null,
  obligation_type text not null check (obligation_type in ('service_level','economic','reporting','approval','conduct','data','compliance','termination','other')),
  due_at timestamptz,
  measured_value jsonb,
  target_value jsonb,
  direct_cost_cents bigint not null default 0,
  indirect_cost_cents bigint not null default 0,
  evidence_refs jsonb not null default '[]',
  deviation jsonb,
  status text not null default 'pending' check (status in ('pending','satisfied','at_risk','breached','waived','disputed','cured')),
  measured_at timestamptz,
  created_at timestamptz not null default now(),
  unique (agreement_control_id, obligation_key, due_at)
);

create table if not exists public.regulatory_evidence_rooms (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  readiness_path_id uuid references public.regulatory_readiness_paths(id) on delete cascade,
  target_capability text not null,
  jurisdiction text not null,
  purpose text not null check (purpose in ('shadow_license','application','examination','renewal','relationship_due_diligence')),
  predicted_activation_at timestamptz,
  manifest jsonb not null default '{}',
  completeness_score int not null default 0 check (completeness_score between 0 and 100),
  freshness_score int not null default 0 check (freshness_score between 0 and 100),
  contradiction_count int not null default 0,
  eligibility_effects jsonb not null default '[]',
  room_digest text not null unique,
  status text not null default 'building' check (status in ('building','review_ready','application_ready','submitted','exam_active','archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id,target_capability,jurisdiction,purpose)
);

create table if not exists public.regulatory_evidence_items (
  id uuid primary key default gen_random_uuid(),
  room_id uuid not null references public.regulatory_evidence_rooms(id) on delete cascade,
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  requirement_key text not null,
  evidence_type text not null,
  source_system text not null,
  source_ref text not null,
  evidence_digest text not null,
  bounded_facts jsonb not null default '{}',
  observed_at timestamptz,
  expires_at timestamptz,
  verification_status text not null default 'unverified' check (verification_status in ('unverified','verified','stale','contradicted','rejected')),
  verified_by text,
  created_at timestamptz not null default now(),
  unique (room_id,requirement_key,evidence_digest)
);

create table if not exists public.regulatory_feature_controls (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  project_ref text not null,
  feature_key text not null,
  jurisdiction text not null,
  activity text not null,
  required_authority jsonb not null default '{}',
  current_coverage jsonb not null default '{}',
  compliant_variants jsonb not null default '[]',
  activation_plan jsonb not null default '[]',
  enforcement_mode text not null default 'advisory' check (enforcement_mode in ('advisory','shadow','enforced')),
  desired_state text not null default 'available_when_covered' check (desired_state in ('enabled','disabled','available_when_covered','adjusted')),
  effective_state text not null default 'shadow' check (effective_state in ('enabled','disabled','adjusted','shadow','blocked')),
  one_click_action jsonb not null default '{}',
  activated_at timestamptz,
  activated_by uuid,
  control_digest text not null unique,
  updated_at timestamptz not null default now(),
  unique (organization_id,project_ref,feature_key,jurisdiction)
);

create table if not exists public.regulatory_strategy_options (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  assessment_id uuid references public.regulatory_activity_assessments(id) on delete cascade,
  readiness_path_id uuid references public.regulatory_readiness_paths(id) on delete cascade,
  option_type text not null check (option_type in ('obtain_license','sponsor','restructure','acquire_entity','referral','delay','abandon')),
  title text not null,
  assumptions jsonb not null default '{}',
  timeline jsonb not null default '{}',
  direct_costs jsonb not null default '{}',
  indirect_costs jsonb not null default '{}',
  expected_value jsonb not null default '{}',
  risks jsonb not null default '[]',
  dependencies jsonb not null default '[]',
  cade_score jsonb not null default '{}',
  activation_action jsonb not null default '{}',
  option_digest text not null unique,
  status text not null default 'available' check (status in ('available','selected','preparing','active','rejected','superseded')),
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_cade_settlement_elections (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  agreement_control_id uuid not null references public.regulatory_agreement_controls(id) on delete cascade,
  counterparty_organization_id uuid references public.orchestrator_organizations(id) on delete set null,
  scope jsonb not null default '{}',
  tier_structure jsonb not null default '{"initial":"standard","appeal":"enhanced","final":"extreme"}',
  fee_structure jsonb not null default '{}',
  evidence_rules jsonb not null default '{}',
  governing_terms_ref text,
  organization_approved_at timestamptz,
  counterparty_approved_at timestamptz,
  activation_approved_at timestamptz,
  status text not null default 'offered' check (status in ('offered','pending_counterparty','active','declined','revoked')),
  created_at timestamptz not null default now(),
  unique (agreement_control_id)
);

create index if not exists idx_reg_temporal_org on public.regulatory_temporal_scenarios(organization_id,status,created_at desc);
create index if not exists idx_reg_agreement_org on public.regulatory_agreement_controls(organization_id,status,updated_at desc);
create index if not exists idx_reg_obligations_org on public.regulatory_obligation_ledger(organization_id,status,due_at);
create index if not exists idx_reg_evidence_org on public.regulatory_evidence_rooms(organization_id,status,updated_at desc);
create index if not exists idx_reg_feature_org on public.regulatory_feature_controls(organization_id,project_ref,jurisdiction,effective_state);
create index if not exists idx_reg_options_org on public.regulatory_strategy_options(organization_id,status,created_at desc);

alter table public.regulatory_temporal_scenarios enable row level security;
alter table public.regulatory_agreement_controls enable row level security;
alter table public.regulatory_obligation_ledger enable row level security;
alter table public.regulatory_evidence_rooms enable row level security;
alter table public.regulatory_evidence_items enable row level security;
alter table public.regulatory_feature_controls enable row level security;
alter table public.regulatory_strategy_options enable row level security;
alter table public.regulatory_cade_settlement_elections enable row level security;

comment on table public.regulatory_agreement_controls is 'Agreement interpretations remain shadow controls until a user explicitly activates them.';
comment on table public.regulatory_feature_controls is 'Jurisdiction-scoped product controls; advisory by default and enforced only after explicit activation.';
comment on table public.regulatory_evidence_items is 'Bounded facts and content digests only; underlying evidence remains in its source system.';
