-- Immutable task/rebase identities. Additive and safe for mixed-version runners.
alter table tasks add column if not exists artifact_ref text;
create table if not exists task_artifacts (
  slug text primary key, branch text, commit_sha text, patch_diff text,
  diff_bytes integer, touched_files jsonb, test_log text, cost_usd numeric,
  captured_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
alter table task_artifacts add column if not exists artifact_ref text;
alter table task_artifacts add column if not exists patch_id text;
create index if not exists tasks_artifact_ref_idx on tasks(artifact_ref) where artifact_ref is not null;
create index if not exists task_artifacts_patch_id_idx on task_artifacts(patch_id) where patch_id is not null;
