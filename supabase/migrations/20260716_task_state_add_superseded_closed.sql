-- Add SUPERSEDED and CLOSED states for legal-radar v1 deduplication
alter type task_state add value if not exists 'SUPERSEDED';
alter type task_state add value if not exists 'CLOSED';

-- Add reason field to track why a task was transitioned to a terminal state
alter table tasks add column if not exists reason text;
