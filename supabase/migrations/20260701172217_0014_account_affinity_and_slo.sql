-- account machine-affinity (for later: pin a Claude login to a specific Mac to avoid contention)
alter table accounts add column if not exists machine text;   -- null = usable by any machine

-- per-app cost SLO: target $/merge the closed loop holds automatically
create table if not exists cost_slos (
  app        text primary key,
  target_usd_per_merge numeric not null default 1.0,
  hard_ceiling_usd_per_merge numeric,     -- optional: breach => escalate/pause
  updated_at timestamptz default now()
);

-- productization proposals from proven capabilities
create table if not exists capability_products (
  id uuid primary key default gen_random_uuid(),
  capability_slug text not null,
  status text default 'proposed',          -- proposed|approved|scaffolded|live
  eval_pass_rate numeric,
  rationale text,
  created_at timestamptz default now()
);;
