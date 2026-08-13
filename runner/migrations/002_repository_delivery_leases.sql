-- 002_repository_delivery_leases.sql
--
-- Renewable, repository- and role-scoped delivery leases with a monotonic fencing token.
--
-- WHY
-- ---
-- integration_owner.decide() picks the integrating host as a *pure function of
-- runner_heartbeats*. That is cheap and cannot wedge the fleet, but it is advisory
-- and it is checked exactly ONCE, at the top of a train pass:
--
--   * TOCTOU. merge_train/release_train call decide() and then spend minutes on
--     rebase + full test run + production build before they push. The election can
--     flip underneath a pass (a host stops heartbeating, or a fresher code sha
--     appears) and nothing re-checks at write time.
--   * FAIL-OPEN IN THREE PLACES. No heartbeat rows -> True. Any exception inside
--     decide() -> True. Any exception around the call site -> "proceeding". Each is
--     individually defensible; together they mean two hosts can both believe they own
--     integration during a control-plane hiccup.
--   * A PASS IN FLIGHT IS NEVER INTERRUPTED, by explicit design. So a host that has
--     already lost the election keeps pushing to shared refs until its pass ends.
--
-- Those are the conditions that produced the 54 PUSH-VERIFY-FAILED sha mismatches
-- documented in integration_owner.py. A UUID token alone does not fix it: a UUID
-- proves identity but carries no ordering, so a stalled predecessor that wakes up
-- after its lease expired still presents a "valid-looking" token. Ordering is the
-- missing ingredient, hence a fencing token in the Kleppmann sense: a per
-- (repo_key, role) counter that strictly increases on every takeover, so a write
-- carrying a stale fence is rejected by the store rather than by the writer's
-- own good behaviour.
--
-- SCOPE
-- -----
-- repo_key   the PROJECT NAME, not a filesystem path — repo paths differ per Mac
--            (see db.localize_repo_path), project names do not.
-- role       'integrator' or 'releaser'. Held separately so a long merge-train pass
--            does not block an unrelated release, and so takeover of one does not
--            silently fence the other.

CREATE TABLE IF NOT EXISTS repository_delivery_leases (
    repo_key          text        NOT NULL,
    role              text        NOT NULL,
    owner             text        NOT NULL,
    runner_generation text        NOT NULL DEFAULT '',
    lease_token       uuid        NOT NULL,
    -- Strictly increasing per (repo_key, role). Never reset, never reused: the row
    -- survives release and takeover precisely so this counter keeps its history.
    fence             bigint      NOT NULL DEFAULT 1,
    acquired_at       timestamptz NOT NULL DEFAULT now(),
    heartbeat_at      timestamptz NOT NULL DEFAULT now(),
    expires_at        timestamptz NOT NULL,
    released_at       timestamptz,
    PRIMARY KEY (repo_key, role)
);

CREATE INDEX IF NOT EXISTS repository_delivery_leases_expiry_idx
    ON repository_delivery_leases (expires_at DESC);


-- acquire_delivery_lease
--
-- Returns the granted lease row, or NULL when a live lease is held by someone else.
-- The fence increments ONLY on a genuine change of holder. A re-acquire by the
-- current holder (same owner AND same token) is treated as a renewal and keeps the
-- fence, so a holder can never fence out its own in-flight work by calling acquire
-- twice.
CREATE OR REPLACE FUNCTION acquire_delivery_lease(
    p_repo_key   text,
    p_role       text,
    p_owner      text,
    p_token      uuid,
    p_generation text DEFAULT '',
    p_ttl_seconds integer DEFAULT 900
) RETURNS repository_delivery_leases
LANGUAGE plpgsql
AS $$
DECLARE
    existing repository_delivery_leases;
    granted  repository_delivery_leases;
    ttl      integer := GREATEST(60, COALESCE(p_ttl_seconds, 900));
BEGIN
    SELECT * INTO existing FROM repository_delivery_leases
     WHERE repo_key = p_repo_key AND role = p_role
     FOR UPDATE;

    IF NOT FOUND THEN
        INSERT INTO repository_delivery_leases
            (repo_key, role, owner, runner_generation, lease_token, fence,
             acquired_at, heartbeat_at, expires_at, released_at)
        VALUES (p_repo_key, p_role, p_owner, COALESCE(p_generation, ''), p_token, 1,
                now(), now(), now() + make_interval(secs => ttl), NULL)
        RETURNING * INTO granted;
        RETURN granted;
    END IF;

    -- Same holder re-acquiring: renewal, fence AND token preserved.
    --
    -- Matched on (owner, runner_generation) rather than on the token, because acquire()
    -- mints a fresh token on every call — a token match here could never fire, and the
    -- caller would fall through to the contention branch and deadlock against itself.
    -- The stored token and fence are returned unchanged rather than rotated, so a lease
    -- handle already held by in-flight work keeps verifying. Re-acquiring is idempotent
    -- for one process incarnation and is a takeover for anybody else.
    IF existing.owner = p_owner
       AND existing.runner_generation = COALESCE(p_generation, '')
       AND existing.released_at IS NULL THEN
        UPDATE repository_delivery_leases
           SET heartbeat_at = now(),
               expires_at   = now() + make_interval(secs => ttl)
         WHERE repo_key = p_repo_key AND role = p_role
        RETURNING * INTO granted;
        RETURN granted;
    END IF;

    -- Someone else still holds it and it has not lapsed: contended.
    IF existing.released_at IS NULL AND existing.expires_at > now() THEN
        RETURN NULL;
    END IF;

    -- Takeover of a released or expired lease. THIS is where the fence moves, and it
    -- is the whole point of the table: the moment it increments, every write still
    -- in flight under the previous fence becomes unauthorised.
    UPDATE repository_delivery_leases
       SET owner             = p_owner,
           runner_generation = COALESCE(p_generation, ''),
           lease_token       = p_token,
           fence             = existing.fence + 1,
           acquired_at       = now(),
           heartbeat_at      = now(),
           expires_at        = now() + make_interval(secs => ttl),
           released_at       = NULL
     WHERE repo_key = p_repo_key AND role = p_role
    RETURNING * INTO granted;
    RETURN granted;
END;
$$;


-- renew_delivery_lease
--
-- Extends the lease iff the caller still holds it at the exact fence it was granted.
-- Returns TRUE when still held. A FALSE here is genuine lease loss (taken over), and
-- callers must treat it as such — it is not an infrastructure error, which surfaces
-- as an exception instead.
CREATE OR REPLACE FUNCTION renew_delivery_lease(
    p_repo_key   text,
    p_role       text,
    p_owner      text,
    p_token      uuid,
    p_fence      bigint,
    p_generation text DEFAULT '',
    p_ttl_seconds integer DEFAULT 900
) RETURNS boolean
LANGUAGE plpgsql
AS $$
DECLARE
    ttl integer := GREATEST(60, COALESCE(p_ttl_seconds, 900));
    hit integer;
BEGIN
    UPDATE repository_delivery_leases
       SET heartbeat_at = now(),
           expires_at   = now() + make_interval(secs => ttl)
     WHERE repo_key = p_repo_key AND role = p_role
       AND owner = p_owner AND lease_token = p_token AND fence = p_fence
       AND runner_generation = COALESCE(p_generation, '')
       AND released_at IS NULL;
    GET DIAGNOSTICS hit = ROW_COUNT;
    RETURN hit > 0;
END;
$$;


-- verify_delivery_fence
--
-- The write-time gate. TRUE iff this exact (owner, token, fence) is the CURRENT
-- holder and has not lapsed. Deliberately does not extend the lease: verifying is
-- not renewing, and a check that silently kept a dead pass alive would defeat the
-- purpose.
--
-- Note the `fence >= p_fence` asymmetry is absent on purpose — equality is required.
-- A predecessor holding fence N must fail once the incumbent is at N+1, and an
-- impossibly-ahead fence indicates a bug, not authority.
CREATE OR REPLACE FUNCTION verify_delivery_fence(
    p_repo_key   text,
    p_role       text,
    p_owner      text,
    p_token      uuid,
    p_fence      bigint,
    p_generation text DEFAULT ''
) RETURNS boolean
LANGUAGE sql
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1 FROM repository_delivery_leases
         WHERE repo_key = p_repo_key AND role = p_role
           AND owner = p_owner AND lease_token = p_token AND fence = p_fence
           AND runner_generation = COALESCE(p_generation, '')
           AND released_at IS NULL AND expires_at > now()
    );
$$;


-- release_delivery_lease
--
-- Voluntary release. Marks the row released so the next acquirer takes over at
-- fence+1 without waiting out the TTL. Only the current holder may release; a
-- predecessor calling this after takeover is a no-op, which is what stops a late
-- straggler from releasing the incumbent's lease out from under it.
CREATE OR REPLACE FUNCTION release_delivery_lease(
    p_repo_key   text,
    p_role       text,
    p_owner      text,
    p_token      uuid,
    p_fence      bigint,
    p_generation text DEFAULT ''
) RETURNS boolean
LANGUAGE plpgsql
AS $$
DECLARE
    hit integer;
BEGIN
    UPDATE repository_delivery_leases
       SET released_at = now()
     WHERE repo_key = p_repo_key AND role = p_role
       AND owner = p_owner AND lease_token = p_token AND fence = p_fence
       AND runner_generation = COALESCE(p_generation, '')
       AND released_at IS NULL;
    GET DIAGNOSTICS hit = ROW_COUNT;
    RETURN hit > 0;
END;
$$;
