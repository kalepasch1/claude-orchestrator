#!/usr/bin/env python3
"""
db.py - tiny Supabase (PostgREST) client over urllib. No third-party deps.
The runner uses the SERVICE ROLE key so it bypasses RLS. Set:
    SUPABASE_URL=https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY=<service-role key>   (keep secret; never ship to the web app)
"""
import os, re, json, socket, time, datetime, threading, urllib.request, urllib.parse, urllib.error

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
    """Prepend standard macOS tool directories to PATH if missing.

    Ensures git, python, node, and other CLI tools are discoverable even when
    the runner is launched via launchd (which inherits a minimal PATH)."""
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

# ── SECRET HYGIENE (2026-07-15) ──────────────────────────────────────────────
# Redact API keys, service keys, and other secrets from strings before they are
# stored in the database (task notes, log_tail, error messages). Prevents secrets
# from leaking into the tasks table via raw command output or tracebacks.
_SECRET_PATTERNS = re.compile(
    r"("
    # Anthropic API keys (sk-ant-api03-...)
    r"sk-ant-api\S{10,}"
    r"|"
    # Supabase service role keys (eyJ...)
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"
    r"|"
    # Generic long API key patterns (key=..., token=..., secret=..., password=...)
    r"(?:(?:api[_-]?key|secret[_-]?key|service[_-]?key|token|password|credential)"
    r"\s*[=:]\s*['\"]?)([A-Za-z0-9_/+\-.]{16,})"
    r"|"
    # OpenAI keys (sk-...)
    r"sk-[A-Za-z0-9]{20,}"
    r"|"
    # Generic bearer tokens
    r"Bearer\s+[A-Za-z0-9_\-/.]{20,}"
    r")",
    re.I,
)


def redact_secrets(text):
    """Replace secret-like patterns in *text* with [REDACTED]. Fail-soft: returns
    original text on any error so it never blocks writes."""
    if not text or not isinstance(text, str):
        return text
    try:
        return _SECRET_PATTERNS.sub("[REDACTED]", text)
    except Exception:
        return text


_TASK_SENSITIVE_FIELDS = {"note", "log_tail"}
HTTP_RETRIES = int(os.environ.get("ORCH_SUPABASE_RETRIES", "3") or 3)
HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504, 521, 522, 523}  # incl. Cloudflare origin-down codes so monitors ride through Supabase capacity blips instead of silently no-op'ing

# DB Failover state: track consecutive DB failures to trigger offline mode
DB_DOWN_THRESHOLD = int(os.environ.get("SENTINEL_DB_DOWN_THRESHOLD", "3"))
_db_failure_count = 0
_db_failure_lock = threading.Lock()


def _reset_db_failure_count():
    """Reset failure counter on successful DB operation."""
    global _db_failure_count
    with _db_failure_lock:
        _db_failure_count = 0


def _increment_db_failure_count():
    """Increment failure counter on DB operation failure."""
    global _db_failure_count
    with _db_failure_lock:
        _db_failure_count += 1
        return _db_failure_count


def is_db_down():
    """Check if DB is considered down based on failure count."""
    with _db_failure_lock:
        return _db_failure_count >= DB_DOWN_THRESHOLD


# Thread-safe per-slug dedup lock pool (prevents same-machine race conditions)
_DEDUP_LOCKS = {}
_DEDUP_LOCKS_LOCK = threading.Lock()

class _dedup_lock:
    """Per-key lock for serializing task inserts with the same slug."""
    def __init__(self, key):
        self.key = key
    def __enter__(self):
        with _DEDUP_LOCKS_LOCK:
            if self.key not in _DEDUP_LOCKS:
                _DEDUP_LOCKS[self.key] = threading.Lock()
            self._lock = _DEDUP_LOCKS[self.key]
        self._lock.acquire()
        return self
    def __exit__(self, *args):
        self._lock.release()
        # Clean up to prevent memory leak (only if no one else is waiting)
        with _DEDUP_LOCKS_LOCK:
            if self.key in _DEDUP_LOCKS and not _DEDUP_LOCKS[self.key].locked():
                try:
                    del _DEDUP_LOCKS[self.key]
                except KeyError:
                    pass
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
    """Map project name to priority rank (lower = higher priority).

    Args:
        name: Project name or None.

    Returns:
        int: Priority rank (1-9); unknown projects default to 9 (lowest).
    """
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
    # edge failures.  Writes deliberately remain single-attempt: retrying an
    # uncertain POST could create duplicate work when the first request reached
    # PostgREST but its response was lost.
    attempts = HTTP_RETRIES + 1 if method == "GET" else 1
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
                return None
            if method != "GET" or e.code not in HTTP_RETRY_STATUSES or attempt >= attempts - 1:
                raise
            time.sleep(min(12, 2 ** attempt) + (0.1 * attempt))
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            if method != "GET" or attempt >= attempts - 1:
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


def insert(table, row, upsert=False):
    # SECRET HYGIENE: redact secrets from sensitive fields on task insert too.
    if table == "tasks" and isinstance(row, dict):
        # The database contract is a non-null array. Normalizing at the sole
        # enqueue choke point preserves the semantic meaning of SQL NULL
        # (independent work) without relying on callers to know storage details.
        from execution_assurance import normalize_deps
        row["deps"] = normalize_deps(row.get("deps"))
        for field in _TASK_SENSITIVE_FIELDS:
            if field in row and isinstance(row[field], str):
                row[field] = redact_secrets(row[field])
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
            pass
        # Process-level lock: serialize inserts with the same slug on this machine.
        # Cross-machine races still possible but reduced (the sentinel catches the rest).
        with _dedup_lock(_dedup_key):
            try:
                # Re-check after lock (another thread may have inserted while we waited)
                existing = select("tasks", {
                    "select": "id,slug,state",
                    "project_id": f"eq.{row['project_id']}",
                    "slug": f"eq.{row['slug']}",
                    "state": "in.(QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED,DECOMPOSED)",
                    "limit": "1"}) or []
                if existing:
                    return existing
            except Exception:
                pass
    h = {"Prefer": "return=representation" + (",resolution=merge-duplicates" if upsert else "")}
    try:
        result = _req("POST", f"/rest/v1/{table}", body=row, headers=h)
    except urllib.error.HTTPError as e:
        # 409 = duplicate key: the row already exists, so the write intent is satisfied. A retried
        # task re-inserting an outcome/row used to raise HTTP 409 -> "runner exception: Conflict" ->
        # BLOCKED, which stalled merges. Retry idempotently as an upsert; if that still can't apply,
        # swallow it so a duplicate never crashes the task.
        if e.code == 409:
            if upsert:
                return None
            try:
                return _req("POST", f"/rest/v1/{table}",
                            body=row, headers={"Prefer": "return=representation,resolution=merge-duplicates"})
            except Exception:
                return None
        raise

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
    # SECRET HYGIENE: redact secrets from sensitive task fields before DB write.
    # Applied here (the single choke point for all task updates) so every caller
    # — set_state, blocker_quarantine, error-retry, etc. — gets automatic protection.
    if table == "tasks" and isinstance(patch, dict):
        for field in _TASK_SENSITIVE_FIELDS:
            if field in patch and isinstance(patch[field], str):
                patch[field] = redact_secrets(patch[field])
    params = {k: f"eq.{v}" for k, v in match.items()}
    try:
        return _req("PATCH", f"/rest/v1/{table}", body=patch,
                    headers={"Prefer": "return=representation"}, params=params)
    except urllib.error.HTTPError as e:
        # 409 = a concurrent write (the two Macs racing the same row). The write intent is already
        # satisfied by the other writer, so treat it as a no-op instead of letting it bubble up as a
        # "runner exception: HTTP 409 conflict" that terminally BLOCKS the task (this froze 200+ tasks).
        if e.code == 409:
            return None
        raise


def rpc(fn, args):
    """Call a PostgREST RPC function *fn* with *args* dict and return the result."""
    return _req("POST", f"/rest/v1/rpc/{fn}", body=args)


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
    claim_fields = "id,slug,project_id,deps,confidence,created_at,updated_at,kind,note,priority,prompt,batch_id,parent_task_id,operator_approved_at,operator_approved_by,counsel_approved_at,counsel_approved_by"
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
    except Exception:
        _increment_db_failure_count()
        queued = []
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

    def _cooling_down(t):
        """Avoid instantly reclaiming work a worker deliberately deferred.

        The old QUEUED -> RUNNING hot loop could reclaim the same conflict/toolchain
        hold several times a minute, consuming a lane without doing useful work.
        """
        note = str(t.get("note") or "").lower()
        seconds = 0
        if note.startswith("held: project toolchain not ready"):
            seconds = int(os.environ.get("ORCH_TOOLCHAIN_RECLAIM_COOLDOWN_S", "300"))
        elif note.startswith(("conflict-predictor: deferring", "portfolio-plan deferred")):
            seconds = int(os.environ.get("ORCH_CONFLICT_RECLAIM_COOLDOWN_S", "90"))
        elif note.startswith(("fleet-topology: redirecting", "ensemble-predictor:")):
            seconds = int(os.environ.get("ORCH_ROUTING_RECLAIM_COOLDOWN_S", "60"))
        if not seconds or not t.get("updated_at"):
            return False
        try:
            updated = datetime.datetime.fromisoformat(str(t["updated_at"]).replace("Z", "+00:00"))
            return (datetime.datetime.now(datetime.timezone.utc) - updated).total_seconds() < seconds
        except Exception:
            return False


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
    recovery_reserved_lanes = max(0, int(os.environ.get("ORCH_RECOVERY_RESERVED_LANES", "0") or 0))
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

    queued.sort(key=lambda t: (_evidence_reserve_rank(t),                        # reserve one vendor-evidence lane
                               _recovery_reserve_rank(t),                        # turn completed work into mergeable branches
                               _release_fix_rank(t),                             # unblock Vercel releases across the portfolio
                               _release_fix_urgency(t),                          # hot gate fixes before stale EV noise
                               _release_fix_specificity(t),                      # exact current failures before legacy slices
                               _blocker_portfolio_rank(t),                       # maximize downstream work unblocked per claim
                               _portfolio_project_rank(t),                       # owner order within the same delivery class
                               _evidence_rank(t),                                # bounded canaries unblock learned routing
                               _recovery_rank(t),                                # recover tested work next
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
        if all(d in done for d in (t.get("deps") or [])):
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
HEARTBEAT_PRUNE_INTERVAL_S = int(os.environ.get("ORCH_HEARTBEAT_PRUNE_INTERVAL_S", "600"))
HEARTBEAT_PRUNE_AGE_S = int(os.environ.get("ORCH_HEARTBEAT_PRUNE_AGE_S", str(24 * 3600)))


def _prune_stale_heartbeats():
    """runner_heartbeats upserts on runner_id, but runner_id is PID-based -- every runner
    restart (crash, keepalive respawn, sentinel-triggered cycle) mints a new runner_id and thus a
    new row that's never cleaned up. Left unbounded, the table accumulates one dead row-family per
    restart forever, which previously made an unordered/unbounded fleet.status() scan miss
    genuinely live lanes. Rate-limited (once per HEARTBEAT_PRUNE_INTERVAL_S per process) and
    fail-soft so a prune hiccup never blocks a heartbeat write."""
    global _last_heartbeat_prune
    now = time.time()
    if now - _last_heartbeat_prune < HEARTBEAT_PRUNE_INTERVAL_S:
        return
    _last_heartbeat_prune = now
    try:
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(seconds=HEARTBEAT_PRUNE_AGE_S)).isoformat()
        _req("DELETE", "/rest/v1/runner_heartbeats", params={"last_seen": f"lt.{cutoff}"})
    except Exception:
        pass


def heartbeat(runner_id, hostname, active):
    """Publish liveness plus a best-effort executor compatibility proof.

    The fallback keeps rolling upgrades safe while a host has the older
    heartbeat schema or has not yet received the migration.
    """
    row = {"runner_id": runner_id, "hostname": hostname, "active_tasks": active,
           "last_seen": "now()"}
    try:
        import runtime_contract
        proof = runtime_contract.check()
        row.update({k: proof[k] for k in ("code_sha", "contract_hash", "contract_version")})
    except Exception:
        pass
    try:
        insert("runner_heartbeats", row, upsert=True)
    except Exception:
        # Compatibility with remotes that have not yet applied the additive migration.
        row = {k: v for k, v in row.items()
               if k not in ("code_sha", "contract_hash", "contract_version")}
        insert("runner_heartbeats", row, upsert=True)
    if os.environ.get("ORCH_LOGICAL_RUNNERS", "true").lower() not in ("true", "1", "yes"):
        return
    try:
        target = max(1, min(10, int(os.environ.get("ORCH_RUNNER_FLEET_TARGET", "8"))))
        for i in range(2, target + 1):
            lane_id = f"{runner_id}-lane-{i}"
            lane = dict(row)
            lane.update({"runner_id": lane_id, "hostname": f"{hostname} lane {i}",
                         "active_tasks": 1 if active >= i else 0, "last_seen": "now()"})
            try:
                insert("runner_heartbeats", lane, upsert=True)
            except Exception:
                insert("runner_heartbeats", {k: v for k, v in lane.items()
                                               if k not in ("code_sha", "contract_hash", "contract_version")},
                       upsert=True)
    except Exception:
        pass
    _prune_stale_heartbeats()
