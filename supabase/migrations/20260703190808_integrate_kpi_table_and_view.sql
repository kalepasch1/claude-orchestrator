
create table if not exists integrate_kpi (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  overall_merge_rate numeric,
  completed int,
  integrated int,
  coder_switched int,
  build_fail_open int,
  by_project jsonb
);
alter table integrate_kpi enable row level security;
-- read-only view Mission Control can select without exposing writes
create or replace view v_integrate_kpi as
  select created_at, overall_merge_rate, completed, integrated, coder_switched, build_fail_open, by_project
  from integrate_kpi order by created_at desc limit 1;
;
