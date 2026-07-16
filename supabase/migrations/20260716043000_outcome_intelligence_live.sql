create table if not exists public.outcome_shadow_experiments (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade, app text not null, capability text not null,
  objective text not null, proposal jsonb not null default '{}'::jsonb, projected_outcome jsonb not null default '{}'::jsonb,
  status text not null default 'shadow' check (status in ('shadow','eligible','promoted','rejected')), promoted_at timestamptz,
  created_at timestamptz not null default now()
);
create table if not exists public.outcome_drift_snapshots (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade, app text not null, capability text not null,
  sources jsonb not null default '[]'::jsonb, findings jsonb not null default '[]'::jsonb, status text not null default 'queued', created_at timestamptz not null default now()
);
create table if not exists public.proof_share_links (
  id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  proof_id uuid not null references public.execution_proof_envelopes(id) on delete cascade, token_hash text not null unique,
  audience text not null, scopes jsonb not null default '["proof:read"]'::jsonb, expires_at timestamptz not null,
  revoked_at timestamptz, created_by uuid not null references auth.users(id), created_at timestamptz not null default now()
);
create index if not exists outcome_shadow_org_idx on public.outcome_shadow_experiments(organization_id,created_at desc);
create index if not exists outcome_drift_org_idx on public.outcome_drift_snapshots(organization_id,created_at desc);
alter table public.outcome_shadow_experiments enable row level security;
alter table public.outcome_drift_snapshots enable row level security;
alter table public.proof_share_links enable row level security;
drop policy if exists "outcome shadow organization read" on public.outcome_shadow_experiments;
drop policy if exists "outcome drift organization read" on public.outcome_drift_snapshots;
drop policy if exists "proof links organization read" on public.proof_share_links;
create policy "outcome shadow organization read" on public.outcome_shadow_experiments for select using (exists(select 1 from public.orchestrator_org_memberships m where m.organization_id=outcome_shadow_experiments.organization_id and m.user_id=auth.uid() and m.status='active'));
create policy "outcome drift organization read" on public.outcome_drift_snapshots for select using (exists(select 1 from public.orchestrator_org_memberships m where m.organization_id=outcome_drift_snapshots.organization_id and m.user_id=auth.uid() and m.status='active'));
create policy "proof links organization read" on public.proof_share_links for select using (exists(select 1 from public.orchestrator_org_memberships m where m.organization_id=proof_share_links.organization_id and m.user_id=auth.uid() and m.status='active'));
