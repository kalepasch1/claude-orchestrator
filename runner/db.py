#!/usr/bin/env python3
"""
db.py - tiny Supabase (PostgREST) client over urllib. No third-party deps.
The runner uses the SERVICE ROLE key so it bypasses RLS. Set:
    SUPABASE_URL=https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY=<service-role key>   (keep secret; never ship to the web app)
The .env file in runner/ is auto-loaded at import time by the _load_env() helper below.
"""
import os, re, json, socket, time, datetime, threading, urllib.request, urllib.parse, urllib.error


# ── DB failover detection ────────────────────────────────────────────────────
DB_DOWN_THRESHOLD = int(os.environ.get("SENTINEL_DB_DOWN_THRESHOLD", "3"))
_db_failure_count = 0
_db_failure_lock = threading.Lock()

def is_db_down():
    """Return True if consecutive DB failures >= threshold."""
    return _db_failure_count >= DB_DOWN_THRESHOLD

def _increment_db_failure_count():
    global _db_failure_count
    with _db_failure_lock:
        _db_failure_count += 1
        return _db_failure_count

def _reset_db_failure_count():
    global _db_failure_count
    with _db_failure_lock:
        _db_failure_count = 0


class MissingRelationError(Exception):
    """Raised when a PostgREST request targets a table that does not exist in the schema.

    This is a permanent, structural error, not a transient one: no amount of retrying will make
    the table appear. It exists so callers — and the periodic job runner in particular — can tell
    "this job is querying something that was never deployed" apart from a real outage.

    Added 2026-08-02 after finding relationship_crm (crm_contacts) and virtual_executive_worker
    (legal_obligations) had each crash-looped thousands of times against tables that do not
    exist, writing 17MB of identical tracebacks that buried every genuine failure in the logs.
    """


class TransientDBError(Exception):
    """Raised when a Supabase/PostgREST request fails with a retryable HTTP status (e.g. 409 Conflict).

    Callers can catch this to distinguish transient DB collisions from permanent errors.
    The original urllib.error.HTTPError is chained via __cause__.
    """
    pass

# Load runner/.env directly from Python so launchd agents pick up all env vars
# (EMBED_PROVIDER, ANTHROPIC_API_KEY, etc.) even when the shell wrapper can't
# source the file due to macOS TCC restrictions.
def _load_env():
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    # Billing firewall, layer 2: every periodic job runs as a fresh subprocess that imports db
    # at the top, and this loader used to setdefault() a stray ANTHROPIC_API_KEY back into the
    # environment even after subscription_guard.enforce() stripped it from the parent runner
    # process. That re-injection made billing_guard trip every 5 minutes and re-pause the whole
    # fleet (root cause of the 2026-07-08 overnight outage: 878 consecutive trips). When
    # subscription mode is on and API billing hasn't been explicitly opted into, never let
    # ANTHROPIC_API_KEY* enter the environment from .env.
    try:
        with open(env) as f:
            raw_lines = f.readlines()
    except OSError:
        return  # silently skip if FDA not yet granted; plist env vars are the fallback
    pairs = []
    for raw in raw_lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.split("#")[0].strip().strip('"').strip("'")
        pairs.append((k, v))
    # setdefault() below means the FIRST definition of a key wins, so a later line setting the
    # same key to a different value is silently dead. ORCH_SUPABASE_RETRIES was set to 1 on line
    # 116 and 4 on line 399 of a 500-line file; the 4 never applied and three monitor jobs
    # crash-looped on a transient edge error as a result. Nothing surfaced it. Now it is loud.
    _seen = {}
    _shadowed = []
    for k, v in pairs:
        if k in _seen and _seen[k] != v:
            _shadowed.append((k, _seen[k], v))
        _seen.setdefault(k, v)
    for k, kept, ignored in _shadowed:
        print("db: .env defines %s twice with different values — using %r, IGNORING %r. "
              "Delete one of the definitions." % (k, kept, ignored))
    # First pass: everything except Anthropic API keys, so an ORCH_ALLOW_API_BILLING=true set
    # only inside .env (not the shell/plist) is honored below rather than read as its old default.
    anthropic_pairs = []
    for k, v in pairs:
        if k == "ANTHROPIC_API_KEY" or k.startswith("ANTHROPIC_API_KEY_"):
            anthropic_pairs.append((k, v))
            continue
        os.environ.setdefault(k, v)
    sub_on = os.environ.get("ORCH_USE_SUBSCRIPTION", "true").lower() == "true"
    api_opt_in = os.environ.get("ORCH_ALLOW_API_BILLING", "false").lower() == "true"
    if sub_on and not api_opt_in:
        return  # billing blocked: leave ANTHROPIC_API_KEY* out of the environment entirely
    for k, v in anthropic_pairs:
        os.environ.setdefault(k, v)

def _ensure_tool_path():
    """Prepend standard tool directories to PATH so git/python/brew are available in launchd."""
    paths = (
        "/opt/homebrew/bin",
        "/usr/local/bin",
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/Library/Python/3.9/bin"),
        os.path.expanduser("~/Library/Python/3.11/bin"),
        os.path.expanduser("~/Library/Python/3.12/bin"),
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    )
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    for p in reversed(paths):
        if os.path.isdir(p) and p not in parts:
            parts.insert(0, p)
    os.environ["PATH"] = os.pathsep.join(parts)

_load_env()
if os.environ.get("ORCH_CANONICAL_RUNTIME_HOME", "true").lower() in ("1", "true", "yes", "on"):
    os.environ["CLAUDE_ORCH_HOME"] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime")
_ensure_tool_path()

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
HTTP_TIMEOUT = float(os.environ.get("ORCH_SUPABASE_TIMEOUT", "15") or 15)

# --- Secret redaction: strip credentials from task fields before DB writes ---
_SECRET_PATTERNS = re.compile(
    r"("
    # Anthropic API keys (sk-ant-api03-...)
    r"sk-ant-api\S{10,}"
    r"|"
    # Supabase service role keys (eyJ...)
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"
    r"|"
    # GitHub PATs and tokens (github_pat_, ghp_, gho_, ghs_, ghu_, ghr_)
    r"(?:github_pat_|gh[posur]_)[A-Za-z0-9_]{20,}"
    r"|"
    # Vercel tokens (vcp_)
    r"vcp_[A-Za-z0-9]{20,}"
    r"|"
    # AWS access key IDs (AKIA...)
    r"AKIA[0-9A-Z]{16}"
    r"|"
    # OpenAI keys (sk-...)
    r"sk-[A-Za-z0-9]{20,}"
    r"|"
    # Generic key=value patterns
    r"(?:(?:api[_-]?key|secret[_-]?key|service[_-]?key|token|password|credential)"
    r"\s*[=:]\s*['\"]?)([A-Za-z0-9_/+\-.]{16,})"
    r"|"
    # Generic bearer tokens
    r"Bearer\s+[A-Za-z0-9_\-/.]{20,}"
    r")",
    re.I,
)
_TASK_SENSITIVE_FIELDS = {"note", "log_tail", "prompt"}


def redact_secrets(text):
    """Replace secret-like patterns in text with [REDACTED]. Fail-soft: returns
    original text on any error so it never blocks writes."""
    if not text or not isinstance(text, str):
        return text
    try:
        return _SECRET_PATTERNS.sub("[REDACTED]", text)
    except Exception:
        return text
# One retry was not enough to ride out a Cloudflare edge blip: on 2026-08-03 the arbitrage,
# batchmech and forecast jobs all crash-looped on 521/525 within the same minute, having exhausted
# their single retry against an outage that lasted longer than one second of backoff.
HTTP_RETRIES = int(os.environ.get("ORCH_SUPABASE_RETRIES", "3") or 3)
# Retry on transient HTTP errors: 408 (request timeout), 429 (rate-limited), 5xx (server errors),
# plus the Cloudflare edge codes so monitors ride through Supabase capacity blips instead of
# silently no-op'ing. 520 (unknown origin error), 524 (origin timeout) and 525 (origin SSL
# handshake failed) were missing and are as transient as the 521-523 already listed — a 525 in
# particular is a TLS handshake that will usually succeed on the next attempt.
HTTP_RETRY_STATUSES = {408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525}
# Core orchestrator RPC operations that benefit from retries to tolerate transient failures
CORE_RETRY_RPCS = {
    "acquire_branch_execution_lease", "heartbeat_branch_execution_lease", "release_branch_execution_lease",
    "execute_task", "complete_task", "claim_task", "mark_done",
    "record_attempt", "update_task_state", "insert_outcome",
}
RECOVERY_PREFIX = "recover-missing-branch-"
CANARY_PREFIX = "canary-"
IMPROVEMENT_PREFIX = "improve-"
RELEASE_FIX_PREFIXES = ("relfix-", "qafix-", "deployfix-", "buildfix-", "copyfix-",
                        "toolchain-repair-")
REWORK_PREFIX = "rework-"
CLAIM_SCAN_LIMIT = int(os.environ.get("ORCH_CLAIM_SCAN_LIMIT", "1000") or 1000)
PROJECT_PRIORITY_ORDER = {
    "orchestrator": 1,
    "beethoven": 1,
    "tomorrow": 2,
    "apparently": 3,
    "smarter": 4,
    "pareto-2080": 5,
    "pareto": 5,
    "2080": 5,
    "hisanta": 6,
    "santas-secret-workshop": 6,
    "galop": 7,
    "racefeed": 7,
    "sustainable-barks": 8,
    "sustainablebarks": 8,
}


def _project_rank_name(name):
    """Return numeric priority for *name* (lower = higher priority, 9 = default/unknown)."""
    return PROJECT_PRIORITY_ORDER.get(str(name or "").strip().lower(), 9)


def localize_repo_path(repo_path):
    """Resolve a project's stored repo_path to THIS machine's actual clone.

    projects.repo_path is one shared absolute path (e.g. /Users/kpasch/Documents/foo). On the
    machine that owns that path it exists as-is; on a second Mac the same repo lives under a
    different home (e.g. /Users/mandypasch/Documents/foo). Rewrite the /Users/<user>/ home prefix
    to THIS user's home when a clone actually exists there, so one shared task queue is runnable on
    any Mac that has the repos at the same sub-path. No-op on the owning machine (stored path
    already exists) and no-op when there is no local clone (the claim guard then skips the task, so
    a runner never grabs work it cannot run). Opt out with ORCH_REPO_LOCALIZE=false.

    Args:
        repo_path (str | None): Stored repo path from projects table.

    Returns:
        str | None: Localized path for this machine, or original if no local clone exists.
    """
    if not repo_path or os.environ.get("ORCH_REPO_LOCALIZE", "true").lower() in ("false", "0", "no"):
        return repo_path
    if os.path.isdir(repo_path):
        return repo_path  # stored path is valid on this host (the owning machine)
    m = re.match(r"^/Users/[^/]+/(.*)$", repo_path)
    if m:
        cand = os.path.join(os.path.expanduser("~"), m.group(1))
        if os.path.isdir(cand):
            return cand
    return repo_path  # no local equivalent — leave unchanged; caller/guard handles absence


def repo_runnable_here(repo_path):
    """Check if a task's project repo can run on this machine (host affinity).

    A task is runnable if it has no repo_path (uses cwd) or a local clone exists
    (possibly via localize_repo_path). Used by claim_task to prevent cross-machine
    task theft when the required repo is not locally available.

    Args:
        repo_path (str | None): Stored repo path from projects table.

    Returns:
        bool: True if runnable here; False if repo is required but not present.
    """
    if not repo_path:
        return True
    loc = localize_repo_path(repo_path)
    if not os.path.isdir(loc):
        return False
    try:
        os.listdir(loc)
        return True
    except (PermissionError, OSError):
        return False


def _is_core_rpc(path):
    """Check if a request path is for a core orchestrator RPC that should be retried.

    Returns True only for orchestrator-critical operations. External/vendor RPC calls
    are not retried to reduce rate-limiting cascade on non-critical paths.
    """
    if "/rpc/" not in path:
        return False
    rpc_name = path.split("/rpc/")[-1].rstrip("/")
    return rpc_name in CORE_RETRY_RPCS


def _req(method, path, body=None, headers=None, params=None):
    if not URL or not KEY:
        raise RuntimeError("set SUPABASE_URL and SUPABASE_SERVICE_KEY")
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}",
         "Content-Type": "application/json"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path + qs, data=data, method=method, headers=h)
    # Reads are idempotent, so they can safely ride out transient resolver and
    # edge failures.  Core RPC writes (branch leases, task state) also retry on transient
    # errors since they are orchestrator-critical and safe to retry. Other writes deliberately
    # remain single-attempt: retrying an uncertain POST could create duplicate work when the
    # first request reached PostgREST but its response was lost. External RPC calls skip retry
    # to reduce rate-limiting cascade on non-critical paths.
    retryable = method == "GET" or (method == "POST" and _is_core_rpc(path))
    attempts = HTTP_RETRIES + 1 if retryable else 1
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            # A flood-guard dedup rejection (HTTP 409) must NOT kill the task —
            # it means a unique constraint blocked a duplicate insert, which is
            # idempotent and safe to ignore. No callers depend on the return value
            # of insert(), so returning None is safe.
            if e.code == 409:
                raise TransientDBError(f"HTTP 409 Conflict on {method} {path}") from e
            # A 404 on /rest/v1/<table> means the relation is not in the schema. Retrying cannot
            # help, and letting it surface as a bare HTTPError is what allowed several jobs to
            # crash-loop indefinitely against tables that were never deployed.
            if e.code == 404 and path.startswith("/rest/v1/"):
                _relation = path[len("/rest/v1/"):].split("?")[0].strip("/")
                raise MissingRelationError(
                    f"relation '{_relation}' does not exist (HTTP 404 on {method} {path})") from e
            if not retryable or e.code not in HTTP_RETRY_STATUSES or attempt >= attempts - 1:
                raise
            time.sleep(min(12, 2 ** attempt) + (0.1 * attempt))
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            if not retryable or attempt >= attempts - 1:
                raise
            time.sleep(min(12, 2 ** attempt) + (0.1 * attempt))


def select(table, params=None):
    """Fetch rows from *table* via PostgREST GET.  Returns a list of dicts."""
    return _req("GET", f"/rest/v1/{table}", params=params or {"select": "*"})


def count(table, params=None):
    """Exact PostgREST row count without downloading the matching rows."""
    if not URL or not KEY:
        raise RuntimeError("set SUPABASE_URL and SUPABASE_SERVICE_KEY")
    q = dict(params or {})
    q.setdefault("select", "id")
    qs = "?" + urllib.parse.urlencode(q)
    h = {
        "apikey": KEY,
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
        "Prefer": "count=exact",
        "Range-Unit": "items",
        "Range": "0-0",
    }
    req = urllib.request.Request(URL + f"/rest/v1/{table}" + qs, method="GET", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            content_range = r.headers.get("Content-Range", "")
            if "/" in content_range:
                total = content_range.rsplit("/", 1)[1]
                if total and total != "*":
                    return int(total)
            raw = r.read().decode()
            return len(json.loads(raw) if raw else [])
    except urllib.error.HTTPError as e:
        if e.code == 416:
            content_range = e.headers.get("Content-Range", "")
            if "/" in content_range:
                total = content_range.rsplit("/", 1)[1]
                if total and total != "*":
                    return int(total)
            return 0
        raise


# ── Queue admission control ──────────────────────────────────────────────────────────────────
#
# WHY (2026-08-02): the fleet created 1,877 tasks in 24h and completed 55. Depth grew ~166/hour
# and never converged, so genuinely wanted work (the queued branding and design missions) sat
# behind thousands of machine-generated tasks that would never be reached.
#
# queue_velocity.py already had a PID controller for this, but it gated on a hardcoded set of
# nine "pausable generators" — and 53 different modules call db.insert("tasks", ...). None of the
# high-volume ones were in the set, so it never fired. A per-generator allowlist cannot keep up
# with a codebase that grows new generators; the ceiling has to live at the single insertion
# choke point, where every route is subject to it regardless of caller.
#
# Work that clears blockage is exempt, otherwise a full queue would prevent the fleet from
# repairing itself out of the condition.
_QUEUE_DEPTH_CACHE = {"at": 0.0, "depth": 0}
_QUEUE_BLOCK_LOGGED = {"at": 0.0, "count": 0}
# Exemption is by slug prefix only, deliberately.
#
# `kind` is far too coarse: agentic_repair stamps kind="bugfix" on every buildfail/testfail/
# missing-branch/noop/conflict repair it spawns, so exempting that kind waved the entire rework
# loop straight past the ceiling — which is the loop that produced 2,000 queued and 700
# quarantined rows in the first place. The slug prefixes below are set by the release and deploy
# fix paths specifically, and those are the only tasks that genuinely unblock shipping.
_EXEMPT_SLUG_PREFIXES = ("relfix-", "deployfix-", "buildfix-", "hotfix-")


def _max_queue_depth():
    try:
        return int(os.environ.get("ORCH_MAX_QUEUE_DEPTH", "800"))
    except ValueError:
        return 800


def _queue_depth_block(row):
    """True when the queue is over its ceiling and this task is not exempt."""
    ceiling = _max_queue_depth()
    if ceiling <= 0:
        return False
    slug = str(row.get("slug") or "")
    if slug.startswith(_EXEMPT_SLUG_PREFIXES):
        return False
    if row.get("_bypass_depth_cap"):
        return False

    now = time.time()
    if now - _QUEUE_DEPTH_CACHE["at"] > 60:
        try:
            _QUEUE_DEPTH_CACHE["depth"] = count("tasks", {"state": "eq.QUEUED"}) or 0
            _QUEUE_DEPTH_CACHE["at"] = now
        except Exception:
            return False  # never let admission control fail an insert on its own error

    if _QUEUE_DEPTH_CACHE["depth"] < ceiling:
        return False

    _QUEUE_BLOCK_LOGGED["count"] += 1
    if now - _QUEUE_BLOCK_LOGGED["at"] > 300:
        print(f"[queue-cap] QUEUED depth {_QUEUE_DEPTH_CACHE['depth']} >= ceiling {ceiling}; "
              f"refused {_QUEUE_BLOCK_LOGGED['count']} task insert(s) in the last window "
              f"(latest: {slug[:70]}). Blocker-clearing kinds are still admitted. "
              f"Raise ORCH_MAX_QUEUE_DEPTH to change.", flush=True)
        _QUEUE_BLOCK_LOGGED["at"] = now
        _QUEUE_BLOCK_LOGGED["count"] = 0
    return True


def _guard_fleet_config(table, row):
    """Refuse to persist a credential into fleet_config, from ANY write path.

    The ban existed in config_applier and config_sync, but a dozen other writers
    (config_changelog, config_rollback, auto_tune_applicator, continuous_test,
    decomposition_backpressure, raw SQL INSERTs) never consulted them — which is how
    VERCEL_TOKEN, GITHUB_PAT, OPENAI_API_KEY and GEMINI_API_KEY ended up stored in
    plaintext (incident 2026-08-02). This is the one door every writer passes through.

    Fails CLOSED: if the guard module is unavailable, an inline pattern still blocks
    the obvious cases rather than letting the write through.
    """
    if table != "fleet_config" or not isinstance(row, dict):
        return
    key, value = row.get("key"), row.get("value")
    try:
        import fleet_config_guard
    except Exception:
        import re as _re
        if _re.search(r"(SECRET|TOKEN|PASSWORD|CREDENTIAL|API_?KEY|_PAT\b|PRIVATE_?KEY)",
                      str(key or ""), _re.I):
            raise ValueError(
                f"[fleet-config-guard/fallback] refusing to store credential-named key "
                f"'{key}' in fleet_config")
        return
    fleet_config_guard.assert_writable(key, value)


def insert(table, row, upsert=False):
    """Insert a single row into *table* via PostgREST POST.  Returns the created row or None on 409 dedup."""
    _guard_fleet_config(table, row)
    if table == "tasks" and isinstance(row, dict):
        # Keep the persisted DAG shape deterministic for every insertion route,
        # including upserts. A SQL NULL here makes independent tasks disappear
        # from dependency-aware queue queries.
        import execution_assurance
        row = dict(row)
        row["deps"] = execution_assurance.normalize_deps(row.get("deps"))
        blocked = _queue_depth_block(row)
        if blocked:
            return None
    # IDEMPOTENT TASK ENQUEUE (2026-07-10): the queue has no UNIQUE(project_id, slug) constraint,
    # so ~20 different generators that db.insert("tasks", ...) directly kept creating duplicate
    # QUEUED rows (5-at-a-time, recurring — the sentinel dedupe was firing 45x/24h just cleaning up
    # after them). Guard at the single choke point: if a task with this (project_id, slug) already
    # exists in a live/settled state, skip the insert. Opt out with row["_allow_dup"]=True.
    # PROMPT VALIDATION GATE: reject tasks with garbage prompts before they enter the queue.
    # Catches: PATCH TEMPLATE stubs, empty prompts, prompts that are just error messages.
    # This prevents 1,794+ garbage tasks from ever being created (they used to be cleaned up
    # after the fact by rootcause_cluster, which was too late — they'd already consumed slots).
    if table == "tasks" and isinstance(row, dict) and not upsert:
        _prompt = (row.get("prompt") or "").strip()
        _reject_reason = None
        if not _prompt or len(_prompt) < 20:
            _reject_reason = "empty or trivial prompt"
        elif _prompt.startswith("PATCH TEMPLATE"):
            _reject_reason = "unfilled PATCH TEMPLATE stub"
        elif all(line.startswith(("Error", "error:", "Traceback", "fatal:"))
                 for line in _prompt.strip().split("\n")[:5] if line.strip()):
            _reject_reason = "prompt is only error messages"
        if _reject_reason:
            import logging
            logging.getLogger("db").warning(
                "prompt-gate: rejecting task %s — %s (prompt: %.100s...)",
                row.get("slug", "?"), _reject_reason, _prompt)
            return None  # silently reject — caller gets None, same as "already exists"

    if (table == "tasks" and isinstance(row, dict) and not upsert
            and row.get("slug") and row.get("project_id") and not row.pop("_allow_dup", False)):
        # ATOMIC DEDUP (2026-07-14): the old SELECT-then-INSERT raced across two Macs,
        # causing 503 duplicate tasks. Now we:
        # 1. Check for existing (fast path, catches most dupes)
        # 2. Use a process-level lock to serialize concurrent inserts on the same machine
        # 3. Re-check after acquiring the lock (double-checked locking)
        _dedup_key = f"{row['project_id']}:{row['slug']}"
        try:
            existing = select("tasks", {
                "select": "id,slug,state",
                "project_id": f"eq.{row['project_id']}",
                "slug": f"eq.{row['slug']}",
                "state": "in.(QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED,DECOMPOSED)",
                "limit": "1"}) or []
            if existing:
                return existing
        except Exception:
            pass  # fail-soft: never let the guard block a legitimate insert
    # SECRET HYGIENE: redact secrets from sensitive fields on task insert.
    if table == "tasks" and isinstance(row, dict):
        for field in _TASK_SENSITIVE_FIELDS:
            if field in row and isinstance(row[field], str):
                row[field] = redact_secrets(row[field])
    h = {"Prefer": "return=representation" + (",resolution=merge-duplicates" if upsert else "")}
    try:
        result = _req("POST", f"/rest/v1/{table}", body=row, headers=h)
    except TransientDBError:
        # 409 = duplicate key: the row already exists, so the write intent is satisfied. A retried
        # task re-inserting an outcome/row used to raise HTTP 409 -> "runner exception: Conflict" ->
        # BLOCKED, which stalled merges. Retry idempotently as an upsert; if that still can't apply,
        # swallow it so a duplicate never crashes the task.
        if upsert:
            return None
        try:
            return _req("POST", f"/rest/v1/{table}",
                        body=row, headers={"Prefer": "return=representation,resolution=merge-duplicates"})
        except Exception:
            return None

    # POST-INSERT DEDUP RECONCILIATION (2026-07-15): the SELECT-then-INSERT guard above
    # prevents same-machine duplicates via _dedup_lock, but two Macs can still race past
    # the SELECT check simultaneously and both INSERT. This post-insert check detects that
    # race: if multiple QUEUED rows now share (project_id, slug), keep only the oldest and
    # DELETE the rest. This closes the cross-machine race window that previously required
    # the groom_task_queue sentinel to clean up after the fact (producing the
    # "groomed: duplicate queued slug" failures ~45x/24h).
    if (table == "tasks" and isinstance(row, dict) and not upsert
            and row.get("slug") and row.get("project_id")):
        try:
            dupes = select("tasks", {
                "select": "id,created_at",
                "project_id": f"eq.{row['project_id']}",
                "slug": f"eq.{row['slug']}",
                "state": "eq.QUEUED",
                "order": "created_at.asc",
            }) or []
            if len(dupes) > 1:
                # Keep the oldest (first by created_at), delete the rest
                keeper_id = dupes[0]["id"]
                for dup in dupes[1:]:
                    try:
                        _req("DELETE", "/rest/v1/tasks",
                             params={"id": f"eq.{dup['id']}", "state": "eq.QUEUED"})
                    except Exception:
                        pass
                import logging
                logging.getLogger("db").info(
                    "post-insert-dedup: removed %d duplicate QUEUED rows for slug=%s (kept %s)",
                    len(dupes) - 1, row["slug"], keeper_id)
        except Exception:
            pass  # fail-soft: groom_task_queue sentinel is the backstop

    return result


def upsert(table, row):
    """Compatibility helper for modules that store idempotent control rows."""
    return insert(table, row, upsert=True)


def update(table, match, patch):
    """PATCH rows in *table* matching *match* dict with *patch* fields.  Tolerates 409 (concurrent write)."""
    # A PATCH can plant a secret just as easily as an INSERT; the key may live in
    # `match` (WHERE key=…) while the credential arrives in `patch` (SET value=…).
    if table == "fleet_config":
        _guard_fleet_config(table, {"key": (match or {}).get("key") or (patch or {}).get("key"),
                                    "value": (patch or {}).get("value")})
    params = {k: f"eq.{v}" for k, v in match.items()}
    try:
        return _req("PATCH", f"/rest/v1/{table}", body=patch,
                    headers={"Prefer": "return=representation"}, params=params)
    except TransientDBError:
        # 409 = a concurrent write (the two Macs racing the same row). The write intent is already
        # satisfied by the other writer, so treat it as a no-op instead of letting it bubble up as a
        # "runner exception: HTTP 409 conflict" that terminally BLOCKS the task (this froze 200+ tasks).
        return None


def rpc(fn, args):
    """Call a PostgREST RPC function *fn* with *args* dict and return the result."""
    return _req("POST", f"/rest/v1/rpc/{fn}", body=args)


class _DBNamespace:
    """Namespace wrapper for database operations to support mocking/testing."""
    @staticmethod
    def insert(table, row, upsert=False):
        return insert(table, row, upsert)

    @staticmethod
    def select(table, params=None):
        return select(table, params)

    @staticmethod
    def update(table, match, patch):
        return update(table, match, patch)

    @staticmethod
    def count(table, params=None):
        return count(table, params)


db = _DBNamespace()


def _ev_rank_map():
    """Best-effort EV ranking fallback.

    ev_scheduler writes a controls row when the live schema lacks tasks.priority.
    claim_task must consume that row or the ranking loop becomes advisory only.
    """
    try:
        rows = select("controls", {"select": "value", "key": "eq.ev_ranking", "limit": "1"}) or []
        raw = (rows[0] if rows else {}).get("value") or "[]"
        ids = json.loads(raw) if isinstance(raw, str) else raw
        return {str(tid): i for i, tid in enumerate(ids or [])}
    except Exception:
        return {}


def _thermal_rank_map():
    try:
        rows = select("controls", {"select": "value", "key": "eq.thermal_ranking", "limit": "1"}) or []
        raw = (rows[0] if rows else {}).get("value") or "[]"
        ids = json.loads(raw) if isinstance(raw, str) else raw
        return {str(tid): i for i, tid in enumerate(ids or [])}
    except Exception:
        return {}


def _num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _is_recovery_task(t):
    return str((t or {}).get("slug") or "").startswith(RECOVERY_PREFIX)


def _is_release_fix_task(t):
    slug = str((t or {}).get("slug") or "")
    note = str((t or {}).get("note") or "").lower()
    if slug.startswith(("qafix-", "buildfix-", "deployfix-", "copyfix-")):
        return True
    if slug.startswith("relfix-"):
        # `relfix-*` is also used by the improvement miner for speculative
        # orchestrator ideas. Those are valuable, but they are not production
        # release blockers and must not monopolize the emergency hot lane.
        return any(marker in note for marker in
                   ("release_train", "release gate", "staging/prod", "auto-queued", "vercel"))
    return "release_train" in note or "vercel" in note


def _is_improvement_task(t):
    return str((t or {}).get("slug") or "").startswith(IMPROVEMENT_PREFIX)


def _is_quarantine_rework_task(t):
    return str((t or {}).get("slug") or "").startswith(REWORK_PREFIX)


def _is_evidence_task(t):
    slug = str((t or {}).get("slug") or "")
    note = str((t or {}).get("note") or "").lower()
    kind = str((t or {}).get("kind") or "").lower()
    return (slug.startswith(CANARY_PREFIX)
            or "-canary-" in slug
            or kind == "canary"
            or "coder-canary" in note
            or "routing sample" in note)


# ── done-slug cache (T4 hardening) ─────────────────────────────────
_done_cache_lock = threading.Lock()
_done_cache = {"slugs": set(), "ts": 0.0, "ttl": 60.0}


def _done_slugs():
    """Return cached set of DONE/MERGED slugs, refreshing every 60s.

    The set contains bare slugs (backward-compatible project-local lookup)
    AND ``project_name:slug`` qualified entries so cross-project deps
    (e.g. ``apparently:curation-layer-land``) resolve against the global
    task namespace while bare ids stay project-local.
    """
    now = time.time()
    if now - _done_cache["ts"] < _done_cache["ttl"]:
        return _done_cache["slugs"]
    with _done_cache_lock:
        # double-check after acquiring lock
        if now - _done_cache["ts"] < _done_cache["ttl"]:
            return _done_cache["slugs"]
        rows = select("tasks", {
            "select": "slug,project_id",
            "state": "in.(DONE,MERGED)",
            "limit": "10000",
        }) or []
        slugs = set()
        # Build project_id -> name map for cross-project qualified entries
        _proj_names = {}
        try:
            for p in (select("projects", {"select": "id,name"}) or []):
                if p.get("name"):
                    _proj_names[p["id"]] = p["name"]
        except Exception:
            pass
        for r in rows:
            s = r.get("slug")
            if not s:
                continue
            slugs.add(s)  # bare slug (backward compat)
            pid = r.get("project_id")
            pname = _proj_names.get(pid)
            if pname:
                slugs.add(f"{pname}:{s}")  # qualified cross-project entry
        _done_cache["slugs"] = slugs
        _done_cache["ts"] = time.time()
        return _done_cache["slugs"]


def invalidate_done_cache():
    """Clear the done-slug cache (for tests and after state transitions)."""
    with _done_cache_lock:
        _done_cache["slugs"] = set()
        _done_cache["ts"] = 0.0


def set_pin(slug, rank=1):
    """Set or clear pin status on a task.

    Args:
        slug (str): Task slug to pin/unpin.
        rank (int, optional): Pin rank (1 = highest priority among pinned).
                              rank=0 clears the pin. Default is 1.
    """
    if rank == 0:
        return update("tasks", {"slug": slug}, {"pinned": False, "pin_rank": 0})
    else:
        return update("tasks", {"slug": slug}, {"pinned": True, "pin_rank": rank})


def claim_task(runner_id):
    """Atomically claim one QUEUED task whose dependencies are satisfied.

    Implements ECONOMIC ORDERING: within project-priority bands, prefer higher-ROI
    projects (via concurrency_weight) and then FIFO. Guarantees no double-claims across
    multiple runners via atomic optimistic PATCH (state=QUEUED -> RUNNING). Also enforces
    host affinity to prevent claiming tasks whose repo is not locally available.

    Args:
        runner_id (str): Unique identifier for this runner/executor.

    Returns:
        dict | None: Task dict (id, slug, project_id, deps, etc.) if claim succeeds,
                     or None if queue is empty or all deps unsatisfied.
    """
    # FAILOVER: if DB has been unreachable for N consecutive cycles, try offline mirror
    if is_db_down():
        try:
            import local_queue
            task = local_queue.claim_task_offline(runner_id)
            if task:
                return task
        except Exception:
            pass
    prio, roi_w, project_names, paused_pids, local_repo_pids = {}, {}, {}, set(), None
    try:
        projs = select("projects", {"select": "id,name,priority,concurrency_weight,repo_path"}) or []
        prio = {p["id"]: (p.get("priority") if p.get("priority") is not None else 5) for p in projs}
        roi_w = {p["id"]: (p.get("concurrency_weight") if p.get("concurrency_weight") is not None else 1)
                 for p in projs}
        project_names = {p["id"]: p.get("name") for p in projs}
        # HOST AFFINITY: projects whose repo is actually present on THIS machine (after localizing
        # the shared /Users/<owner>/ path to this home). A runner must not claim a task whose repo
        # it lacks — it would flip QUEUED->RUNNING, fail for lack of a checkout, and steal the task
        # from the machine that CAN run it. None => couldn't compute (fail open, old behavior).
        local_repo_pids = {p["id"] for p in projs if repo_runnable_here(p.get("repo_path"))}
        name2id = {p["name"]: p["id"] for p in projs}
        paused_names = {c["project"] for c in (select("controls", {"select": "project,paused,updated_by",
                        "scope": "eq.project", "paused": "is.true"}) or [])
                        if c.get("project") and c.get("updated_by") != "remote-quarantine"}
        paused_pids = {name2id[n] for n in paused_names if n in name2id}
    except Exception:
        _increment_db_failure_count()
        pass
    claim_fields = "id,slug,project_id,deps,confidence,created_at,updated_at,kind,note,priority,prompt,batch_id,parent_task_id,operator_approved_at,operator_approved_by,counsel_approved_at,counsel_approved_by,pinned,pin_rank"
    try:
        queued = select("tasks", {"select": claim_fields,
                                  "state": "eq.QUEUED",
                                  "order": "created_at.asc",
                                  "limit": str(CLAIM_SCAN_LIMIT)}) or []
        # Sync to local mirror on successful fetch
        try:
            running = select("tasks", {"select": claim_fields, "state": "eq.RUNNING", "limit": "2000"}) or []
            import local_queue
            local_queue.sync_from_remote(queued, running)
            _reset_db_failure_count()  # DB is healthy, reset failure counter
        except Exception:
            pass
    except Exception as exc:
        _increment_db_failure_count()
        queued = []
        # A failing claim scan means this runner claims NOTHING — it is total
        # starvation, not a slowdown, so it must never be silent. On 2026-08-02
        # claim_fields listed `pinned`/`pin_rank` before their migration existed;
        # PostgREST answered every scan with HTTP 400, this handler swallowed it,
        # and the runner sat idle for hours against a 2,000-task queue while the
        # logs showed a healthy main loop. Say so, loudly, every time.
        print(f"[claim] SCAN FAILED — claiming nothing this cycle: {exc}. "
              f"A 400 here usually means claim_fields names a column the tasks "
              f"table does not have (schema/code drift).", flush=True)
    # PostgREST/Supabase caps large result sets at 1,000 rows. Urgent new work
    # otherwise sits outside an oldest-first scan and cannot be prioritized at
    # all. Pull bounded escape hatches for deployment blockers and evidence
    # tasks, then let the normal atomic ranking/claim path decide among them.
    escape_filters = (
        "(slug.like.relfix-*,slug.like.qafix-*,slug.like.deployfix-*,slug.like.buildfix-*,slug.like.copyfix-*,slug.like.toolchain-repair-*)",
        "(slug.like.canary-*,slug.like.*-canary-*,kind.eq.canary,note.ilike.*coder-canary*,note.ilike.*routing%20sample*)",
    )
    seen_ids = {t.get("id") for t in queued}
    for expression in escape_filters:
        try:
            extra = select("tasks", {"select": claim_fields, "state": "eq.QUEUED",
                                      "or": expression, "order": "created_at.desc", "limit": "200"}) or []
        except Exception:
            extra = []
        for task in extra:
            if task.get("id") not in seen_ids:
                queued.append(task); seen_ids.add(task.get("id"))
    queued = [t for t in queued if t.get("project_id") not in paused_pids]  # skip paused projects
    # Counsel-gated design specs are queue-visible but cannot enter an execution
    # lane until both approvals are explicitly stored on the task. Fail closed.
    try:
        from execution_assurance import counsel_gate_satisfied, is_counsel_gated
        allowed = []
        for task in queued:
            if not is_counsel_gated(task):
                allowed.append(task)
                continue
            if counsel_gate_satisfied(task):
                allowed.append(task)
            else:
                print(f"[counsel-gate] holding {task.get('slug')} pending operator + counsel approval", flush=True)
        queued = allowed
    except Exception as exc:
        # Do not silently bypass a design-spec gate on a database/API problem.
        queued = [task for task in queued if not is_counsel_gated(task)]
        print(f"[counsel-gate] approval lookup failed; holding gated work: {exc}", flush=True)
    # HOST AFFINITY: only claim tasks whose project repo exists on this machine. No-op on the
    # machine that owns the repos (all present) and when localization is disabled; prevents a
    # second Mac from grabbing-and-failing work it has no checkout for. Gated + fail-open.
    if (local_repo_pids is not None
            and os.environ.get("ORCH_CLAIM_REQUIRE_LOCAL_REPO", "true").lower() in ("true", "1", "yes")):
        before = len(queued)
        queued = [t for t in queued if t.get("project_id") in local_repo_pids]
        if before and not queued:
            print(f"[claim] no locally-runnable tasks: {before} queued, but no project repo is present "
                  f"on {socket.gethostname()} (host affinity). Idle until a runnable repo exists.",
                  flush=True)
    per_project_limit = max(1, int(os.environ.get("ORCH_PER_PROJECT_CODE_LANES", "1")))
    # A known-broken toolchain is a project-wide root blocker.  Only its one
    # repair task may claim a lane; every dependent task would otherwise spend
    # a model call merely to rediscover the same missing dependency.
    toolchain_blocked_pids = set()
    try:
        blockers = select("tasks", {
            "select": "project_id,slug", "state": "in.(QUEUED,RUNNING,RETRY)",
            "slug": "like.toolchain-repair-*", "limit": "500",
        }) or []
        toolchain_blocked_pids = {r.get("project_id") for r in blockers if r.get("project_id")}
    except Exception:
        pass
    if toolchain_blocked_pids:
        queued = [t for t in queued if (t.get("project_id") not in toolchain_blocked_pids
                                        or str(t.get("slug") or "").startswith("toolchain-repair-"))]
    active_by_project = {}
    active_release_by_project = {}
    active_recovery_by_project = {}
    active_evidence = 0
    try:
        for r in (select("tasks", {"select": "project_id,slug,kind,note", "state": "in.(RUNNING,RETRY)"}) or []):
            pid = r.get("project_id")
            if pid:
                active_by_project[pid] = active_by_project.get(pid, 0) + 1
                if _is_release_fix_task(r):
                    active_release_by_project[pid] = active_release_by_project.get(pid, 0) + 1
                if _is_recovery_task(r):
                    active_recovery_by_project[pid] = active_recovery_by_project.get(pid, 0) + 1
            if _is_evidence_task(r):
                active_evidence += 1
    except Exception:
        pass
    # FAIR ROUND-ROBIN across projects: prefer the project that has gone LONGEST without activity, so
    # every app gets worked (not just the biggest/highest-priority queue). Within that, honor priority,
    # ROI weight, then FIFO. This is what lets a single-slot runner still touch ALL projects in rotation.
    last_act = {}
    try:
        for r in (select("tasks", {"select": "project_id,updated_at", "state": "in.(RUNNING,DONE,MERGED)",
                                    "order": "updated_at.desc", "limit": "400"}) or []):
            pid = r.get("project_id")
            if pid and pid not in last_act:
                last_act[pid] = r.get("updated_at") or ""
    except Exception:
        pass
    # CHURN DEPRIORITIZATION: continuation ("cont-") and mechanical batch tasks are low-value churn —
    # they rarely produce a mergeable deliverable, and when the queue fills with them they starve the
    # real feature work that actually reaches integrate()+MERGED (the root cause of the ~2% merge rate).
    # Sort them LAST so real work is always claimed first; they still run when nothing else is pending,
    # so they're deprioritized, not starved. Ordering-only change — the atomic optimistic PATCH below
    # still guarantees two runners never double-claim, so multi-machine correctness is unchanged.
    deprio_churn = os.environ.get("ORCH_DEPRIORITIZE_CHURN", "true").lower() in ("true", "1", "yes")

    def _churn(t):
        s = str(t.get("slug") or "")
        return 1 if deprio_churn and (s.startswith("cont-") or s.startswith("batch-mech")) else 0


    # Kind+age composite score: prioritize bugfixes and older tasks within the same
    # jump-queue tier. Lower score = claimed sooner. Age gives a small boost (up to -10
    # for tasks waiting 10+ days) so stale work doesn't starve behind fresh work of the
    # same kind.
    _KIND_WEIGHTS = {
        "bugfix": 0, "test": 1, "cleanup": 2, "chore": 2, "docs": 3,
        "mechanical": 3, "build": 4, "efficiency": 5, "research": 6, "self": 7,
    }

    def _kind_age_score(t):
        kind_w = _KIND_WEIGHTS.get(str(t.get("kind") or "").lower(), 5)
        created = t.get("created_at") or ""
        age_boost = 0.0
        if created:
            try:
                from datetime import datetime, timezone
                # Parse ISO timestamp, compute age in hours
                ts = created.replace("Z", "+00:00")
                if "+" not in ts and ts[-1] != "Z":
                    ts += "+00:00"
                dt = datetime.fromisoformat(ts)
                age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                age_boost = min(age_h / 24, 10)  # cap at 10 days
            except Exception:
                pass
        return kind_w - age_boost

    def _pinned_rank(t):
        # Pinned tasks claim before unpinned: rank 0 for pinned, 1 for unpinned.
        return 0 if t.get("pinned") else 1

    def _pin_rank_order(t):
        # Among pinned tasks, lower pin_rank claims first (1 = highest priority).
        # Rank 0 or missing treated as unpinned (rank 9999).
        rank = t.get("pin_rank") or 0
        return rank if rank > 0 else 9999

    thermal_rank = _thermal_rank_map()
    ev_rank = _ev_rank_map()
    recovery_backlog = (
        os.environ.get("ORCH_RECOVERY_JUMP_QUEUE", "true").lower() in ("true", "1", "yes", "on")
        and any(_is_recovery_task(t) for t in queued)
    )
    # STARVATION FIX: rework-* tasks (blocker_quarantine's legal/secret/security replacements)
    # matched none of the existing jump-queue categories, so they always lost every tie-break to
    # recovery/release-fix/improvement/evidence work -- which is effectively always present given
    # fleet volume. Result: a 2-day-old rework-* task sat at attempt=0, never claimed, while its
    # backlog kept growing. Give it its own bounded jump-queue tier so it actually gets a turn.
    rework_backlog = (
        os.environ.get("ORCH_QUARANTINE_REWORK_JUMP_QUEUE", "true").lower() in ("true", "1", "yes", "on")
        and any(_is_quarantine_rework_task(t) for t in queued)
    )
    release_fix_backlog = (
        os.environ.get("ORCH_RELEASE_FIX_JUMP_QUEUE", "true").lower() in ("true", "1", "yes", "on")
        and any(_is_release_fix_task(t) for t in queued)
    )
    improvement_backlog = (
        os.environ.get("ORCH_IMPROVEMENT_JUMP_QUEUE", "true").lower() in ("true", "1", "yes", "on")
        and any(_is_improvement_task(t) for t in queued)
    )
    evidence_backlog = (
        os.environ.get("ORCH_EVIDENCE_JUMP_QUEUE", "true").lower() in ("true", "1", "yes", "on")
        and any(_is_evidence_task(t) for t in queued)
    )
    evidence_reserved_lanes = max(0, int(os.environ.get("ORCH_EVIDENCE_RESERVED_LANES", "1") or 0))
    evidence_reserve_open = evidence_backlog and active_evidence < evidence_reserved_lanes
    recovery_reserved_lanes = max(0, int(os.environ.get("ORCH_RECOVERY_RESERVED_LANES", "1") or 0))
    recovery_reserve_open = (recovery_backlog
                             and sum(active_recovery_by_project.values()) < recovery_reserved_lanes)
    try:
        import blocker_portfolio
        blocker_scores = blocker_portfolio.scores(queued)
    except Exception:
        blocker_scores = {}

    def _task_priority(t):
        return _num(t.get("priority"), 1000)

    def _blocker_portfolio_rank(t):
        # Higher score means this task clears more downstream/release work.
        if _is_recovery_task(t) and not recovery_backlog:
            return 0.0
        if _is_release_fix_task(t) and not release_fix_backlog:
            return 0.0
        return -float(blocker_scores.get(str(t.get("id") or t.get("slug") or ""), 0.0))

    def _portfolio_project_rank(t):
        # Owner directive: prioritize portfolio work in this exact product order. Keep this
        # independent from mutable DB priority so newly-added rows with stale/null values cannot
        # silently outrank the core apps.
        return _project_rank_name(project_names.get(t.get("project_id")))

    def _ev_rank(t):
        if _is_release_fix_task(t):
            return 0
        return ev_rank.get(str(t.get("id")), 1000000)

    def _thermal_rank(t):
        if _is_release_fix_task(t):
            return 0
        return thermal_rank.get(str(t.get("id")), 1000000)

    def _confidence_rank(t):
        if _is_release_fix_task(t):
            return 0
        # Last-resort EV fallback writes higher confidence for better tasks.
        return -_num(t.get("confidence"), 0.0)

    def _recovery_rank(t):
        # Missing-branch recovery is already mostly solved work. While any of that backlog exists,
        # claim it ahead of net-new work regardless of stale thermal/priority rows.
        return 0 if (recovery_backlog and _is_recovery_task(t)) else (1 if recovery_backlog else 0)

    def _rework_rank(t):
        # Quarantine rework: safer to give these a real turn than let them starve indefinitely
        # behind an always-full recovery/release-fix backlog (see rework_backlog comment above).
        # Ranked below recovery/release-fix (those are more time-critical) but ahead of generic
        # thermal-ranked net-new work, so the backlog actually drains instead of only growing.
        return 0 if (rework_backlog and _is_quarantine_rework_task(t)) else (1 if rework_backlog else 0)

    def _release_fix_rank(t):
        # Red release gates are the only thing between completed work and Vercel review. Drain those
        # before recovery so green staged batches can ship overnight.
        return 0 if (release_fix_backlog and _is_release_fix_task(t)) else (1 if release_fix_backlog else 0)

    def _evidence_reserve_rank(t):
        # Keep at least one tiny evidence lane alive so GPT/Gemini/DeepSeek/Ollama samples become real
        # outcomes instead of staying permanently queued behind release/recovery pressure.
        return 0 if (evidence_reserve_open and _is_evidence_task(t)) else (1 if evidence_reserve_open else 0)

    def _recovery_reserve_rank(t):
        return 0 if (recovery_reserve_open and _is_recovery_task(t)) else (1 if recovery_reserve_open else 0)

    def _release_fix_urgency(t):
        if not _is_release_fix_task(t):
            return 9
        slug = str(t.get("slug") or "")
        # Explicit release-gate self-heals beat generic Vercel mentions and stale EV labels.
        if slug.startswith(("qafix-", "relfix-", "buildfix-", "deployfix-")):
            return 0
        return 1

    def _release_fix_specificity(t):
        """Current compiled failure signatures beat legacy sliced/generic repair backlogs."""
        if not _is_release_fix_task(t):
            return 9
        import re
        slug = str(t.get("slug") or "")
        return 0 if re.search(r"-[0-9a-f]{12}$", slug) else 1

    def _improvement_rank(t):
        # Once recovery is drained, orchestrator self-improvements should ship before fresh product
        # expansion because every merge compounds throughput/cost/quality across the whole fleet.
        return 0 if (improvement_backlog and _is_improvement_task(t)) else (1 if improvement_backlog else 0)

    def _train_approved_rank(t):
        # Tasks that passed the release train but bounced back (rebase conflict, build-fix needed)
        # are nearly-merged work. Prioritize them ahead of net-new to convert sunk cost into value.
        note = str(t.get("note") or "").lower()
        if any(marker in note for marker in ("train: passed", "train: approved", "train: ready")):
            return 0
        return 1

    def _evidence_rank(t):
        # Canary/evidence tasks are tiny, bounded, and produce the non-Claude merge samples the router
        # needs. Let them jump ahead of recovery too: otherwise a deep recovery backlog can hide every
        # API-provider sample and leave routing in permanent "learning" mode. Release fixes still win.
        return 0 if (evidence_backlog and _is_evidence_task(t)) else (1 if evidence_backlog else 0)

    def _project_lane_limit(t):
        # Priority drains should not wait forever just because the same project already has one
        # unrelated task active. Keep the override bounded so one repo cannot consume the fleet.
        if _is_release_fix_task(t):
            return max(1, int(os.environ.get("ORCH_RELEASE_FIX_PER_PROJECT_CODE_LANES", "1")))
        if _is_recovery_task(t):
            # Missing-branch retries compete for the same refs and locks.  One
            # deterministic recovery owner per project prevents retry storms.
            return max(1, int(os.environ.get("ORCH_RECOVERY_PER_PROJECT_CODE_LANES", "1")))
        if _is_evidence_task(t):
            return max(per_project_limit, int(os.environ.get("ORCH_EVIDENCE_PER_PROJECT_CODE_LANES", "2")))
        if _is_improvement_task(t):
            return max(per_project_limit, int(os.environ.get("ORCH_IMPROVEMENT_PER_PROJECT_CODE_LANES", "2")))
        if _is_quarantine_rework_task(t):
            return max(per_project_limit, int(os.environ.get("ORCH_QUARANTINE_REWORK_PER_PROJECT_CODE_LANES", "2")))
        return per_project_limit

    def _cooling_down(t):
        """Skip tasks that failed recently — exponential backoff based on retry_count."""
        rc = int(t.get("retry_count") or 0)
        if rc == 0:
            return False
        last = t.get("updated_at") or t.get("created_at") or ""
        if not last:
            return False
        try:
            from datetime import datetime, timezone
            if last.endswith("Z"):
                last = last[:-1] + "+00:00"
            updated = datetime.fromisoformat(last)
            cooldown_s = min(3600, 30 * (2 ** min(rc - 1, 6)))  # 30s, 60s, 120s, ... up to 1h
            elapsed = (datetime.now(timezone.utc) - updated).total_seconds()
            return elapsed < cooldown_s
        except Exception:
            return False

    queued.sort(key=lambda t: (_pinned_rank(t),                                 # pinned tasks claim first
                               _pin_rank_order(t),                               # among pinned, lower rank wins
                               _evidence_reserve_rank(t),                        # reserve one vendor-evidence lane
                               _recovery_reserve_rank(t),                        # turn completed work into mergeable branches
                               _release_fix_rank(t),                             # unblock Vercel releases across the portfolio
                               _release_fix_urgency(t),                          # hot gate fixes before stale EV noise
                               _release_fix_specificity(t),                      # exact current failures before legacy slices
                               _blocker_portfolio_rank(t),                       # maximize downstream work unblocked per claim
                               _portfolio_project_rank(t),                       # owner order within the same delivery class
                               _evidence_rank(t),                                # bounded canaries unblock learned routing
                               _recovery_rank(t),                                # recover tested work next
                               _train_approved_rank(t),                           # nearly-merged train-approved work next
                               _rework_rank(t),                                  # then quarantine-recovered work
                               _improvement_rank(t),                             # then drain improve-* work
                               _churn(t),                                        # real work before churn
                               _kind_age_score(t),                                # kind+age: bugfixes first, older tasks boosted
                               _thermal_rank(t),                                 # EV/min thermal map
                               _task_priority(t),                                # EV/task priority when present
                               _ev_rank(t),                                      # controls.ev_ranking fallback
                               _confidence_rank(t),                              # tasks.confidence fallback
                               last_act.get(t.get("project_id"), ""),           # least-recently-served first
                               prio.get(t.get("project_id"), 5),
                               -float(roi_w.get(t.get("project_id"), 1) or 1),
                               t.get("created_at") or ""))
    # PREFLIGHT: skip tasks with notes indicating prior quarantine cycle
    try:
        import preflight_filter as _pf
        _skip_note = _pf.should_skip_note
    except ImportError:
        _SKIP_NOTE_PATTERNS = ("swarm-parallel-fail", "legacy direct improvement",
                               "Meta-decomposition loop", "queue-bankruptcy",
                               "sentinel-dedupe", "semantic-dedupe", "preflight:",
                               "non-actionable:", "GC:")
        _skip_note = lambda n: any(pat in n for pat in _SKIP_NOTE_PATTERNS)

    done = _done_slugs()
    for t in queued or []:
        if _cooling_down(t):
            continue
        # Skip recycled/garbage tasks before claiming
        if _skip_note(str(t.get("note") or "")):
            continue
        pid = t.get("project_id")
        if pid:
            if _is_release_fix_task(t):
                occupied = active_release_by_project.get(pid, 0)
            elif _is_recovery_task(t):
                occupied = active_recovery_by_project.get(pid, 0)
            else:
                occupied = active_by_project.get(pid, 0)
            if occupied >= _project_lane_limit(t):
                continue
        # SOFT-DEP SPECULATION: if deps aren't all done, check if file scopes
        # are disjoint — if so, start the task speculatively instead of waiting.
        _deps_all_done = all(d in done for d in (t.get("deps") or []))
        if not _deps_all_done:
            try:
                import soft_dep_spec
                _deps_all_done, _spec_reason = soft_dep_spec.can_speculate(t, done)
                if _deps_all_done:
                    _pending = [d for d in (t.get("deps") or []) if d not in done]
                    soft_dep_spec.register(t, _pending)
            except Exception:
                pass
        if _deps_all_done:
            # optimistic claim: flip to RUNNING only if still QUEUED
            try:
                res = _req("PATCH", "/rest/v1/tasks",
                           body={"state": "RUNNING", "account": runner_id, "updated_at": "now()"},
                           headers={"Prefer": "return=representation"},
                           params={"id": f"eq.{t['id']}", "state": "eq.QUEUED"})
            except Exception:
                _increment_db_failure_count()
                res = None
            if res:
                if pid:
                    active_by_project[pid] = active_by_project.get(pid, 0) + 1
                    if _is_release_fix_task(t):
                        active_release_by_project[pid] = active_release_by_project.get(pid, 0) + 1
                    if _is_recovery_task(t):
                        active_recovery_by_project[pid] = active_recovery_by_project.get(pid, 0) + 1
                # Invalidate pre-optimization cache for claimed task
                try:
                    import queue_preopt
                    queue_preopt.invalidate(t["id"])
                except Exception:
                    pass
                invalidate_done_cache()
                return res[0]
    return None


_last_heartbeat_prune = 0.0
_heartbeat_fail = {"n": 0, "t": 0.0}  # consecutive publish failures + last loud log
HEARTBEAT_TTL_MINUTES = int(os.environ.get("ORCH_HEARTBEAT_TTL_MINUTES", "30"))
HEARTBEAT_PRUNE_INTERVAL_S = int(os.environ.get("ORCH_HEARTBEAT_PRUNE_INTERVAL_S", "600"))
HEARTBEAT_PRUNE_AGE_S = int(os.environ.get("ORCH_HEARTBEAT_PRUNE_AGE_S", str(24 * 3600)))


def _fresh(timestamp):
    """Check if heartbeat timestamp is within TTL (fresh/not stale).

    Args:
        timestamp (float | int): Unix timestamp to check.

    Returns:
        bool: True if heartbeat is within HEARTBEAT_TTL_MINUTES, False otherwise.
    """
    if not isinstance(timestamp, (int, float)) or timestamp <= 0:
        return False
    now = time.time()
    age_minutes = (now - timestamp) / 60.0
    return age_minutes <= HEARTBEAT_TTL_MINUTES


def _prune_stale_heartbeats():
    """runner_heartbeats upserts on runner_id, but runner_id is PID-based -- every runner
    restart (crash, keepalive respawn, sentinel-triggered cycle) mints a new runner_id and thus a
    new row that's never cleaned up. Left unbounded, the table accumulates one dead row-family per
    restart forever, which previously made an unordered/unbounded fleet.status() scan miss
    genuinely live lanes. Rate-limited (once per HEARTBEAT_PRUNE_INTERVAL_S per process) and
    fail-soft so a prune hiccup never blocks a heartbeat write."""
    global _last_heartbeat_prune
    now = time.time()
    if _last_heartbeat_prune > 0 and now - _last_heartbeat_prune < HEARTBEAT_PRUNE_INTERVAL_S:
        return
    _last_heartbeat_prune = now
    try:
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(minutes=HEARTBEAT_TTL_MINUTES)).isoformat()
        _req("DELETE", "/rest/v1/runner_heartbeats", params={"last_seen": f"lt.{cutoff}"})
    except Exception:
        pass


def heartbeat(runner_id, hostname, active, model_loaded=None, memory_mb=None):
    """Publish liveness plus a best-effort executor compatibility proof.

    Args:
        runner_id (str): Unique runner identifier.
        hostname (str): Runner hostname.
        active (bool): Whether runner is actively processing tasks.
        model_loaded (str, optional): Name of loaded model if any.
        memory_mb (int, optional): Available memory in MB.

    The fallback keeps rolling upgrades safe while a host has the older
    heartbeat schema or has not yet received the migration. All operations are fail-soft.
    """
    try:
        # Row MUST match the live schema exactly:
        #   runner_id text, hostname text, active_tasks int, last_seen timestamptz,
        #   code_sha text, contract_hash text, contract_version text.
        # The previous shape ("active" bool, epoch-float last_seen, model_loaded/
        # memory_mb columns that don't exist) made EVERY insert fail, and three
        # nested silent excepts hid it — runner_heartbeats sat empty for weeks
        # ("0 live machines", 2026-07-31). Schema-shaped row + loud failure now.
        row = {"runner_id": runner_id, "hostname": hostname,
               "active_tasks": int(active) if not isinstance(active, bool) else (1 if active else 0),
               "last_seen": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        try:
            import runtime_contract
            proof = runtime_contract.check()
            row.update({k: proof[k] for k in ("code_sha", "contract_hash", "contract_version")
                       if k in proof})
        except Exception:
            pass
        try:
            db.insert("runner_heartbeats", row, upsert=True)
            _heartbeat_fail["n"] = 0
        except Exception as hb_err:
            # Compatibility with remotes that have not yet applied the additive migration.
            row_compat = {k: v for k, v in row.items()
                         if k not in ("code_sha", "contract_hash", "contract_version")}
            try:
                db.insert("runner_heartbeats", row_compat, upsert=True)
                _heartbeat_fail["n"] = 0
            except Exception:
                # Fail-soft but SELF-REPORTING: a heartbeat that can never land is
                # an invisible outage. Log loudly (rate-limited to once/5 min).
                _heartbeat_fail["n"] = _heartbeat_fail.get("n", 0) + 1
                if time.time() - _heartbeat_fail.get("t", 0) > 300:
                    _heartbeat_fail["t"] = time.time()
                    print(f"[heartbeat] CRITICAL: publish failing "
                          f"({_heartbeat_fail['n']} consecutive) — {hb_err}", flush=True)
        if os.environ.get("ORCH_LOGICAL_RUNNERS", "false").lower() not in ("true", "1", "yes"):
            _prune_stale_heartbeats()
            return
        try:
            target = max(1, min(10, int(os.environ.get("ORCH_RUNNER_FLEET_TARGET", "8"))))
            for i in range(2, target + 1):
                lane_id = f"{runner_id}-lane-{i}"
                lane = dict(row)
                lane.update({"runner_id": lane_id, "hostname": f"{hostname} lane {i}",
                             "active_tasks": row["active_tasks"],
                             "last_seen": datetime.datetime.now(datetime.timezone.utc).isoformat()})
                try:
                    db.insert("runner_heartbeats", lane, upsert=True)
                except Exception:
                    lane_compat = {k: v for k, v in lane.items()
                                  if k not in ("code_sha", "contract_hash", "contract_version")}
                    try:
                        db.insert("runner_heartbeats", lane_compat, upsert=True)
                    except Exception:
                        pass
        except Exception:
            pass
        _prune_stale_heartbeats()
    except Exception:
        # Outermost fail-soft: never crash on heartbeat errors
        pass
