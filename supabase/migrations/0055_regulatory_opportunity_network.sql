-- Regulatory opportunity network: explainable causality, smallest-change
-- market unlocks, portable capability evidence, supervisory capacity,
-- privacy-safe precedent learning, safe-harbor controls, and incident twins.

create table if not exists public.regulatory_counterfactual_opportunities (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  assessment_id uuid references public.regulatory_activity_assessments(id) on delete cascade, project_ref text,
  baseline jsonb not null default '{}', proposed_change jsonb not null default '{}', unlocked_markets jsonb not null default '[]',
  retained_capabilities jsonb not null default '[]', lost_capabilities jsonb not null default '[]', implementation_plan jsonb not null default '[]',
  qa_plan jsonb not null default '[]', expected_value_cents bigint not null default 0, direct_cost_cents bigint not null default 0,
  time_to_value_days int not null default 0, reversibility_score int not null default 0 check (reversibility_score between 0 and 100),
  confidence numeric not null default 0 check (confidence between 0 and 1), opportunity_digest text not null unique,
  status text not null default 'proposed' check (status in ('proposed','selected','preparing','active','dismissed','superseded')),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);

create table if not exists public.regulatory_causality_receipts (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  subject_type text not null, subject_id text not null, decision text not null, causes jsonb not null default '[]',
  authority_refs jsonb not null default '[]', evidence_refs jsonb not null default '[]', agreement_refs jsonb not null default '[]',
  approval_refs jsonb not null default '[]', counterfactuals jsonb not null default '[]', receipt_digest text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_portability_opportunities (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  source_capability text not null, target_capability text not null, source_jurisdiction text not null, target_jurisdiction text not null,
  portable_evidence jsonb not null default '[]', nonportable_requirements jsonb not null default '[]', consent_requirements jsonb not null default '[]',
  predicted_time_saved_days int not null default 0, predicted_cost_saved_cents bigint not null default 0, confidence numeric not null default 0,
  opportunity_digest text not null unique, status text not null default 'available' check (status in ('available','selected','preparing','used','rejected','expired')),
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_feedback_patterns (
  id uuid primary key default gen_random_uuid(), pattern_key text not null, domain text not null, jurisdiction text not null,
  cohort_size int not null default 0, bounded_pattern jsonb not null default '{}', recommended_control jsonb not null default '{}',
  support_score numeric not null default 0, privacy_threshold_met boolean not null default false, pattern_digest text not null unique,
  status text not null default 'shadow' check (status in ('shadow','eligible','adopted','retired')), created_at timestamptz not null default now()
);

create table if not exists public.regulatory_feedback_observations (
  id uuid primary key default gen_random_uuid(), organization_digest text not null, domain text not null, jurisdiction text not null,
  finding_code text not null, result text not null check (result in ('finding','accepted','remediated','withdrawn')),
  recommended_control text, observation_digest text not null unique, observed_at timestamptz not null default now()
);

create table if not exists public.regulatory_supervisory_capacity (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  relationship_id uuid references public.regulatory_relationships(id) on delete set null, capability text not null, jurisdictions jsonb not null default '[]',
  capacity_units int not null default 0, used_units int not null default 0, eligibility_constraints jsonb not null default '[]',
  pricing_model jsonb not null default '{}', correlation_limits jsonb not null default '{}', consent_mode text not null default 'per_match',
  status text not null default 'shadow' check (status in ('shadow','available','paused','exhausted','retired')), updated_at timestamptz not null default now()
);

create table if not exists public.regulatory_safe_harbor_controls (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  project_ref text not null, safe_harbor_key text not null, jurisdiction text not null, authority_refs jsonb not null default '[]',
  eligibility_conditions jsonb not null default '[]', executable_controls jsonb not null default '[]', evidence_schedule jsonb not null default '{}',
  disqualifying_events jsonb not null default '[]', enforcement_mode text not null default 'shadow' check (enforcement_mode in ('shadow','advisory','enforced')),
  control_digest text not null unique, status text not null default 'current' check (status in ('current','superseded','revoked')), updated_at timestamptz not null default now()
);

create table if not exists public.regulatory_incident_twins (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  project_ref text, incident_type text not null, assumptions jsonb not null default '{}', cascade jsonb not null default '[]',
  containment_plan jsonb not null default '[]', notification_plan jsonb not null default '[]', authority_effects jsonb not null default '[]',
  recovery_plan jsonb not null default '[]', direct_cost_cents bigint not null default 0, downtime_hours numeric not null default 0,
  incident_digest text not null unique, status text not null default 'simulated' check (status in ('simulated','accepted','activated','closed','superseded')),
  created_at timestamptz not null default now()
);

create index if not exists idx_reg_counterfactual_org on public.regulatory_counterfactual_opportunities(organization_id,status,expected_value_cents desc);
create index if not exists idx_reg_causality_subject on public.regulatory_causality_receipts(organization_id,subject_type,subject_id,created_at desc);
create index if not exists idx_reg_portability_org on public.regulatory_portability_opportunities(organization_id,status,predicted_cost_saved_cents desc);
create index if not exists idx_reg_capacity_org on public.regulatory_supervisory_capacity(organization_id,status,updated_at desc);
create index if not exists idx_reg_safe_harbor_org on public.regulatory_safe_harbor_controls(organization_id,project_ref,jurisdiction,status);
create index if not exists idx_reg_incident_org on public.regulatory_incident_twins(organization_id,created_at desc);

alter table public.regulatory_counterfactual_opportunities enable row level security;
alter table public.regulatory_causality_receipts enable row level security;
alter table public.regulatory_portability_opportunities enable row level security;
alter table public.regulatory_feedback_patterns enable row level security;
alter table public.regulatory_feedback_observations enable row level security;
alter table public.regulatory_supervisory_capacity enable row level security;
alter table public.regulatory_safe_harbor_controls enable row level security;
alter table public.regulatory_incident_twins enable row level security;

comment on table public.regulatory_counterfactual_opportunities is 'Proactive smallest-change lawful-market unlocks; proposals remain shadow until explicitly selected.';
comment on table public.regulatory_feedback_patterns is 'Cross-organization patterns are usable only after a minimum privacy cohort is met; organization-level examples are never exposed.';
comment on table public.regulatory_feedback_observations is 'De-identified bounded outcome observations; no organization identifiers, narratives, documents, or raw evidence.';
comment on table public.regulatory_causality_receipts is 'Machine-verifiable explanation of why an authority decision occurred, based on bounded references and hashes.';
