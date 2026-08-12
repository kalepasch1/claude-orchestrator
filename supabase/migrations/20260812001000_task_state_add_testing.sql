-- Immediate enqueue-to-test handoff. Safe and idempotent across rolling hosts.
alter type task_state add value if not exists 'TESTING';
