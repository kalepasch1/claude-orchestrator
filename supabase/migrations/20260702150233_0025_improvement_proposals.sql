create table if not exists improvement_proposals (
  id uuid primary key default gen_random_uuid(),
  app text, surface text,                 -- feature|product|api|backend|frontend|ux|function|growth|...
  title text, current_state text, proposal text,
  expected_multiplier text,               -- '20x' | '100x' | '500x' ...
  divergent boolean default false,        -- would it change the business model?
  rationale text,                         -- why it's high-leverage (the presentation body)
  status text default 'proposed',         -- proposed|queued|for_review|approved|rejected|shipped
  task_slug text,                         -- if auto-queued
  score numeric,                          -- impact x feasibility rank
  created_at timestamptz default now()
);
create index if not exists idx_improv_status on improvement_proposals(status, created_at desc);
create index if not exists idx_improv_app on improvement_proposals(app, surface);;
