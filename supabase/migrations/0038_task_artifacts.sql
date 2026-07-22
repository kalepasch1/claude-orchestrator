-- 0038_task_artifacts.sql — add the task_artifacts table.
--
-- runner/task_artifacts.py has captured branch/commit_sha/patch_diff/touched_files/test_log
-- for every completed task since 2026-07-08 (the artifact-guard fix meant to kill the
-- missing-branch recovery loop by letting recovery reconstruct work from stored artifacts
-- instead of re-running the agent from scratch). The table it writes to was never created,
-- so every capture() call has been failing with a 404 and silently falling back to a
-- LOCAL JSON file on whichever Mac happened to run the task — which defeats the whole
-- point on this two-Mac fleet (the other machine can never see those artifacts) and was
-- one of the contributing factors in the 2026-07-08 merge-stall investigation.
--
-- Additive only; no existing table or data is touched.

create table if not exists task_artifacts (
  slug          text primary key,
  branch        text,
  commit_sha    text,
  patch_diff    text,
  diff_bytes    integer,
  touched_files jsonb,
  test_log      text,
  cost_usd      numeric,
  captured_at   timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists task_artifacts_captured_at_idx on task_artifacts (captured_at desc);

select '0038_task_artifacts OK — task_artifacts table created' as status;
