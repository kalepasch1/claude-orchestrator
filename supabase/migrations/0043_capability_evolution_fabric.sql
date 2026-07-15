-- Capability evolution fabric: federated trust, causal UI simulation, credential
-- lifecycle, organizational skills, outcome settlement, private learning,
-- accessibility preferences, and synthetic journey evidence.

create table if not exists federated_trust_issuers (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  issuer_slug text not null,
  display_name text not null,
  trust_level text not null default 'verified' check (trust_level in ('observed','verified','privileged')),
  allowed_capabilities text[] not null default '{}',
  status text not null default 'active' check (status in ('active','suspended','revoked')),
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  unique(organization_id,issuer_slug)
);
create table if not exists federated_passport_credentials (
  id uuid primary key default gen_random_uuid(),
  subject_organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  issuer_organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  capabilities text[] not null default '{}',
  claims jsonb not null default '{}',
  signature text not null,
  status text not null default 'active' check (status in ('active','expired','revoked')),
  expires_at timestamptz not null,
  issued_by uuid not null references auth.users(id),
  created_at timestamptz not null default now()
);
create table if not exists interface_twin_simulations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  objective text not null,
  current_contract_version integer not null default 1,
  proposal jsonb not null,
  projected_outcome jsonb not null,
  invariant_routes text[] not null default '{}',
  status text not null default 'simulated' check (status in ('simulated','accepted','rejected','expired')),
  created_at timestamptz not null default now()
);
create table if not exists organizational_skills (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  skill_key text not null,
  label text not null,
  description text not null default '',
  capability_grants text[] not null default '{}',
  evidence_policy jsonb not null default '{}',
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  unique(organization_id,skill_key)
);
create table if not exists member_skill_evidence (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  skill_id uuid not null references organizational_skills(id) on delete cascade,
  level integer not null default 1 check (level between 1 and 5),
  status text not null default 'observed' check (status in ('observed','verified','expired','revoked')),
  evidence jsonb not null default '{}',
  verified_by uuid references auth.users(id),
  verified_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  unique(user_id,skill_id)
);
create table if not exists capability_route_outcomes (
  id uuid primary key default gen_random_uuid(),
  receipt_id uuid not null references capability_route_receipts(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  provider text not null,
  succeeded boolean not null,
  quality numeric not null check (quality between 0 and 1),
  latency_ms integer,
  realized_cost_usd numeric,
  policy_incidents integer not null default 0,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique(receipt_id)
);
create table if not exists private_learning_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  enabled boolean not null default true,
  share_aggregate boolean not null default true,
  retention_days integer not null default 30 check (retention_days between 1 and 365),
  minimum_cohort integer not null default 5 check (minimum_cohort between 3 and 100),
  noise_level numeric not null default 0.1 check (noise_level between 0 and 1),
  updated_at timestamptz not null default now()
);
create table if not exists accessibility_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  density text not null default 'comfortable' check (density in ('compact','comfortable','spacious')),
  explanation_depth text not null default 'balanced' check (explanation_depth in ('concise','balanced','detailed')),
  motion text not null default 'system' check (motion in ('system','reduced','none')),
  contrast text not null default 'system' check (contrast in ('system','high')),
  text_scale numeric not null default 1 check (text_scale between 0.9 and 1.5),
  keyboard_first boolean not null default false,
  updated_at timestamptz not null default now()
);
create table if not exists connector_lifecycle_events (
  id bigint generated always as identity primary key,
  connector_account_id uuid references connector_accounts(id) on delete cascade,
  organization_id uuid references orchestrator_organizations(id) on delete cascade,
  provider text not null,
  event text not null check (event in ('healthy','expiring','refreshed','refresh_failed','rotation_due','revoked')),
  status text not null,
  next_action_at timestamptz,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create table if not exists journey_contract_runs (
  id uuid primary key default gen_random_uuid(),
  contract_version integer not null,
  deployment_url text,
  status text not null check (status in ('passed','failed')),
  checks jsonb not null,
  created_at timestamptz not null default now()
);
create index if not exists route_outcomes_provider_idx on capability_route_outcomes(organization_id,provider,created_at desc);
create index if not exists connector_lifecycle_due_idx on connector_lifecycle_events(next_action_at) where next_action_at is not null;
create index if not exists interface_twin_user_idx on interface_twin_simulations(user_id,created_at desc);
alter table federated_trust_issuers enable row level security;
alter table federated_passport_credentials enable row level security;
alter table interface_twin_simulations enable row level security;
alter table organizational_skills enable row level security;
alter table member_skill_evidence enable row level security;
alter table capability_route_outcomes enable row level security;
alter table private_learning_profiles enable row level security;
alter table accessibility_profiles enable row level security;
alter table connector_lifecycle_events enable row level security;
alter table journey_contract_runs enable row level security;
-- Deliberately server-only. Membership, trust, evidence, and secrets are enforced by APIs.;
