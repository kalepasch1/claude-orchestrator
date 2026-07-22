-- 0027_tasks_pinned.sql
-- First-class task priority pin: pinned tasks sort before the fairness round-robin.
-- Idempotent (ALTER TABLE ... ADD COLUMN IF NOT EXISTS).

alter table tasks add column if not exists pinned   boolean not null default false;
alter table tasks add column if not exists pin_rank int     not null default 0;

comment on column tasks.pinned   is 'When true, task is claimed before the normal fairness round-robin.';
comment on column tasks.pin_rank is 'Lower value = higher priority among pinned tasks (0 = unset/lowest).';

-- Index for fast pinned-first scans.
create index if not exists tasks_pinned_idx on tasks(pinned, pin_rank) where state = 'QUEUED';
