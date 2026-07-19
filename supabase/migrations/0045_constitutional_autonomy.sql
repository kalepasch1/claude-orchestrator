-- Constitutional autonomy: institutional separation of powers, causal evidence,
-- outcome treasury, selective disclosure, immune response, policy compilation,
-- portable continuity, and adversarial journey certification.

create table if not exists constitutional_institutions (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  name text not null, constitution_version integer not null default 1, roles jsonb not null,
  separation_rules jsonb not null, appeal_policy jsonb not null, status text not null default 'active' check (status in ('draft','active','paused','retired')),
  created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists institutional_cases (
  id uuid primary key default gen_random_uuid(), institution_id uuid not null references constitutional_institutions(id) on delete cascade,
  organization_id uuid not null references orchestrator_organizations(id) on delete cascade, objective text not null,
  assignments jsonb not null, stage text not null default 'proposed' check (stage in ('proposed','simulated','reviewed','approved','executed','audited','appealed','closed')),
  decision jsonb not null default '{}', proof_envelope_id uuid references execution_proof_envelopes(id) on delete set null,
  created_by uuid not null references auth.users(id), created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists causal_outcome_evidence (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  intervention text not null, population jsonb not null default '{}', treatment jsonb not null, control jsonb not null,
  estimated_effect jsonb not null, confidence numeric not null check (confidence between 0 and 1), privacy jsonb not null,
  evidence_digest text not null, sharing_status text not null default 'private' check (sharing_status in ('private','federated','withdrawn')),
  created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists capability_treasury_allocations (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  capability text not null, proposed_budget_usd numeric not null default 0, realized_roi numeric, warranty_score numeric,
  opportunity_cost numeric, recommendation jsonb not null, status text not null default 'proposed' check (status in ('proposed','approved','allocated','paused','reclaimed')),
  proof_envelope_id uuid references execution_proof_envelopes(id) on delete set null, created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists selective_disclosure_credentials (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  subject_user_id uuid not null references auth.users(id) on delete cascade, claim_type text not null, claim_commitment text not null,
  disclosure_policy jsonb not null, proof jsonb not null, status text not null default 'active' check (status in ('active','revoked','expired')),
  expires_at timestamptz, created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists immune_response_incidents (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  signal jsonb not null, severity text not null check (severity in ('low','medium','high','critical')), affected_capabilities text[] not null default '{}',
  response_plan jsonb not null, status text not null default 'detected' check (status in ('detected','quarantined','approval_required','recovering','verified','closed')),
  release_snapshot_id uuid references release_state_snapshots(id) on delete set null, proof_envelope_id uuid references execution_proof_envelopes(id) on delete set null,
  created_by uuid not null references auth.users(id), created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists compiled_organizational_policies (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  source_text text not null, policy_ast jsonb not null, executable_rules jsonb not null, test_cases jsonb not null,
  test_result jsonb not null, compatibility jsonb not null, status text not null default 'draft' check (status in ('draft','tested','approved','active','superseded')),
  created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists agent_continuity_capsules (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade, capsule_version integer not null default 1,
  encrypted_payload text not null, payload_digest text not null, manifest jsonb not null, portability_policy jsonb not null,
  status text not null default 'active' check (status in ('active','exported','revoked','superseded')), created_at timestamptz not null default now()
);
create table if not exists adversarial_journey_runs (
  id uuid primary key default gen_random_uuid(), organization_id uuid references orchestrator_organizations(id) on delete cascade,
  contract_version integer not null, profiles jsonb not null, fault_matrix jsonb not null, results jsonb not null,
  status text not null check (status in ('passed','failed','partial')), deployment_url text, created_by uuid references auth.users(id), created_at timestamptz not null default now()
);
create index if not exists institutional_cases_org_created_idx on institutional_cases(organization_id,created_at desc);
create index if not exists causal_evidence_org_created_idx on causal_outcome_evidence(organization_id,created_at desc);
create index if not exists treasury_org_created_idx on capability_treasury_allocations(organization_id,created_at desc);
create index if not exists immune_incidents_org_created_idx on immune_response_incidents(organization_id,created_at desc);
create index if not exists continuity_capsules_user_idx on agent_continuity_capsules(user_id,created_at desc);
alter table constitutional_institutions enable row level security;
alter table institutional_cases enable row level security;
alter table causal_outcome_evidence enable row level security;
alter table capability_treasury_allocations enable row level security;
alter table selective_disclosure_credentials enable row level security;
alter table immune_response_incidents enable row level security;
alter table compiled_organizational_policies enable row level security;
alter table agent_continuity_capsules enable row level security;
alter table adversarial_journey_runs enable row level security;
-- Server endpoints enforce membership, role, proof, and confirmation boundaries.;
