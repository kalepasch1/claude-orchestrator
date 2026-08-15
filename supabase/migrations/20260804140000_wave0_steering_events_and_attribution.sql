-- Wave-0 review gate (PROMPT-beethoven-review-gate-and-steering items 2+4):
-- attributed steering_events substrate + task submitter attribution.
-- Applied to eatfwdzfurujcuwlhdgj via MCP 2026-08-04.

create table if not exists public.steering_events (
  id uuid primary key default gen_random_uuid(),
  task_id uuid null references public.tasks(id) on delete set null,
  approval_id uuid null references public.approvals(id) on delete set null,
  project text null,
  actor_id uuid null,
  actor_label text null,
  event_type text not null check (event_type in (
    'clarification_answer','redirect','approval_rationale',
    'fleet_control','kill_switch','release_decision')),
  rationale text null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_steering_events_task on public.steering_events(task_id) where task_id is not null;
create index if not exists idx_steering_events_approval on public.steering_events(approval_id) where approval_id is not null;
create index if not exists idx_steering_events_project_created on public.steering_events(project, created_at desc);

-- Tight RLS: operators (authenticated) read steering history; only the service
-- role writes (runner + Nitro server endpoints both use the service key).
alter table public.steering_events enable row level security;
drop policy if exists steering_events_auth_read on public.steering_events;
create policy steering_events_auth_read on public.steering_events
  for select to authenticated using (true);

-- Attribution on tasks (spec item 4): who submitted the objective.
alter table public.tasks add column if not exists submitted_by uuid null references auth.users(id) on delete set null;
alter table public.tasks add column if not exists submitted_by_label text null;
