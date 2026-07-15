-- Organizational capability passports, delegated connector administration, adaptive learning,
-- replayable onboarding, and explainable route receipts. Server-only RLS by design.
create table if not exists orchestrator_organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now()
);

create table if not exists orchestrator_org_memberships (
  organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'member' check (role in ('owner','admin','operator','reviewer','engineer','analyst','member')),
  status text not null default 'active' check (status in ('invited','active','suspended')),
  joined_at timestamptz not null default now(),
  primary key (organization_id,user_id)
);

create table if not exists orchestrator_capability_passports (
  organization_id uuid primary key references orchestrator_organizations(id) on delete cascade,
  permissions text[] not null default '{}',
  connector_allowlist text[] not null default '{}',
  policies jsonb not null default '{}',
  training_path jsonb not null default '[{"id":"command-center","label":"Understand portfolio state","route":"/"},{"id":"connections","label":"Understand available capabilities","route":"/connectors"},{"id":"digital-twin","label":"Simulate a change safely","route":"/digital-twin"}]',
  default_objective text not null default 'operate',
  version integer not null default 1,
  updated_by uuid references auth.users(id),
  updated_at timestamptz not null default now()
);

create table if not exists connector_provider_configs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references orchestrator_organizations(id) on delete cascade,
  provider text not null,
  client_id text not null,
  client_secret_ciphertext text,
  enabled boolean not null default true,
  metadata jsonb not null default '{}',
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(organization_id,provider)
);

create table if not exists interface_learning_events (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  organization_id uuid references orchestrator_organizations(id) on delete cascade,
  event text not null check (event in ('page_view','action_started','action_completed','guidance_followed','guidance_dismissed')),
  route text,
  objective text,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists onboarding_progress (
  user_id uuid not null references auth.users(id) on delete cascade,
  organization_id uuid references orchestrator_organizations(id) on delete cascade,
  step_id text not null,
  status text not null default 'available' check (status in ('available','started','completed','replayed')),
  evidence jsonb not null default '{}',
  first_completed_at timestamptz,
  last_replayed_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key(user_id,step_id)
);

create table if not exists capability_route_receipts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  organization_id uuid references orchestrator_organizations(id) on delete cascade,
  intent text not null,
  capability text not null,
  selected_provider text,
  selected_account_id uuid references connector_accounts(id) on delete set null,
  explanation jsonb not null,
  alternatives jsonb not null default '[]',
  estimated_cost_usd numeric,
  created_at timestamptz not null default now()
);

create index if not exists interface_learning_user_created_idx on interface_learning_events(user_id,created_at desc);
create index if not exists capability_route_user_created_idx on capability_route_receipts(user_id,created_at desc);

alter table orchestrator_organizations enable row level security;
alter table orchestrator_org_memberships enable row level security;
alter table orchestrator_capability_passports enable row level security;
alter table connector_provider_configs enable row level security;
alter table interface_learning_events enable row level security;
alter table onboarding_progress enable row level security;
alter table capability_route_receipts enable row level security;
-- No browser policies: authenticated server endpoints enforce membership and never return secrets.
