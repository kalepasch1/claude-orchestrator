-- legal triage: risk level so routine 'legal-flavored' cards can auto-clear, novel ones escalate
alter table approvals add column if not exists legal_risk_level text;  -- routine|elevated|novel
-- auto-exec track record marker
alter table approvals add column if not exists auto_exec_ok boolean default false;

-- revenue attribution: link a merged change to observed revenue/usage movement
create table if not exists merge_revenue (
  id uuid primary key default gen_random_uuid(),
  project text, slug text, kind text,
  mrr_before numeric, mrr_after numeric, users_before integer, users_after integer,
  revenue_delta numeric, window_days integer default 7,
  created_at timestamptz default now()
);

-- snapshot of app_revenue over time so attribution has a before/after
create table if not exists app_revenue_history (
  app text, mrr_usd numeric, active_users integer, captured_at timestamptz default now()
);
create index if not exists idx_arh_app on app_revenue_history(app, captured_at desc);;
