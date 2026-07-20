-- First-class lineage, batch ownership, and two-key counsel approvals.
-- Additive/idempotent: mixed-version runners remain safe during rollout.

create table if not exists task_batches (
  id uuid primary key default gen_random_uuid(),
  project_id uuid references projects(id) on delete cascade,
  slug text not null unique,
  title text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table tasks add column if not exists batch_id uuid references task_batches(id) on delete set null;
alter table tasks add column if not exists parent_task_id uuid references tasks(id) on delete set null;
alter table tasks add column if not exists operator_approved_at timestamptz;
alter table tasks add column if not exists operator_approved_by text;
alter table tasks add column if not exists counsel_approved_at timestamptz;
alter table tasks add column if not exists counsel_approved_by text;

create index if not exists tasks_batch_state_idx on tasks(batch_id, state, created_at);
create index if not exists tasks_parent_state_idx on tasks(parent_task_id, state, created_at);
create index if not exists task_batches_project_created_idx on task_batches(project_id, created_at desc);

-- Backfill safe unambiguous existing parent/child relationships. A child can only
-- receive a parent ID when its dependency list contains exactly one DECOMPOSED parent.
with candidates as (
  select child.id as child_id, (array_agg(parent.id order by parent.id))[1] as parent_id, count(*) as parent_count
  from tasks child
  join tasks parent on parent.slug = any(child.deps) and parent.state = 'DECOMPOSED'
  where child.parent_task_id is null
  group by child.id
)
update tasks child
set parent_task_id = candidates.parent_id
from candidates
where child.id = candidates.child_id and candidates.parent_count = 1;

-- Explicit approvals must be paired: timestamps and actors are either both set
-- or both null. This prevents a partial approval from satisfying a gate.
alter table tasks drop constraint if exists tasks_operator_approval_pair;
alter table tasks add constraint tasks_operator_approval_pair
  check ((operator_approved_at is null) = (operator_approved_by is null)) not valid;
alter table tasks validate constraint tasks_operator_approval_pair;
alter table tasks drop constraint if exists tasks_counsel_approval_pair;
alter table tasks add constraint tasks_counsel_approval_pair
  check ((counsel_approved_at is null) = (counsel_approved_by is null)) not valid;
alter table tasks validate constraint tasks_counsel_approval_pair;

alter table task_batches enable row level security;
drop policy if exists task_batches_authenticated_read on task_batches;
create policy task_batches_authenticated_read on task_batches for select to authenticated using (true);

alter publication supabase_realtime add table task_batches;
