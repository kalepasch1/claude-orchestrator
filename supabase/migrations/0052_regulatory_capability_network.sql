-- Regulated Capability Network. Stores bounded activity signals, eligibility
-- evidence, relationship controls, and decisions. Raw code and legal documents
-- remain in their systems of record.

create table if not exists public.regulatory_capability_profiles (
  organization_id uuid primary key references public.orchestrator_organizations(id) on delete cascade,
  jurisdictions text[] not null default '{}',
  business_models text[] not null default '{}',
  autonomy jsonb not null default '{"continuous_detection":true,"auto_non_material":true,"material_changes":false,"external_sharing":false}',
  risk_tolerance text not null default 'standard' check (risk_tolerance in ('conservative','standard','growth')),
  assistance_provider text not null default 'apparently',
  relationship_provider text not null default 'smarter',
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table if not exists public.regulatory_rule_catalog (
  id uuid primary key default gen_random_uuid(),
  rule_key text not null unique,
  domain text not null,
  jurisdiction text not null default 'US-general',
  activity_patterns text[] not null,
  trigger_summary text not null,
  coverage_models jsonb not null default '[]',
  eligibility_requirements jsonb not null default '[]',
  prohibited_shortcuts text[] not null default '{}',
  source_refs jsonb not null default '[]',
  version text not null,
  effective_at timestamptz,
  reviewed_at timestamptz,
  status text not null default 'guidance' check (status in ('guidance','counsel_reviewed','regulator_confirmed','retired')),
  updated_at timestamptz not null default now()
);

create table if not exists public.regulatory_activity_signals (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  project_ref text,
  source_type text not null check (source_type in ('code','product','marketing','contract','operations','user','integration')),
  source_ref text not null,
  source_digest text not null,
  bounded_indicators jsonb not null default '{}',
  detected_activities text[] not null default '{}',
  jurisdictions text[] not null default '{}',
  materiality text not null default 'unknown' check (materiality in ('non_material','material','unknown')),
  confidence numeric not null check (confidence between 0 and 1),
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  status text not null default 'active' check (status in ('active','dismissed','superseded')),
  unique (organization_id, source_digest)
);

create table if not exists public.regulatory_activity_assessments (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  signal_id uuid not null references public.regulatory_activity_signals(id) on delete cascade,
  rule_id uuid references public.regulatory_rule_catalog(id) on delete set null,
  activity text not null,
  regulated_core jsonb not null default '{}',
  unregulated_components jsonb not null default '[]',
  verdict text not null check (verdict in ('covered','conditionally_covered','referral_only','not_covered','counsel_required')),
  reasons jsonb not null default '[]',
  required_actions jsonb not null default '[]',
  safe_alternatives jsonb not null default '[]',
  confidence numeric not null check (confidence between 0 and 1),
  assessment_digest text not null unique,
  status text not null default 'current' check (status in ('current','superseded','accepted','dismissed')),
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_readiness_paths (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  rule_id uuid references public.regulatory_rule_catalog(id) on delete set null,
  target_capability text not null,
  jurisdiction text not null,
  requirements jsonb not null default '[]',
  evidence jsonb not null default '{}',
  blockers jsonb not null default '[]',
  next_actions jsonb not null default '[]',
  readiness_score int not null default 0 check (readiness_score between 0 and 100),
  earliest_eligible_at timestamptz,
  simulation_status text not null default 'shadow' check (simulation_status in ('shadow','eligible','application_ready','submitted','licensed','paused')),
  assistance_enabled boolean not null default false,
  updated_at timestamptz not null default now(),
  unique (organization_id, target_capability, jurisdiction)
);

create table if not exists public.regulatory_relationships (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  counterparty_organization_id uuid references public.orchestrator_organizations(id) on delete set null,
  counterparty_name text not null,
  relationship_type text not null check (relationship_type in ('sponsor','authorized_delegate','associated_person','appointment','white_label','service_provider','referral','partnership','guarantee','subsidiary','other')),
  covered_activities text[] not null default '{}',
  jurisdictions text[] not null default '{}',
  authority_limits jsonb not null default '{}',
  economics jsonb not null default '{}',
  agreement_refs jsonb not null default '[]',
  supervision_plan jsonb not null default '{}',
  organization_approved_at timestamptz,
  counterparty_approved_at timestamptz,
  regulator_approved_at timestamptz,
  effective_at timestamptz,
  expires_at timestamptz,
  status text not null default 'draft' check (status in ('draft','proposed','pending_counterparty','pending_regulator','active','suspended','terminated')),
  updated_at timestamptz not null default now()
);

create table if not exists public.regulatory_relationship_events (
  id uuid primary key default gen_random_uuid(),
  relationship_id uuid not null references public.regulatory_relationships(id) on delete cascade,
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  event_type text not null check (event_type in ('code_change','marketing_change','activity','complaint','limit','evidence','agreement','approval','suspension')),
  severity text not null check (severity in ('info','warning','high','critical')),
  bounded_facts jsonb not null default '{}',
  obligation_refs jsonb not null default '[]',
  action_taken text,
  event_digest text not null unique,
  status text not null default 'open' check (status in ('open','contained','acknowledged','resolved')),
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_assistance_requests (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  assessment_id uuid references public.regulatory_activity_assessments(id) on delete set null,
  readiness_path_id uuid references public.regulatory_readiness_paths(id) on delete set null,
  relationship_id uuid references public.regulatory_relationships(id) on delete set null,
  provider text not null check (provider in ('apparently','smarter','combined')),
  assistance_type text not null check (assistance_type in ('eligibility','application','business_model','code_boundary','marketing','contract','relationship','monitoring')),
  bounded_brief jsonb not null,
  external_share_approved_at timestamptz,
  execution_ref text,
  status text not null default 'draft' check (status in ('draft','approved','queued','in_progress','setup_required','completed','failed','cancelled')),
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.regulatory_autopilot_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  trigger text not null check (trigger in ('session','schedule','event','operator')),
  signals_processed int not null default 0,
  assessments_created int not null default 0,
  paths_updated int not null default 0,
  relationship_alerts int not null default 0,
  outcomes jsonb not null default '[]',
  exceptions jsonb not null default '[]',
  run_digest text not null unique,
  status text not null check (status in ('completed','attention_required','failed')),
  created_at timestamptz not null default now()
);

create index if not exists idx_reg_signals_org on public.regulatory_activity_signals(organization_id,status,last_seen_at desc);
create index if not exists idx_reg_assessments_org on public.regulatory_activity_assessments(organization_id,status,created_at desc);
create index if not exists idx_reg_paths_org on public.regulatory_readiness_paths(organization_id,readiness_score desc);
create index if not exists idx_reg_relationships_org on public.regulatory_relationships(organization_id,status,updated_at desc);
create index if not exists idx_reg_events_relationship on public.regulatory_relationship_events(relationship_id,status,created_at desc);

alter table public.regulatory_capability_profiles enable row level security;
alter table public.regulatory_rule_catalog enable row level security;
alter table public.regulatory_activity_signals enable row level security;
alter table public.regulatory_activity_assessments enable row level security;
alter table public.regulatory_readiness_paths enable row level security;
alter table public.regulatory_relationships enable row level security;
alter table public.regulatory_relationship_events enable row level security;
alter table public.regulatory_assistance_requests enable row level security;
alter table public.regulatory_autopilot_runs enable row level security;

comment on table public.regulatory_activity_signals is 'Bounded indicators and hashes only; raw source and legal documents remain in their source systems.';
comment on table public.regulatory_activity_assessments is 'Decision support, not a representation that an organization or activity is licensed.';
