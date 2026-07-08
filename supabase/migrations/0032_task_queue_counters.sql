-- Canonical full-queue counters for dashboard/autopilot.
-- This prevents newest-row samples from hiding old backlog below the sample window.

create or replace view v_task_queue_counters as
select
  'state'::text as bucket,
  coalesce(state::text, 'UNKNOWN') as name,
  count(*)::bigint as n
from tasks
group by coalesce(state::text, 'UNKNOWN')
union all
select 'total', 'tasks', count(*)::bigint
from tasks
union all
select 'prefix', 'recovery_queued', count(*)::bigint
from tasks
where state::text = 'QUEUED' and slug like 'recover-missing-branch-%'
union all
select 'prefix', 'improvements_queued', count(*)::bigint
from tasks
where state::text = 'QUEUED' and slug like 'improve-%'
union all
select 'prefix', 'canaries_active', count(*)::bigint
from tasks
where state::text in ('QUEUED', 'RUNNING') and slug like 'canary-%'
union all
select 'prefix', 'release_fix_queued', count(*)::bigint
from tasks
where state::text = 'QUEUED'
  and (slug like 'relfix-%' or slug like 'qafix-%' or slug like 'deployfix-%' or slug like 'buildfix-%')
union all
select 'prefix', 'release_fix_running', count(*)::bigint
from tasks
where state::text = 'RUNNING'
  and (slug like 'relfix-%' or slug like 'qafix-%' or slug like 'deployfix-%' or slug like 'buildfix-%');

grant select on v_task_queue_counters to authenticated;
