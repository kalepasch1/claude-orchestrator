-- Durable development-session event + artifact store. Contracts slice only:
-- tables, indexes and constraints. No behaviour, no backfills, no triggers.
--
-- WHY. task_artifacts records ONE row per task slug, and on any DB error it
-- falls back to a JSON file under .runtime/artifacts on whichever Mac happened
-- to run the task. That is invisible to every other host, so a release-critical
-- record can exist only on a laptop that is asleep. It also cannot answer "what
-- happened during this session, in order" — there is no event stream, only a
-- final snapshot, so a session that dies mid-flight leaves nothing to resume.
--
-- The invariants below are stated as CONSTRAINTS rather than as store-layer
-- checks so they survive a caller that bypasses development_session_store.py.
--
-- NOT YET APPLIED to eatfwdzfurujcuwlhdgj — apply after a shadow dry-run.
-- Idempotent: safe to re-run across rolling hosts.

-- ---------------------------------------------------------------------------
-- Sessions — one development session on one host.
-- ---------------------------------------------------------------------------
create table if not exists public.development_sessions (
  session_id    uuid primary key default gen_random_uuid(),
  slug          text not null,
  project       text,
  host          text not null,
  -- The runner generation that owns this session. A resumed session keeps its
  -- session_id and takes a new generation, so "who is writing right now" is
  -- answerable without guessing from timestamps.
  generation    bigint not null default 0,
  adapter       text,
  status        text not null default 'active'
    check (status in ('active','completed','failed','abandoned')),
  -- Monotonic high-water mark of appended events. Kept on the session so a
  -- reader can detect gaps without scanning the event table.
  last_seq      bigint not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  ended_at      timestamptz
);

create index if not exists development_sessions_slug_idx
  on public.development_sessions (slug, created_at desc);
create index if not exists development_sessions_status_idx
  on public.development_sessions (status, updated_at desc);
-- Host-loss sweep: find sessions still 'active' whose host stopped heartbeating.
create index if not exists development_sessions_host_active_idx
  on public.development_sessions (host, status);

-- ---------------------------------------------------------------------------
-- Events — append-only, per-session sequence, idempotent delivery.
-- ---------------------------------------------------------------------------
create table if not exists public.development_session_events (
  event_id       uuid primary key default gen_random_uuid(),
  session_id     uuid not null
                 references public.development_sessions (session_id) on delete cascade,
  -- Dense per-session ordinal. The (session_id, seq) unique constraint is what
  -- makes concurrent appenders safe: two writers racing for the same ordinal
  -- means exactly one INSERT survives and the loser retries at seq+1, rather
  -- than both "succeeding" and one silently overwriting the other.
  seq            bigint not null check (seq > 0),
  -- Caller-supplied key for at-least-once transports. A redelivered event
  -- collides here and is absorbed instead of being appended twice.
  idempotency_key text not null,
  kind           text not null,
  payload        jsonb not null default '{}'::jsonb,
  redacted       boolean not null default false,
  created_at     timestamptz not null default now(),
  constraint development_session_events_seq_unique unique (session_id, seq),
  constraint development_session_events_idem_unique unique (session_id, idempotency_key)
);

-- Cursor pagination reads (session_id, seq) ranges in order; this is the index
-- that keeps a >1000-event replay from degrading into a scan.
create index if not exists development_session_events_cursor_idx
  on public.development_session_events (session_id, seq);
create index if not exists development_session_events_retention_idx
  on public.development_session_events (created_at);

-- ---------------------------------------------------------------------------
-- Artifacts — durable references, never a local path.
-- ---------------------------------------------------------------------------
create table if not exists public.development_session_artifacts (
  artifact_id   uuid primary key default gen_random_uuid(),
  session_id    uuid
                references public.development_sessions (session_id) on delete set null,
  slug          text,
  task_id       text,
  commit_sha    text,
  -- Content address. Two runs producing identical bytes produce identical
  -- digests, so replay can prove it is looking at the same artifact.
  digest        text not null,
  media_type    text not null default 'application/octet-stream',
  byte_size     bigint not null default 0,
  -- Provenance: which adapter, on which runner, in which generation.
  adapter       text,
  runner_host   text,
  generation    bigint not null default 0,
  -- Durable location (git ref, object-store URL, ...). A bare local filesystem
  -- path is rejected by the store layer: it is not durable, and recording one
  -- is how a release-critical artifact ends up readable from exactly one Mac.
  location      text not null,
  location_kind text not null default 'unknown',
  redacted      boolean not null default false,
  created_at    timestamptz not null default now(),
  constraint development_session_artifacts_digest_unique unique (digest, location)
);

create index if not exists development_session_artifacts_session_idx
  on public.development_session_artifacts (session_id, created_at desc);
create index if not exists development_session_artifacts_slug_idx
  on public.development_session_artifacts (slug, created_at desc);
create index if not exists development_session_artifacts_digest_idx
  on public.development_session_artifacts (digest);
