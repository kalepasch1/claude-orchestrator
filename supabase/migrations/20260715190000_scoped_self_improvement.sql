-- Governed, scope-addressable self-improvement for the Madeus orchestrator.
create table if not exists scoped_improvement_loops (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references auth.users(id) on delete cascade,
  project_id uuid references projects(id) on delete cascade,
  scope_type text not null check (scope_type in ('portfolio','application','orchestrator','workflow','code','component')),
  scope_ref text not null,
  label text not null,
  mode text not null default 'shadow' check (mode in ('observe','shadow','bounded_autonomy')),
  target_kpi text not null default 'first_pass_rate',
  status text not null default 'active' check (status in ('active','paused','rolled_back','graduated','retired')),
  allocation_pct numeric not null default 2 check (allocation_pct between 0 and 25),
  rollback_threshold numeric not null default 10 check (rollback_threshold between 1 and 50),
  locked_invariants jsonb not null default '["authority","secrets","privacy","budget","independent_qa"]'::jsonb,
  recommendation jsonb not null default '{}'::jsonb,
  baseline jsonb not null default '{}'::jsonb,
  last_evaluation jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(owner_id, scope_type, scope_ref)
);

create table if not exists hivemind_contributions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references auth.users(id) on delete cascade,
  loop_id uuid references scoped_improvement_loops(id) on delete set null,
  title text not null,
  evidence jsonb not null default '{}'::jsonb,
  reusable_scope text not null default 'private',
  status text not null default 'candidate' check (status in ('candidate','validating','accepted','rejected','revoked')),
  verified_value_usd numeric not null default 0,
  rebate_credits numeric not null default 0,
  privacy_reviewed boolean not null default false,
  created_at timestamptz not null default now(),
  decided_at timestamptz
);

create index if not exists scoped_improvement_status_idx on scoped_improvement_loops(status, scope_type, updated_at desc);
create index if not exists hivemind_contribution_owner_idx on hivemind_contributions(owner_id, status, created_at desc);
alter table scoped_improvement_loops enable row level security;
alter table hivemind_contributions enable row level security;
create policy "owners manage improvement loops" on scoped_improvement_loops for all to authenticated using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy "owners read contributions" on hivemind_contributions for select to authenticated using (owner_id = auth.uid());
create policy "owners propose contributions" on hivemind_contributions for insert to authenticated with check (owner_id = auth.uid());

