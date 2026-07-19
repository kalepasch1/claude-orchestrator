-- secrets: store ONLY references to a real secret store (keychain/Vault/Doppler/env), never values
create table if not exists secrets (
  id uuid primary key default gen_random_uuid(),
  project text, provider text not null, name text not null,
  ref text not null,                       -- pointer into the secret store, NOT the secret
  store text not null default 'env',       -- env|keychain|supabase_vault|doppler|onepassword
  scope text default 'runner', status text not null default 'active',  -- active|rotating|revoked
  last_rotated timestamptz, created_at timestamptz not null default now(),
  unique (provider, name, project)
);
-- kill switch: global / per-project pause
create table if not exists controls (
  id uuid primary key default gen_random_uuid(),
  scope text not null default 'global',    -- global|project
  project text, paused boolean not null default false,
  reason text, updated_by text, updated_at timestamptz not null default now(),
  unique (scope, project)
);
-- external (non-Claude) provider usage + budgets, for the per-project spend view
create table if not exists provider_usage (
  id bigint generated always as identity primary key,
  provider text not null, project text, units numeric, unit text,
  usd numeric(12,4) default 0, created_at timestamptz not null default now()
);
create index if not exists provider_usage_idx on provider_usage(provider, project);
create table if not exists provider_budgets (
  id uuid primary key default gen_random_uuid(),
  provider text not null, project text,
  monthly_cap numeric(12,2) not null default 100, hard_pause boolean not null default true,
  unique (provider, project)
);
-- credential onboarding requests (the only thing that prompts the human, esp. for payment)
create table if not exists credential_requests (
  id uuid primary key default gen_random_uuid(),
  project text, provider text not null, reason text,
  status text not null default 'needed',   -- needed|payment_required|manual|provisioned
  created_at timestamptz not null default now()
);
-- spend by provider+project this month
create or replace view v_provider_spend_mtd as
  select provider, project, coalesce(sum(usd),0)::numeric(12,2) as spent
  from provider_usage where created_at >= date_trunc('month', now())
  group by provider, project;

alter table secrets enable row level security;     -- service-role only (no policies = locked)
alter table controls enable row level security;
alter table provider_usage enable row level security;
alter table provider_budgets enable row level security;
alter table credential_requests enable row level security;
do $$ declare t text; begin
  foreach t in array array['controls','provider_usage','provider_budgets','credential_requests'] loop
    execute format('drop policy if exists %I_read on %I;', t, t);
    execute format('create policy %I_read on %I for select to authenticated using (true);', t, t);
  end loop;
  -- members can flip the kill switch from the dashboard
  execute 'drop policy if exists controls_write on controls';
  execute 'create policy controls_write on controls for all to authenticated using (true) with check (true)';
end $$;
alter publication supabase_realtime add table controls;
alter publication supabase_realtime add table credential_requests;;
