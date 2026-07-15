
create table if not exists darwin_identities (
  subject text primary key,
  local_ids jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create table if not exists darwin_consent_grants (
  id uuid primary key default gen_random_uuid(),
  subject text not null references darwin_identities(subject) on delete cascade,
  from_product text not null, to_product text not null,
  scopes text[] not null default '{}', granted_at timestamptz not null default now(),
  expires_at timestamptz, revoked boolean not null default false
);
create index if not exists darwin_consent_subject_idx on darwin_consent_grants (subject);
create table if not exists darwin_passports (
  id text primary key, subject text not null, claims jsonb not null,
  issued_at timestamptz not null, digest text not null, signature jsonb not null
);
create index if not exists darwin_passports_subject_idx on darwin_passports (subject);
create table if not exists darwin_receipts (
  id text primary key, chain text not null, seq integer not null, prev_hash text,
  product text not null, action_type text not null, actor text not null, subject_id text,
  decision text not null, rule_id text, reason text not null, at timestamptz not null,
  digest text not null, signature jsonb not null, unique (chain, seq)
);
create index if not exists darwin_receipts_chain_idx on darwin_receipts (chain, seq);
create index if not exists darwin_receipts_product_idx on darwin_receipts (product, at desc);
create table if not exists darwin_capabilities (
  id text primary key, owner text not null, name text not null, version text not null,
  spec jsonb not null, created_at timestamptz not null default now()
);
create index if not exists darwin_capabilities_owner_idx on darwin_capabilities (owner);
create table if not exists darwin_tasks (
  id text primary key, product text not null, goal text not null,
  input jsonb not null default '{}'::jsonb, state text not null default 'queued',
  depends_on text[] not null default '{}', requires_approval boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists darwin_tasks_state_idx on darwin_tasks (state);
create table if not exists darwin_approvals (
  task_id text primary key references darwin_tasks(id) on delete cascade,
  why text not null, value text not null, risk text not null,
  alternatives text[] not null default '{}', decision text not null default 'pending'
);
create table if not exists darwin_federated_shares (
  id uuid primary key default gen_random_uuid(), metric text not null, from_product text not null,
  cohort_size integer not null, value double precision, epsilon double precision not null,
  created_at timestamptz not null default now()
);
create table if not exists darwin_usage_records (
  id text primary key, capability_id text not null, caller text not null, owner text not null,
  latency_ms integer not null, units double precision not null, amount_cents integer not null,
  at timestamptz not null, digest text not null, signature jsonb not null
);
create index if not exists darwin_usage_owner_idx on darwin_usage_records (owner, caller, at desc);
create table if not exists darwin_attestations (
  id text primary key, kind text not null, issuer text not null, about text not null,
  payload jsonb not null, issued_at timestamptz not null, expires_at timestamptz not null,
  digest text not null, signature jsonb not null
);
create index if not exists darwin_attestations_about_idx on darwin_attestations (about, kind);
create table if not exists darwin_reward_ledger (
  id uuid primary key default gen_random_uuid(), subject text not null, currency text not null,
  amount double precision not null, reason text not null, created_at timestamptz not null default now()
);
create index if not exists darwin_reward_subject_idx on darwin_reward_ledger (subject);
create table if not exists darwin_identity_edges (
  id uuid primary key default gen_random_uuid(), from_subject text not null, to_subject text not null,
  kind text not null, created_at timestamptz not null default now(),
  unique (from_subject, to_subject, kind)
);
create index if not exists darwin_edges_from_idx on darwin_identity_edges (from_subject);
alter table darwin_identities enable row level security;
alter table darwin_consent_grants enable row level security;
alter table darwin_passports enable row level security;
alter table darwin_receipts enable row level security;
alter table darwin_capabilities enable row level security;
alter table darwin_tasks enable row level security;
alter table darwin_approvals enable row level security;
alter table darwin_federated_shares enable row level security;
alter table darwin_usage_records enable row level security;
alter table darwin_attestations enable row level security;
alter table darwin_reward_ledger enable row level security;
alter table darwin_identity_edges enable row level security;
;
