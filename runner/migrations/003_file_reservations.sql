-- 003_file_reservations.sql
--
-- The table runner/file_reservation.py has been talking to since it was written,
-- and which has never existed.
--
-- WHY
-- ---
-- file_reservation.py is the fleet's file-level mutual exclusion: before a task
-- runs, runner.py computes the files it will touch, asks blocked_by() whether
-- another task holds any of them, re-queues the task if so, and otherwise calls
-- reserve() to claim them (runner.py:1205-1212). Structurally this is the right
-- shape, and the read half is correctly written against the PostgREST client.
--
-- The write half never worked. reserve(), release(), _clean_expired() and
-- _ensure_table() were all written as raw SQL passed to `db.query(...)`, and the
-- db module has no query() — it is a PostgREST client and has never had a
-- raw-SQL channel. Every one of those calls raised AttributeError into a handler
-- that logged at debug or returned success. So:
--
--   * _ensure_table()'s CREATE TABLE never ran, and could not have: PostgREST
--     exposes no DDL. It returned True regardless ("Table might already exist —
--     try to proceed anyway").
--   * reserve() never inserted a row. Its except-arm looked for the words
--     "duplicate"/"conflict"/"unique" in the error text; "module 'db' has no
--     attribute 'query'" contains none of them, so every file was recorded as
--     neither reserved nor blocked.
--   * blocked_by(), which uses the real db.select and is correct, therefore read
--     an absent relation forever and always answered "nothing is held".
--
-- Net effect: no task has ever been re-queued for a file conflict. Confirmed
-- against the live schema on 2026-08-25 — `file_reservations` is not among the
-- project's tables.
--
-- APPLYING THIS IS A BEHAVIOUR CHANGE. It switches on a guard that has been
-- inert for the whole life of the fleet: tasks that currently start immediately
-- will begin to be re-queued with "file-reservation-held: <file> (held by
-- <task>)" when they collide. That is the intended behaviour and is presumably
-- why the module was written, but it should be a deliberate act, not a side
-- effect of a test-suite repair — so this file is checked in and NOT applied.
-- ORCH_FILE_RESERVATION_ENABLED=false remains the kill switch either way.
--
-- Until it is applied, file_reservation now says so once per process instead of
-- reporting success.

CREATE TABLE IF NOT EXISTS public.file_reservations (
    id          uuid        DEFAULT gen_random_uuid() PRIMARY KEY,
    task_id     text        NOT NULL,
    project_id  text        NOT NULL DEFAULT '',
    repo        text        NOT NULL,
    filepath    text        NOT NULL,
    reserved_at timestamptz NOT NULL DEFAULT now(),
    ttl_seconds int         NOT NULL DEFAULT 7200,

    -- This constraint IS the lock. reserve() claims a file with a plain INSERT
    -- and reads PostgREST's 409 as "held by someone else"; without the
    -- constraint the insert always succeeds and two tasks both believe they own
    -- the file. Do not drop it to "fix" a duplicate-key error.
    CONSTRAINT file_reservations_repo_filepath_key UNIQUE (repo, filepath)
);

-- blocked_by() filters on (repo, filepath) and excludes the asking task;
-- release() and the expiry sweep filter on task_id.
CREATE INDEX IF NOT EXISTS file_reservations_task_id_idx
    ON public.file_reservations (task_id);
CREATE INDEX IF NOT EXISTS file_reservations_reserved_at_idx
    ON public.file_reservations (reserved_at);

-- Service-role only, like the other runner-owned tables: these rows serialise
-- execution across the fleet, and an anon writer could park a reservation on a
-- hot file and stall every task that touches it. RLS on with no policies means
-- only SUPABASE_SERVICE_KEY (which bypasses RLS) can reach it. Do not add a
-- permissive policy to "fix" an access error — find out who is calling with the
-- wrong key.
ALTER TABLE public.file_reservations ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.file_reservations IS
    'File-level mutual exclusion for task execution. One row per (repo, filepath) '
    'held by a task; UNIQUE(repo, filepath) is the lock. Written by '
    'runner/file_reservation.py. Rows expire by reserved_at + ttl_seconds, swept '
    'client-side because PostgREST cannot express a per-row interval predicate.';
