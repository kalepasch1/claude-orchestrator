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
-- APPLIED 2026-08-25, deliberately, at the operator's instruction.
--
-- THIS SWITCHED ON A GUARD THAT HAD BEEN INERT FOR THE WHOLE LIFE OF THE FLEET.
-- Tasks that previously started immediately are now re-queued with
-- "file-reservation-held: <file> (held by <task>)" when they collide on a
-- declared file. That is the module's documented purpose and runner.py:1205
-- already handles the re-queue; it is not a failure mode.
--
-- Verified end to end against the live table before this note was written:
-- task A reserves two files; B is blocked and told which task holds them; A's
-- re-entry is not a conflict; A's own files do not block A; release frees them
-- and B is then clear. All four are the contract reserve()/blocked_by() promise
-- and none of them could hold before, because the relation did not exist.
--
-- Blast radius, in order of what actually contains it:
--   * ORCH_FILE_RESERVATION_ENABLED=false is the kill switch and takes effect
--     without a schema change.
--   * A reservation is only taken when a task has a non-empty file scope
--     (declared, or computed by static_file_scope). No scope, no row.
--   * A collision RE-QUEUES; it never fails or drops a task.
--   * A crashed worker is covered by reserved_at + ttl_seconds (2h default),
--     swept client-side by _clean_expired().
--   * release() runs from set_state() on every terminal transition
--     (QUEUED/DONE/MERGED/BLOCKED/QUARANTINED) and from continuous_merger.

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
