-- Make EV-per-token scheduling first-class instead of advisory.
-- Lower priority values are claimed first; ev_scheduler writes 1..50 for the current top queue.
alter table tasks add column if not exists priority int not null default 1000;
create index if not exists tasks_state_priority_idx on tasks(state, priority, created_at);
