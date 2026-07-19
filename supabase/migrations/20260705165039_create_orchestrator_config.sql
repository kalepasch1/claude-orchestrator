create table if not exists public.orchestrator_config (
  key text primary key,
  value jsonb not null,
  note text,
  updated_by text,
  updated_at timestamptz default now()
);;
