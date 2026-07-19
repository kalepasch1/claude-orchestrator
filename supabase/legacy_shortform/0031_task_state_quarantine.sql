-- Structural backlog drain states.
-- QUARANTINED parks unsafe/problematic originals after a safe replacement task is queued.
-- DECOMPOSED/SHELVED/MERGING are already used by runner loops and are made schema-explicit here.

alter type task_state add value if not exists 'MERGING';
alter type task_state add value if not exists 'DECOMPOSED';
alter type task_state add value if not exists 'SHELVED';
alter type task_state add value if not exists 'QUARANTINED';
