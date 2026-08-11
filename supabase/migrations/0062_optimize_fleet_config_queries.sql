-- 0062_optimize_fleet_config_queries.sql
-- Add database indexes for optimized fleet-wide configuration operations (20x improvement target)
-- Focus: high-frequency queries in fleet_control.load_config(), db.claim_task(), and queue admission

-- Fleet configuration: load_config() queries all rows frequently
-- No index needed for table scan, but ensure efficient updated_at ordering if selective queries added
create index if not exists fleet_config_updated_at_idx on fleet_config(updated_at desc)
  where updated_at > now() - interval '24 hours';

-- Task state queries: the highest-volume queries in claim_task() and _queue_depth_block()
-- Primary: (state, created_at) for oldest-first scans of QUEUED tasks
create index if not exists tasks_state_created_idx on tasks(state, created_at asc)
  where state in ('QUEUED', 'RUNNING', 'RETRY', 'DONE', 'MERGED');

-- Secondary: (state, project_id) for project-scoped task filtering
create index if not exists tasks_state_project_idx on tasks(state, project_id)
  where state in ('QUEUED', 'RUNNING', 'RETRY');

-- Tertiary: (state, updated_at) for fair round-robin by last activity per project
create index if not exists tasks_state_updated_idx on tasks(state, updated_at desc)
  where state in ('RUNNING', 'DONE', 'MERGED');

-- Helper: slug lookups for idempotent insert dedup (already have state filtering, add project)
create index if not exists tasks_project_slug_state_idx on tasks(project_id, slug, state)
  where state in ('QUEUED', 'RUNNING', 'RETRY', 'DONE', 'MERGED', 'BLOCKED');

-- Controls: global/project-scoped pause queries in kill_switch and claim_task filtering
create index if not exists controls_scope_project_idx on controls(scope, project, paused)
  where paused = true;

-- Fleet control: open actions that process_controls() must repeatedly query
create index if not exists fleet_control_open_target_idx on fleet_control(target, done, requested_at)
  where done = false;

-- Projects: project list queries are rare but critical to claim_task performance
-- Already has UNIQUE(name), this adds secondary queries by id and priority
create index if not exists projects_priority_idx on projects(priority, name);

-- Runner heartbeats: live runner detection in claim_task() and fleet status queries
create index if not exists runner_heartbeats_hostname_seen_idx on runner_heartbeats(hostname, last_seen desc);

-- Approval table: admission_rejections logging for admission control visibility
create table if not exists admission_rejections (
  id bigint generated always as identity primary key,
  slug text not null,
  project_id uuid references projects(id) on delete set null,
  gate text not null,  -- queue_depth | release_backpressure | prompt_gate
  reason text,
  operator_origin boolean not null default false,
  submitted_by text,
  created_at timestamptz not null default now()
);
create index if not exists admission_rejections_gate_idx on admission_rejections(gate, created_at desc);
create index if not exists admission_rejections_operator_idx on admission_rejections(operator_origin, created_at desc);
create index if not exists admission_rejections_project_idx on admission_rejections(project_id, gate);
