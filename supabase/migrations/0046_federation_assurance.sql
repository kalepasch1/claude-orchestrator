-- Federation and assurance: sovereign trust, causal twin learning, execution
-- attestations, attenuated delegation, outcome markets, compiled memory,
-- anticipatory inclusion, and constitutional red-team review.

create table if not exists sovereign_federation_trusts (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  counterparty_did text not null, trust_domains text[] not null default '{}', disclosure_policy jsonb not null,
  reciprocity_terms jsonb not null, trust_digest text not null, status text not null default 'proposed' check (status in ('proposed','active','paused','revoked')),
  created_by uuid not null references auth.users(id), created_at timestamptz not null default now(), unique(organization_id,counterparty_did)
);
create table if not exists federated_evidence_exchanges (
  id uuid primary key default gen_random_uuid(), trust_id uuid not null references sovereign_federation_trusts(id) on delete cascade,
  organization_id uuid not null references orchestrator_organizations(id) on delete cascade, evidence_id uuid references causal_outcome_evidence(id) on delete set null,
  disclosed_claims jsonb not null, withheld_fields text[] not null default '{}', exchange_digest text not null,
  status text not null default 'prepared' check (status in ('prepared','approved','delivered','withdrawn')), created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists causal_twin_updates (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  world_snapshot_id uuid references organizational_world_snapshots(id) on delete set null, evidence_ids uuid[] not null default '{}',
  hypotheses jsonb not null, causal_graph jsonb not null, confidence_updates jsonb not null, recommended_experiments jsonb not null,
  model_digest text not null, created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists execution_supply_chain_attestations (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  proof_envelope_id uuid references execution_proof_envelopes(id) on delete set null, release_snapshot_id uuid references release_state_snapshots(id) on delete set null,
  materials jsonb not null, subjects jsonb not null, policy_verdict jsonb not null, attestation_digest text not null,
  status text not null default 'verified' check (status in ('verified','incomplete','revoked')), created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists delegation_graph_edges (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  delegator_user_id uuid not null references auth.users(id) on delete cascade, delegate_subject text not null, parent_edge_id uuid references delegation_graph_edges(id) on delete cascade,
  scopes text[] not null, purpose text not null, constraints jsonb not null, depth integer not null default 0 check (depth between 0 and 8),
  status text not null default 'active' check (status in ('active','expired','revoked','exhausted')), expires_at timestamptz not null,
  created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists outcome_market_contracts (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  capability text not null, provider_subject text not null, outcome_definition jsonb not null, verification_policy jsonb not null,
  consideration jsonb not null, warranty_id uuid references outcome_warranties(id) on delete set null,
  status text not null default 'proposed' check (status in ('proposed','approved','active','verified','settled','disputed','cancelled')),
  created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists organizational_memory_artifacts (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  title text not null, source_refs jsonb not null, memory_graph jsonb not null, compiled_guidance jsonb not null,
  target_surfaces text[] not null default '{}', version integer not null default 1, artifact_digest text not null,
  status text not null default 'draft' check (status in ('draft','reviewed','active','superseded')), created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists inclusion_risk_assessments (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  proposed_change text not null, profiles jsonb not null, predicted_barriers jsonb not null, mitigations jsonb not null,
  overall_risk text not null check (overall_risk in ('low','medium','high','critical')), decision text not null check (decision in ('allow','mitigate','escalate')),
  assessment_digest text not null, created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create table if not exists constitutional_red_team_cases (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  subject_type text not null, subject_id text, proposition text not null, adversarial_panels jsonb not null,
  findings jsonb not null, conflicts jsonb not null, verdict text not null check (verdict in ('clear','conditions_required','escalate','reject')),
  appeal_path jsonb not null, proof_envelope_id uuid references execution_proof_envelopes(id) on delete set null,
  status text not null default 'reviewed' check (status in ('opened','reviewed','appealed','closed')), created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create index if not exists federation_trust_org_idx on sovereign_federation_trusts(organization_id,created_at desc);
create index if not exists causal_twin_org_idx on causal_twin_updates(organization_id,created_at desc);
create index if not exists supply_chain_org_idx on execution_supply_chain_attestations(organization_id,created_at desc);
create index if not exists delegation_active_idx on delegation_graph_edges(organization_id,expires_at) where status='active';
create index if not exists outcome_market_org_idx on outcome_market_contracts(organization_id,created_at desc);
create index if not exists memory_org_idx on organizational_memory_artifacts(organization_id,created_at desc);
create index if not exists inclusion_org_idx on inclusion_risk_assessments(organization_id,created_at desc);
create index if not exists red_team_org_idx on constitutional_red_team_cases(organization_id,created_at desc);
alter table sovereign_federation_trusts enable row level security;
alter table federated_evidence_exchanges enable row level security;
alter table causal_twin_updates enable row level security;
alter table execution_supply_chain_attestations enable row level security;
alter table delegation_graph_edges enable row level security;
alter table outcome_market_contracts enable row level security;
alter table organizational_memory_artifacts enable row level security;
alter table inclusion_risk_assessments enable row level security;
alter table constitutional_red_team_cases enable row level security;
-- Server endpoints enforce organization membership, administration, attenuation,
-- explicit disclosure approval, and proof-carrying execution.;
