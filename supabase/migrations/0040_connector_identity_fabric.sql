-- Unified connector identity fabric. Raw credentials are never readable through RLS.
create table if not exists connector_accounts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null,
  kind text not null,
  label text,
  status text not null default 'connected' check (status in ('connected','expired','revoked','error')),
  scopes text[] not null default '{}',
  token_audience text,
  access_token_ciphertext text,
  refresh_token_ciphertext text,
  expires_at timestamptz,
  metadata jsonb not null default '{}',
  last_used_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id, provider, label)
);

create table if not exists connector_oauth_states (
  state_hash text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null,
  verifier_ciphertext text not null,
  redirect_uri text not null,
  requested_scopes text[] not null default '{}',
  resource text,
  expires_at timestamptz not null,
  consumed_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists connector_mcp_servers (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  server_url text not null,
  canonical_resource text not null,
  authorization_server text,
  status text not null default 'discovered',
  tool_count integer,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique(user_id, canonical_resource)
);

create table if not exists connector_audit_log (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  connector_account_id uuid references connector_accounts(id) on delete set null,
  provider text not null,
  event text not null,
  scopes text[] not null default '{}',
  audience text,
  outcome text not null,
  request_id text,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create index if not exists connector_accounts_user_idx on connector_accounts(user_id, status);
create index if not exists connector_oauth_states_expiry_idx on connector_oauth_states(expires_at);
create index if not exists connector_audit_user_idx on connector_audit_log(user_id, created_at desc);

alter table connector_accounts enable row level security;
alter table connector_oauth_states enable row level security;
alter table connector_mcp_servers enable row level security;
alter table connector_audit_log enable row level security;
-- Intentionally no browser policies: all access flows through authenticated server endpoints.

create or replace function expire_connector_oauth_states() returns integer language plpgsql security definer as $$
declare n integer;
begin
  delete from connector_oauth_states where expires_at < now() or consumed_at < now() - interval '1 hour';
  get diagnostics n = row_count;
  return n;
end $$;
