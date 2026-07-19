-- the single objective the whole system optimizes toward, + its measured value over time
create table if not exists north_star (
  id uuid primary key default gen_random_uuid(),
  metric text not null default 'value_per_compute_dollar',  -- name of the objective
  value numeric,                                            -- measured objective at this tick
  detail jsonb,                                             -- the components (merges, revenue, cost...)
  created_at timestamptz default now()
);
-- every self-tuning change the optimizer makes, so it can measure impact + revert regressions
create table if not exists tuning_log (
  id uuid primary key default gen_random_uuid(),
  knob text, old_value text, new_value text,
  objective_before numeric, objective_after numeric,
  kept boolean, reason text, created_at timestamptz default now()
);
-- current objective config (target + which knobs it may tune)
create table if not exists objective_config (
  id int primary key default 1,
  metric text default 'value_per_compute_dollar',
  direction text default 'maximize',
  updated_at timestamptz default now()
);
insert into objective_config (id, metric) values (1,'value_per_compute_dollar') on conflict (id) do nothing;;
