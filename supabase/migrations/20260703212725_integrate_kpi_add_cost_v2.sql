
alter table if exists integrate_kpi add column if not exists usd numeric;
alter table if exists integrate_kpi add column if not exists usd_per_merge numeric;
drop view if exists v_integrate_kpi;
create view v_integrate_kpi as
  select created_at, overall_merge_rate, completed, integrated, usd, usd_per_merge,
         coder_switched, build_fail_open, by_project
  from integrate_kpi order by created_at desc limit 1;
;
