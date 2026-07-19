create table if not exists capabilities (
  id uuid primary key default gen_random_uuid(),
  name text not null, slug text unique not null, domain text,
  summary text, contract jsonb not null default '{}',
  status text not null default 'experimental',   -- experimental|trusted|productizable|retired
  maturity numeric(5,2) not null default 0,
  regulated boolean not null default false,
  created_at timestamptz not null default now()
);
create table if not exists capability_versions (
  id uuid primary key default gen_random_uuid(),
  capability_id uuid references capabilities(id) on delete cascade,
  semver text not null default '0.1.0', spec text,
  eval_pass_rate numeric(4,3), created_at timestamptz not null default now()
);
create table if not exists capability_provenance (
  id uuid primary key default gen_random_uuid(),
  capability_id uuid references capabilities(id) on delete cascade,
  source_project text, derivation text,
  consent boolean not null default false, data_residency text,
  created_at timestamptz not null default now()
);
create table if not exists capability_instances (
  id uuid primary key default gen_random_uuid(),
  capability_id uuid references capabilities(id) on delete cascade,
  version text, project text, status text not null default 'active',
  created_at timestamptz not null default now()
);
create table if not exists capability_evals (
  id uuid primary key default gen_random_uuid(),
  capability_id uuid references capabilities(id) on delete cascade,
  name text, input jsonb, expected text, last_pass boolean,
  created_at timestamptz not null default now()
);
alter table capabilities enable row level security;
alter table capability_versions enable row level security;
alter table capability_provenance enable row level security;
alter table capability_instances enable row level security;
alter table capability_evals enable row level security;
do $$ declare t text; begin
  foreach t in array array['capabilities','capability_versions','capability_provenance','capability_instances','capability_evals'] loop
    execute format('drop policy if exists %I_read on %I;', t, t);
    execute format('create policy %I_read on %I for select to authenticated using (true);', t, t);
  end loop;
end $$;
alter publication supabase_realtime add table capabilities;;
