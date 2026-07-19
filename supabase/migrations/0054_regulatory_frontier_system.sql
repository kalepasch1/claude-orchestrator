-- Frontier regulatory intelligence: portfolio worldlines, systemic-risk and
-- examination twins, acquisition/capital models, dispute prevention,
-- deployment authority gates, bounded regulator access, and source drift.

create table if not exists public.regulatory_frontier_runs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  project_ref text,
  run_type text not null check (run_type in ('worldline','systemic_risk','examination','acquisition','capital','dispute_prevention')),
  assumptions jsonb not null default '{}',
  outcome jsonb not null default '{}',
  recommended_actions jsonb not null default '[]',
  confidence numeric not null default 0 check (confidence between 0 and 1),
  run_digest text not null unique,
  status text not null default 'current' check (status in ('current','accepted','superseded','dismissed')),
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_deployment_gates (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  project_ref text not null,
  release_ref text not null,
  jurisdiction text not null default 'US-general',
  requested_capabilities jsonb not null default '[]',
  authority_snapshot jsonb not null default '{}',
  decision text not null check (decision in ('allow','hold','block')),
  reasons jsonb not null default '[]',
  required_actions jsonb not null default '[]',
  policy_digest text not null,
  receipt_digest text not null unique,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_authority_sources (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references public.orchestrator_organizations(id) on delete cascade,
  source_key text not null,
  authority text not null,
  jurisdiction text not null,
  source_url text not null,
  effective_at timestamptz,
  content_digest text not null,
  bounded_change_summary jsonb not null default '{}',
  verified_at timestamptz,
  version int not null default 1,
  status text not null default 'current' check (status in ('current','superseded','withdrawn','unverified')),
  created_at timestamptz not null default now(),
  unique (organization_id,source_key,content_digest)
);

create table if not exists public.regulatory_authority_drift_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  authority_source_id uuid references public.regulatory_authority_sources(id) on delete set null,
  prior_digest text,
  current_digest text not null,
  affected_rules jsonb not null default '[]',
  affected_projects jsonb not null default '[]',
  affected_controls jsonb not null default '[]',
  materiality text not null default 'unknown' check (materiality in ('non_material','material','unknown')),
  containment_action text,
  review_required boolean not null default true,
  resolved_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.regulatory_access_grants (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  evidence_room_id uuid references public.regulatory_evidence_rooms(id) on delete cascade,
  grantee_name text not null,
  grantee_domain text,
  purpose text not null,
  allowed_fields jsonb not null default '[]',
  allowed_evidence_types jsonb not null default '[]',
  export_manifest jsonb not null default '{}',
  grant_digest text not null unique,
  approved_by uuid not null,
  approved_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked_at timestamptz,
  last_accessed_at timestamptz,
  status text not null default 'active' check (status in ('active','expired','revoked')),
  created_at timestamptz not null default now()
);

create index if not exists idx_reg_frontier_org on public.regulatory_frontier_runs(organization_id,run_type,status,created_at desc);
create index if not exists idx_reg_deploy_gate_lookup on public.regulatory_deployment_gates(organization_id,project_ref,release_ref,created_at desc);
create index if not exists idx_reg_authority_current on public.regulatory_authority_sources(jurisdiction,source_key,status,created_at desc);
create index if not exists idx_reg_drift_open on public.regulatory_authority_drift_events(organization_id,review_required,created_at desc);
create index if not exists idx_reg_access_active on public.regulatory_access_grants(organization_id,status,expires_at);

alter table public.regulatory_frontier_runs enable row level security;
alter table public.regulatory_deployment_gates enable row level security;
alter table public.regulatory_authority_sources enable row level security;
alter table public.regulatory_authority_drift_events enable row level security;
alter table public.regulatory_access_grants enable row level security;

comment on table public.regulatory_frontier_runs is 'Bounded assumptions and simulated outcomes; not legal advice or a substitute for regulator/counsel review.';
comment on table public.regulatory_deployment_gates is 'Short-lived, machine-readable authority receipts used by CI/CD; hold is the safe default when evidence is incomplete.';
comment on table public.regulatory_access_grants is 'Explicit, revocable, time-limited access to bounded evidence manifests; raw evidence is never copied into Madeus.';
