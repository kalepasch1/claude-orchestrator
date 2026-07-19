-- Regulatory execution network: negotiated operating perimeters, market topology,
-- authority yield, prediction accountability, reversible jurisdiction launches,
-- supervisory attention allocation, and realized counterfactual learning.

create table if not exists public.regulatory_operating_perimeters (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  project_ref text not null, objective text not null, jurisdictions jsonb not null default '[]', selected_variants jsonb not null default '[]',
  retained_capabilities jsonb not null default '[]', excluded_actions jsonb not null default '[]', provider_handoffs jsonb not null default '[]',
  contract_changes jsonb not null default '[]', pricing_changes jsonb not null default '[]', marketing_changes jsonb not null default '[]',
  expected_value_cents bigint not null default 0, residual_risk_score int not null default 0, perimeter_digest text not null unique,
  status text not null default 'shadow' check (status in ('shadow','review','approved','active','superseded')), updated_at timestamptz not null default now()
);

create table if not exists public.regulatory_market_topology_snapshots (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  nodes jsonb not null default '[]', edges jsonb not null default '[]', reachable_markets jsonb not null default '[]', blocked_markets jsonb not null default '[]',
  critical_dependencies jsonb not null default '[]', topology_digest text not null unique, status text not null default 'current' check (status in ('current','superseded')),
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_authority_allocations (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  asset_ref text not null, opportunity_ref text not null, allocated_units numeric not null default 0, expected_value_cents bigint not null default 0,
  marginal_value_cents bigint not null default 0, risk_charge_cents bigint not null default 0, constraints jsonb not null default '[]',
  allocation_digest text not null unique, status text not null default 'recommended' check (status in ('recommended','approved','active','released','rejected')),
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_confidence_bonds (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  prediction_ref text not null, prediction_type text not null, predicted_probability numeric not null check (predicted_probability between 0 and 1),
  predicted_value jsonb not null default '{}', invalidation_triggers jsonb not null default '[]', reliance_limit_cents bigint not null default 0,
  accountability_reserve_cents bigint not null default 0, realized_value jsonb, calibration_score numeric, settled_at timestamptz,
  bond_digest text not null unique, status text not null default 'open' check (status in ('open','invalidated','settled','expired')),
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_jurisdiction_launches (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  project_ref text not null, feature_key text not null, jurisdiction text not null, target_market jsonb not null default '{}',
  stages jsonb not null default '[]', current_stage text not null default 'shadow', lawful_fallback jsonb not null default '{}',
  evidence_contract jsonb not null default '{}', rollback_policy jsonb not null default '{}', reentry_policy jsonb not null default '{}',
  latest_decision jsonb not null default '{}', launch_digest text not null unique,
  activation_approved_at timestamptz, activated_by uuid, status text not null default 'shadow' check (status in ('shadow','ready','active','paused','rolled_back','completed','retired')),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique (organization_id,project_ref,feature_key,jurisdiction)
);

create table if not exists public.regulatory_launch_events (
  id uuid primary key default gen_random_uuid(), launch_id uuid not null references public.regulatory_jurisdiction_launches(id) on delete cascade,
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade, event_type text not null,
  from_stage text, to_stage text, bounded_metrics jsonb not null default '{}', evidence_refs jsonb not null default '[]',
  decision jsonb not null default '{}', receipt_digest text not null unique, created_at timestamptz not null default now()
);

create table if not exists public.regulatory_attention_allocations (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  work_ref text not null, work_type text not null, specialist_role text not null, assigned_member_ref text, scheduled_start timestamptz,
  allocated_minutes int not null default 0, marginal_risk_reduction numeric not null default 0, unlocked_value_cents bigint not null default 0,
  urgency_score int not null default 0, conflict_flags jsonb not null default '[]', minimum_review_floor_minutes int not null default 0,
  explanation jsonb not null default '{}', allocation_digest text not null unique,
  status text not null default 'recommended' check (status in ('recommended','accepted','in_progress','completed','reallocated','cancelled')),
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_counterfactual_outcomes (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  opportunity_id uuid not null references public.regulatory_counterfactual_opportunities(id) on delete cascade,
  predicted jsonb not null default '{}', realized jsonb not null default '{}', deltas jsonb not null default '{}', lessons jsonb not null default '[]',
  model_adjustments jsonb not null default '{}', outcome_digest text not null unique, observed_at timestamptz not null default now()
);

create index if not exists idx_reg_perimeter_org on public.regulatory_operating_perimeters(organization_id,status,updated_at desc);
create index if not exists idx_reg_topology_org on public.regulatory_market_topology_snapshots(organization_id,status,created_at desc);
create index if not exists idx_reg_alloc_org on public.regulatory_authority_allocations(organization_id,status,expected_value_cents desc);
create index if not exists idx_reg_bonds_open on public.regulatory_confidence_bonds(organization_id,status,created_at desc);
create index if not exists idx_reg_launch_org on public.regulatory_jurisdiction_launches(organization_id,status,updated_at desc);
create index if not exists idx_reg_launch_events on public.regulatory_launch_events(launch_id,created_at desc);
create index if not exists idx_reg_attention_org on public.regulatory_attention_allocations(organization_id,status,urgency_score desc);
create index if not exists idx_reg_cf_outcomes_org on public.regulatory_counterfactual_outcomes(organization_id,observed_at desc);

alter table public.regulatory_operating_perimeters enable row level security;
alter table public.regulatory_market_topology_snapshots enable row level security;
alter table public.regulatory_authority_allocations enable row level security;
alter table public.regulatory_confidence_bonds enable row level security;
alter table public.regulatory_jurisdiction_launches enable row level security;
alter table public.regulatory_launch_events enable row level security;
alter table public.regulatory_attention_allocations enable row level security;
alter table public.regulatory_counterfactual_outcomes enable row level security;

comment on table public.regulatory_jurisdiction_launches is 'Reversible, jurisdiction-scoped launch state machines; activation and re-entry require explicit approval plus current authority proof.';
comment on table public.regulatory_attention_allocations is 'Explainable recommendations for scarce expert review time; minimum human-review floors and conflicts cannot be optimized away.';
comment on table public.regulatory_confidence_bonds is 'Prediction accountability and calibration record; not a security, insurance contract, or transfer of legal liability.';
