-- auto-drafted action items: the exact command/migration/config to run, pre-generated
alter table approvals add column if not exists draft text;          -- human-readable "what to do", pre-filled
alter table approvals add column if not exists draft_cmd text;      -- the exact one-line command (if safe/runnable)
alter table approvals add column if not exists executable boolean default false; -- safe to "Run for me"?
alter table approvals add column if not exists exec_status text;     -- null|queued|running|done|failed
-- legal pre-brief: plain-English risk summary + precedent
alter table approvals add column if not exists prebrief text;
-- business-model radar early-decision marker
alter table approvals add column if not exists radar_tag text;      -- pricing|data_use|regulatory|null

-- per-app revenue/usage signal for revenue-linked prioritization (you populate; or a connector does)
create table if not exists app_revenue (
  app text primary key,
  mrr_usd numeric default 0,          -- monthly recurring revenue
  active_users integer default 0,
  weight_override numeric,             -- optional manual importance multiplier
  updated_at timestamptz default now()
);

-- queue for one-click operator execution (scoped, guarded)
create table if not exists action_runs (
  id uuid primary key default gen_random_uuid(),
  approval_id uuid,
  cmd text,
  status text default 'queued',        -- queued|running|done|failed
  result text,
  requested_by text,
  created_at timestamptz default now(),
  finished_at timestamptz
);;
