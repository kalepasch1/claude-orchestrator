-- Database Steering: remediation outcome history.
-- db_remediate.closeout_* measures db-steer PRs against live findings and used to say
-- its verdict only on the PR thread (a commit comment). Persisting one row per PR per
-- measurement turns the verdict stream into outcome learning: which remediation groups
-- actually fix things, which rot, and which findings keep recurring after "fixed".
--
-- One row per (repo, pr_number), upserted as scans re-measure; measured_at + the
-- counts move, state flips open-pending -> verified-resolved / merged-not-confirmed.
create table if not exists db_pr_closeouts (
    id uuid primary key default gen_random_uuid(),
    project text not null,
    repo text not null,
    pr_number integer not null,
    pr_group text,                       -- access-grants / fk-indexes / audit-columns / rls-policies
    state text not null,                 -- open-pending | verified-resolved | merged-not-confirmed | merged-no-live-match
    findings_total integer not null default 0,
    findings_resolved integer not null default 0,
    findings_open integer not null default 0,
    merged boolean not null default false,
    first_measured_at timestamptz not null default now(),
    measured_at timestamptz not null default now(),
    unique (repo, pr_number)
);

comment on table db_pr_closeouts is 'Outcome learning: each db-steer remediation PR measured against live findings over time.';
create index if not exists db_pr_closeouts_project_idx on db_pr_closeouts (project, measured_at desc);
create index if not exists db_pr_closeouts_state_idx on db_pr_closeouts (state);
