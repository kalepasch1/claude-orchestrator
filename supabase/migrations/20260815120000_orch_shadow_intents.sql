-- Shadow mode's audit trail: every shared-ref write the orchestrator WOULD have made while
-- ORCH_SHADOW_MODE=true, so its proposals can be read back and compared against whatever the
-- manual process actually did. The point of shadow mode is evidence, and evidence that lives
-- only in a log file on one machine is not evidence anyone will go and read.
create table if not exists orch_shadow_intents (
  id          bigserial primary key,
  action      text not null,
  project     text,
  subject     text,
  detail      text,
  host        text default null,
  created_at  timestamptz not null default now()
);
create index if not exists orch_shadow_intents_created_idx on orch_shadow_intents (created_at desc);
create index if not exists orch_shadow_intents_project_idx on orch_shadow_intents (project, created_at desc);
alter table orch_shadow_intents enable row level security;
drop policy if exists orch_shadow_intents_read on orch_shadow_intents;
create policy orch_shadow_intents_read on orch_shadow_intents
  for select to authenticated using (true);
