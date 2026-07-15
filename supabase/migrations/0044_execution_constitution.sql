-- Execution constitution: proof-carrying actions, organizational world snapshots,
-- capability exchange, temporary least-privilege grants, collective intent,
-- outcome warranties, universal commands, accessibility certification, and replay.

create table if not exists execution_proof_envelopes (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade, action_type text not null, intent text not null,
  status text not null default 'planned' check (status in ('planned','approved','executed','verified','failed','rolled_back')),
  prediction jsonb not null default '{}', permissions jsonb not null default '{}', proof jsonb not null default '{}',
  rollback_plan jsonb not null default '{}', realized_outcome jsonb, proof_digest text not null, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);

create table if not exists organizational_world_snapshots (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  created_by uuid not null references auth.users(id), label text not null, model_version integer not null default 1,
  entities jsonb not null, dependencies jsonb not null, metrics jsonb not null, causal_assumptions jsonb not null default '[]', created_at timestamptz not null default now()
);

create table if not exists capability_market_offers (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  kind text not null check (kind in ('skill','workflow','capacity','policy','connector','precedent_pack')), title text not null,
  description text not null default '', capabilities text[] not null default '{}', terms jsonb not null default '{}',
  signed_listing jsonb not null, status text not null default 'active' check (status in ('draft','active','paused','retired')),
  created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);

create table if not exists capability_market_settlements (
  id uuid primary key default gen_random_uuid(), offer_id uuid not null references capability_market_offers(id) on delete cascade,
  buyer_organization_id uuid not null references orchestrator_organizations(id) on delete cascade, installed_by uuid not null references auth.users(id),
  status text not null default 'installed' check (status in ('installed','accepted','disputed','refunded')), outcome jsonb not null default '{}', created_at timestamptz not null default now()
);

create table if not exists temporary_scope_grants (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade, connector_account_id uuid references connector_accounts(id) on delete cascade,
  purpose text not null, scopes text[] not null, status text not null default 'active' check (status in ('active','used','expired','revoked')),
  expires_at timestamptz not null, created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);

create table if not exists collective_intent_sessions (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  created_by uuid not null references auth.users(id), objective text not null, stakeholder_positions jsonb not null default '[]',
  synthesized_plan jsonb, conflicts jsonb not null default '[]', decision text check (decision in ('allow','escalate','deny')),
  status text not null default 'draft' check (status in ('draft','synthesized','approved','rejected','executed')), created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);

create table if not exists outcome_warranties (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  route_receipt_id uuid references capability_route_receipts(id) on delete set null, provider text not null,
  commitments jsonb not null, remedies jsonb not null, status text not null default 'active' check (status in ('active','satisfied','breached','remediated','expired')),
  expires_at timestamptz, created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);

create table if not exists universal_command_receipts (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade, command text not null, resolved_capability text,
  destination text, proof_envelope_id uuid references execution_proof_envelopes(id) on delete set null,
  status text not null default 'planned' check (status in ('planned','navigated','executed','blocked')), explanation jsonb not null default '{}', created_at timestamptz not null default now()
);

create table if not exists accessibility_certification_runs (
  id uuid primary key default gen_random_uuid(), organization_id uuid references orchestrator_organizations(id) on delete cascade,
  contract_version integer not null, deployment_url text, status text not null check (status in ('passed','failed')),
  profiles jsonb not null, checks jsonb not null, failures jsonb not null default '[]', created_by uuid references auth.users(id), created_at timestamptz not null default now()
);

create table if not exists release_state_snapshots (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  created_by uuid not null references auth.users(id), label text not null, deployment_id text, navigation_contract_version integer not null,
  state jsonb not null, state_digest text not null, parent_snapshot_id uuid references release_state_snapshots(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists proof_envelopes_org_created_idx on execution_proof_envelopes(organization_id,created_at desc);
create index if not exists temporary_scope_active_idx on temporary_scope_grants(user_id,expires_at) where status='active';
create index if not exists release_snapshots_org_created_idx on release_state_snapshots(organization_id,created_at desc);

alter table execution_proof_envelopes enable row level security;
alter table organizational_world_snapshots enable row level security;
alter table capability_market_offers enable row level security;
alter table capability_market_settlements enable row level security;
alter table temporary_scope_grants enable row level security;
alter table collective_intent_sessions enable row level security;
alter table outcome_warranties enable row level security;
alter table universal_command_receipts enable row level security;
alter table accessibility_certification_runs enable row level security;
alter table release_state_snapshots enable row level security;
-- No browser policies. Server endpoints enforce organization membership and administration.
