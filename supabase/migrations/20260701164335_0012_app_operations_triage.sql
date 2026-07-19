-- Ledger of every AI/API operation the underlying apps run THROUGH the shared triage service,
-- so the orchestrator can perpetually review cost+quality and re-route to the cheapest capable
-- provider. This is the cross-app extension of the model triage we use internally.
create table if not exists app_operations (
  id           uuid primary key default gen_random_uuid(),
  app          text not null,               -- which product/app made the call
  operation    text not null,               -- logical operation name (e.g. 'summarize_listing')
  task_class   text,                         -- mechanical|qa|review|rating|plan|build|hard|...
  provider     text,                         -- chosen provider (local|deepseek|google|openai|claude)
  model        text,
  prompt_chars integer,
  cost_usd     numeric default 0,            -- REAL billable $ for this call (0 for free/local/sub)
  latency_ms   integer,
  quality_score numeric,                     -- perpetual bot-review score 0-10 (nullable until reviewed)
  verdict      text,                         -- pass|fail|null
  ok           boolean default true,
  created_at   timestamptz default now()
);
create index if not exists idx_app_ops_app_op on app_operations(app, operation, created_at desc);
create index if not exists idx_app_ops_review on app_operations(created_at desc) where quality_score is null;

-- Per-(app,operation) recommended route, maintained by the review loop (cheapest capable that
-- holds quality). Apps can read this to know which provider/model to use next.
create table if not exists app_op_routes (
  app        text not null,
  operation  text not null,
  provider   text,
  model      text,
  reason     text,
  avg_cost   numeric,
  avg_quality numeric,
  n_samples  integer default 0,
  updated_at timestamptz default now(),
  primary key (app, operation)
);;
