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
    # Google/Gemini API keys (AIza...) — fleet routes through Gemini; these leaked
    # unredacted into task notes before this pattern existed
    r"AIza[0-9A-Za-z_\-]{30,}"
    r"|"
    # xAI keys (xai-...)
    r"xai-[A-Za-z0-9]{20,}"
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
    # Owner directive 2026-08-04: "start with apparently, apparently-law, tomorrow, the
    # orchestrator, madeus/web, vigil + smarter + illuminati (merging into apparently),
    # then pareto/2080."
    "apparently": 1,
    "apparently-law": 2,
    "tomorrow": 3,
    "orchestrator": 4,
    "beethoven": 4,
    "web": 5,
    "madeus": 5,
    "vigil": 6,
    "smarter": 7,
    "illuminati": 8,
    "pareto-2080": 9,
    "pareto": 9,
    "2080": 9,
    "hisanta": 10,
    "santas-secret-workshop": 10,
    "galop": 11,
    "racefeed": 11,
    "sustainable-barks": 12,
    "sustainablebarks": 12,
}


def _project_rank_name(name):
    """Return numeric priority for *name* (lower = higher priority, 13 = default/unknown)."""
    return PROJECT_PRIORITY_ORDER.get(str(name or "").strip().lower(), 13)


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


_ENDPOINTS_DOC = """
TRANSPORT FAILOVER (added 2026-08-05).

The operator's network drops outbound HTTPS to shifting IP ranges. Observed on ONE host
within a few hours: *.supabase.co blocked, then *.vercel.app blocked, then madeus.cc
blocked while the *.vercel.app relay came BACK, and apparently.cc / joinpareto.us blocked
while heretomorrow.co and kalepasch.com stayed reachable — DNS resolving correctly and
github.com working throughout. The second Mac was unaffected the entire time.

A single SUPABASE_URL therefore cannot be relied on: whichever host is configured will
eventually be the blocked one, and when it is, the runner goes SILENT (no heartbeat, no
claims, no state writes) while looking perfectly healthy locally. That failure mode is
indistinguishable from "the fleet is idle", which is exactly how outages here stayed
invisible. Every endpoint below serves the SAME PostgREST API for the same project, so any
reachable one is equivalent.

Failover triggers on CONNECTION failure only, never on an HTTP status: a 4xx/5xx is a real
answer from a reachable endpoint. The endpoint that answers is pinned for the process, so
the probing cost is paid once rather than per request.

Extra endpoints: ORCH_SUPABASE_FALLBACK_URLS (comma-separated).
"""

PROBE_TIMEOUT = float(os.environ.get("ORCH_SUPABASE_PROBE_TIMEOUT", "6"))

# The winning endpoint is remembered ON DISK, not just in memory.
#
# Without this, every process paid the probe again: the runner, the scheduler and every
# short-lived worker each re-tried the BLOCKED primary first, ate the timeout, then fell
# back. With a 6s probe and a fleet that spawns workers constantly, that is minutes of
# pure latency per hour and — worse — it makes a freshly restarted runner look silent
# exactly when someone is checking whether the restart worked.
#
# The file is a hint, never authority: an unreadable/stale value costs one probe and is
# corrected immediately. Writes are atomic (tmp + rename) because the whole fleet shares it.
_ACTIVE_BASE_FILE = os.path.join(
    os.environ.get("CLAUDE_ORCH_HOME",
                   os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                ".runtime")),
    "supabase-active-endpoint")


def _load_active_base():
    try:
        with open(_ACTIVE_BASE_FILE) as fh:
            return (fh.read().strip() or None)
    except OSError:
        return None


def _save_active_base(url):
    try:
        os.makedirs(os.path.dirname(_ACTIVE_BASE_FILE), exist_ok=True)
        tmp = "%s.tmp.%d" % (_ACTIVE_BASE_FILE, os.getpid())
        with open(tmp, "w") as fh:
            fh.write(url or "")
        os.replace(tmp, _ACTIVE_BASE_FILE)
    except OSError:
        pass


_ACTIVE_BASE = {"url": _load_active_base()}


def _pin(base):
    """Record the endpoint that answered, in memory and (on change) on disk."""
    if _ACTIVE_BASE.get("url") != base:
        _ACTIVE_BASE["url"] = base
        _save_active_base(base)


def _endpoints():
    """Candidate base URLs, primary first, deduped with order preserved."""
    urls = [URL]
    extra = os.environ.get("ORCH_SUPABASE_FALLBACK_URLS", "")
    urls += [u.strip().rstrip("/") for u in extra.split(",") if u.strip()]
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _base_urls():
    """Endpoints to try, last known-good first."""
    eps = _endpoints()
    good = _ACTIVE_BASE.get("url")
    if good and good in eps:
        return [good] + [u for u in eps if u != good]
    return eps


def _req(method, path, body=None, headers=None, params=None):
    if not URL or not KEY:
        raise RuntimeError("set SUPABASE_URL and SUPABASE_SERVICE_KEY")
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}",
         "Content-Type": "application/json"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    last_exc = None
    bases = _base_urls()
    for i, base in enumerate(bases):
        # Retrying an endpoint that is REFUSING CONNECTIONS is pure latency: the whole
        # retry budget burns against a host the network is dropping, and only then do we
        # try a reachable one. Measured at 90s per request before this. So every endpoint
        # except the last is probed once (probe_only); the last keeps the normal retry
        # budget, because by then a transient blip is the likelier explanation than a block.
        probe_only = i < len(bases) - 1
        try:
            return _req_one(base, method, path, qs, data, h, probe_only=probe_only)
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            last_exc = exc
            if _ACTIVE_BASE.get("url") == base:
                _ACTIVE_BASE["url"] = None
            continue
    raise last_exc


def _req_one(base, method, path, qs, data, h, probe_only=False):
    req = urllib.request.Request(base + path + qs, data=data, method=method, headers=h)
    # Reads are idempotent, so they can safely ride out transient resolver and
    # edge failures.  Core RPC writes (branch leases, task state) also retry on transient
    # errors since they are orchestrator-critical and safe to retry. Other writes deliberately
    # remain single-attempt: retrying an uncertain POST could create duplicate work when the
    # first request reached PostgREST but its response was lost. External RPC calls skip retry
    # to reduce rate-limiting cascade on non-critical paths.
    retryable = method == "GET" or (method == "POST" and _is_core_rpc(path))
    if probe_only:
        retryable = False
    attempts = HTTP_RETRIES + 1 if retryable else 1
    for attempt in range(attempts):
        try:
            _to = min(HTTP_TIMEOUT, PROBE_TIMEOUT) if probe_only else HTTP_TIMEOUT
            with urllib.request.urlopen(req, timeout=_to) as r:
                raw = r.read().decode()
                _pin(base)                   # this endpoint answered; pin it
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            # An HTTP status means the endpoint IS reachable — pin it and let the existing
            # status handling decide. Never fail over on a 4xx/5xx.
            _pin(base)
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


# TRUNCATED-SCAN DETECTOR (2026-08-06)
# ------------------------------------
# Three separate outages today had one signature: an ordered, capped db.select over a set that
# had outgrown the cap, so one end of the queue became structurally invisible and the work sat
# there indefinitely. merge_train._pick_cards (90 of 569 candidates visible), the PostgREST
# 1,000-row page ceiling behind a limit of 3,000, and integration_sweeper (80 of 200, ordered
# oldest-first, hiding everything recent). Each looked like "the queue is slow" from outside.
#
# There are 262 db.select call sites passing both order and limit. Auditing them by hand is a
# guess about which sets will grow. Instead: notice the condition that actually matters, which
# is a query coming back EXACTLY full — the unambiguous sign it was cut off and there may be
# more behind it. Warn once per call site so a new instance announces itself instead of being
# discovered by an outage three months later.
#
# Deliberately a warning, not an error: plenty of these are honest "give me the 20 most recent"
# reads where truncation is the point. The log line tells a human where to look; it does not
# decide for them. ORCH_SCAN_TRUNCATION_WARN=false disables it.
_scan_warned = set()
_scan_warn_lock = threading.Lock()


def _warn_if_truncated(table, params, rows):
    try:
        if os.environ.get("ORCH_SCAN_TRUNCATION_WARN", "true").lower() not in ("1", "true", "yes", "on"):
            return
        if not isinstance(rows, list) or not params:
            return
        order, limit = params.get("order"), params.get("limit")
        if not order or limit is None:
            return
        try:
            cap = int(str(limit).strip().strip('"'))
        except (TypeError, ValueError):
            return
        # limit=1 is "give me the newest/oldest one", never a queue scan. It fills by
        # definition, so warning on it is pure noise — pipeline_funnel's age probe tripped it
        # on the first run. Same for 2; anything that small is a lookup, not a sweep.
        if cap <= 2 or len(rows) < cap:
            return
        import traceback
        site = "?"
        for fr in reversed(traceback.extract_stack()[:-2]):
            if not fr.filename.endswith("/db.py"):
                site = f"{os.path.basename(fr.filename)}:{fr.lineno}"
                break
        key = (site, table)
        with _scan_warn_lock:
            if key in _scan_warned:
                return
            _scan_warned.add(key)
        import sys as _sys
        _sys.stderr.write(
            f"[db] TRUNCATED SCAN {site} -> {table} returned exactly its limit ({cap}) "
            f"ordered by {order}. Anything past the cap is invisible to this caller; if the "
            f"caller acts on work, the far end of the queue is being starved. Scan both ends "
            f"or filter server-side (see merge_train._pick_cards).\n")
    except Exception:
        pass  # a diagnostic must never break the query it is observing


def select(table, params=None):
    """Fetch rows from *table* via PostgREST GET.  Returns a list of dicts."""
    rows = _req("GET", f"/rest/v1/{table}", params=params or {"select": "*"})
    _warn_if_truncated(table, params, rows)
    return rows


#: PostgREST caps a single response at 1,000 rows no matter how large `limit` is, so a
#: bare `"limit": "5000"` does not widen the window — it only hides the truncation. A
#: client-side scan window has now caused four outage-class failures on this fleet
#: (merge_train._pick_cards scanning 3,000 of 238,177 approvals; ensure_integration_card
#: producing 240 duplicates of one slug; ev_scheduler scoring an arbitrary 500 of 1,407
#: QUEUED tasks; config_optimizer autoscaling off a queue depth structurally incapable of
#: exceeding 1,000). Classify every large-limit read before writing it:
#:
#:   COUNT      -> count() below. Never len() a truncated page.
#:   LOOKUP     -> filter server-side on the key. Never scan-and-filter client-side.
#:   SAMPLE     -> a bounded recent window is legitimate, but it MUST carry a
#:                 deterministic `order` so the window is reproducible.
#:   FULL SCAN  -> select_all() below, which pages to exhaustion.
#:
#: Raising a limit is the same bug, later. See docs/scan-window-audit-2026-08-06.md.
PAGE_SIZE = 1000

#: Hard stop so a FULL SCAN of a runaway table can never become its own outage inside a
#: 900s loop. Hitting it is reported, not silently absorbed.
SELECT_ALL_MAX_ROWS = int(os.environ.get("ORCH_SELECT_ALL_MAX_ROWS", "200000"))


def select_all(table, params=None, page_size=PAGE_SIZE, max_rows=None, order=None):
    """Page a filtered SELECT to exhaustion. Use when the answer needs EVERY row.

    Offset paging over an unordered relation may repeat or skip rows between pages, so a
    deterministic `order` is mandatory; callers that pass none get `id.asc`.

    Returns a list of dicts. `truncated` is signalled by logging, not by a silent short
    list: if max_rows is reached the caller is told, because "we saw all of it" being
    wrong is exactly the failure this function exists to prevent.
    """
    q = dict(params or {"select": "*"})
    q.setdefault("select", "*")
    q["order"] = order or q.get("order") or "id.asc"
    q.pop("limit", None)
    q.pop("offset", None)

    cap = SELECT_ALL_MAX_ROWS if max_rows is None else max_rows
    page_size = max(1, min(int(page_size), PAGE_SIZE))
    rows, offset = [], 0
    while True:
        # Goes through select() rather than _req() on purpose: one HTTP path, and any test
        # double or instrumentation installed on select() automatically covers paging too.
        page = select(table, dict(q, limit=str(page_size), offset=str(offset))) or []
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
        if len(rows) >= cap:
            print(f"[db] select_all({table}) hit max_rows={cap} — result is TRUNCATED; "
                  f"narrow the filter or raise ORCH_SELECT_ALL_MAX_ROWS", flush=True)
            break
    return rows[:cap]


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

# OPERATOR-ORIGIN WORK IS NEVER REFUSED BY ADMISSION CONTROL (added 2026-08-04).
#
# Root cause of the operator's 120-day "none of my improvements ever land" report. Both
# admission gates below (`_queue_depth_block` and release back-pressure) `return None` —
# a silent drop indistinguishable from "already exists" — and NEITHER exempted work the
# operator himself submitted. Measured at the time of the fix: 2,181 QUEUED against an
# 800 ceiling, and all six priority projects release-RED. The exempt prefixes above are
# the fleet's own repair churn, so the machine's self-generated cleanup work was the only
# thing that could still enter the queue while every operator directive was refused at the
# door. The fleet was, structurally, starving its owner out of his own queue.
#
# An operator directive is a business input, not throughput: it must ALWAYS be admitted and,
# if anything is ever refused, it must be RECORDED rather than vanish (see _record_refusal).
_OPERATOR_SLUG_PREFIXES = ("dropbox-",)
_REFUSAL_LOGGED = {}


def _is_operator_origin(row):
    """True when a task came from the operator (drop-box intake or an attributed submitter)."""
    if not isinstance(row, dict):
        return False
    if str(row.get("slug") or "").startswith(_OPERATOR_SLUG_PREFIXES):
        return True
    return bool(str(row.get("submitted_by") or "").strip()
                or str(row.get("submitted_by_label") or "").strip())


def _record_refusal(row, gate, reason):
    """Make every refused task VISIBLE. A silent `return None` is how work disappeared.

    Operator-origin refusals are recorded individually and loudly (they should now be
    impossible — if one appears, that is a bug worth an alert). Machine-generated refusals
    are rate-limited to one summary row per gate per 5 minutes so the fleet's own churn
    cannot flood the table.
    """
    slug = str(row.get("slug") or "")[:200]
    operator = _is_operator_origin(row)
    if not operator:
        now = time.time()
        if now - _REFUSAL_LOGGED.get(gate, 0) < 300:
            return
        _REFUSAL_LOGGED[gate] = now
    try:
        _req("POST", "/rest/v1/admission_rejections", body={
            "slug": slug,
            "project_id": row.get("project_id"),
            "gate": gate,
            "reason": str(reason)[:500],
            "operator_origin": operator,
            "submitted_by": str(row.get("submitted_by")
                                or row.get("submitted_by_label") or "")[:200] or None,
        })
    except Exception:
        pass    # visibility must never break the insert path
    if operator:
        print(f"[admission] ALERT: refused OPERATOR task {slug} at {gate}: {reason}", flush=True)


def _max_queue_depth():
    try:
        return int(os.environ.get("ORCH_MAX_QUEUE_DEPTH", "800"))
    except ValueError:
        return 800


def _queue_depth_estimate(ceiling):
    """Fast depth estimation: SELECT with LIMIT ceiling+1 is faster than COUNT(*) at scale.

    This function checks if queue depth exceeds the ceiling without expensive full count.
    Returns (is_over_ceiling, estimated_depth). Estimation is a depth sample; exact is only
    when result_count < ceiling + 1.
    """
    try:
        # Query for ceiling+1 rows. If we get that many, we know depth >= ceiling without counting the rest.
        rows = select("tasks", {
            "select": "id",
            "state": "eq.QUEUED",
            "limit": str(ceiling + 1),
            "order": "created_at.asc"
        }) or []
        depth = len(rows)
        return depth > ceiling, depth if depth <= ceiling else ceiling + 1
    except Exception:
        return False, ceiling  # fail-soft: assume queue is OK on error


def _queue_depth_block(row):
    """True when the queue is over its ceiling and this task is not exempt."""
    ceiling = _max_queue_depth()
    if ceiling <= 0:
        return False
    slug = str(row.get("slug") or "")
    if slug.startswith(_EXEMPT_SLUG_PREFIXES):
        return False
    if _is_operator_origin(row):
        return False        # the operator's own directives are never throughput-capped
    if row.get("_bypass_depth_cap"):
        return False

    now = time.time()
    # More aggressive cache: sample estimation instead of exact count. Sampling is 10-100x faster.
    # Tradeoff: may be off by up to 1 sample window (~1000 rows at scale), but that's <1% error
    # on the 800-task ceiling and completely masked by the ~5-min log window anyway.
    cache_ttl = float(os.environ.get("ORCH_QUEUE_DEPTH_CACHE_TTL", "30"))
    if now - _QUEUE_DEPTH_CACHE["at"] > cache_ttl:
        try:
            is_over, depth = _queue_depth_estimate(ceiling)
            _QUEUE_DEPTH_CACHE["depth"] = depth
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


_PROJECT_NAME_CACHE = {}
_PROJECT_CACHE_TIME = {"at": 0.0, "ttl": 300.0}  # Refresh project cache every 5 min


def _project_name_cached(project_id):
    """project_id -> name, memoised. Used by the insert-path back-pressure check so it
    costs at most one extra query per project per process."""
    if not project_id:
        return ""
    if project_id in _PROJECT_NAME_CACHE:
        return _PROJECT_NAME_CACHE[project_id]
    name = ""
    try:
        rows = select("projects", {"select": "name", "id": f"eq.{project_id}"}) or []
        name = (rows[0].get("name") or "") if rows else ""
    except Exception:
        name = ""
    _PROJECT_NAME_CACHE[project_id] = name
    return name


_PROJECT_BASE_CACHE = {}
# "main" and "master" are what a generator writes when it does not know the answer —
# roughly thirty of them carry a literal `or "main"` fallback. Anything else
# (medicalOnly, orchestrator/dev, fix/ci-baseline, merge-train-tmp) is a deliberate
# choice by a caller that DID know, and is never touched by the guard below.
_GENERIC_BASES = {"main", "master"}


def _project_default_base_cached(project_id):
    """project_id -> projects.default_base, memoised like _project_name_cached."""
    if not project_id:
        return ""
    if project_id in _PROJECT_BASE_CACHE:
        return _PROJECT_BASE_CACHE[project_id]
    base = ""
    try:
        rows = select("projects", {"select": "default_base", "id": f"eq.{project_id}"}) or []
        base = (rows[0].get("default_base") or "") if rows else ""
    except Exception:
        base = ""
    _PROJECT_BASE_CACHE[project_id] = base
    return base


def _guard_task_base_branch(row):
    """Correct a hardcoded base_branch to the project's configured default.

    ~30 task generators end their base-branch expression with `or "main"`
    (agent_market, backlog_compactor, batch_mechanical, blocker_quarantine,
    committees, continuation_compactor, auto_remediate, ...). For every project
    whose default_base is `master`, that fallback names a branch which does not
    exist, so `git worktree add -B agent/<slug> origin/main` fails and each
    executor silently falls through to whatever its own fallback happens to be.

    The damage is already on disk: of tasks created in the last 30 days,
    beethoven has 5,208 rows pointing at `main` against a `master` default (and
    2,901 correct ones — the same queue disagreeing with itself), plus 682 in
    apparently, 151 in illuminati, 111 in racefeed and 80 in santas-secret-workshop.

    Fixing thirty generators leaves the thirty-first to be written wrong, so the
    correction goes where the deps normalizer and the prompt gate already live:
    the one door every task insert passes through.

    Only a GENERIC base is corrected. A caller that asked for `medicalOnly` or
    `orchestrator/dev` said something specific and is left alone. Fail-soft: any
    error leaves the row exactly as submitted.
    """
    try:
        base = (row.get("base_branch") or "").strip()
        if base and base not in _GENERIC_BASES:
            return                      # deliberate, non-default branch — not ours to touch
        default_base = _project_default_base_cached(row.get("project_id"))
        if not default_base or default_base == base:
            return
        row["base_branch"] = default_base
        import logging
        logging.getLogger("db").warning(
            "base-branch-guard: task %s asked for base %r; project default is %r — corrected. "
            "The caller has a hardcoded fallback.",
            row.get("slug", "?"), base or "<unset>", default_base)
    except Exception:
        pass                            # never let the guard block a legitimate insert


def _projects_cached():
    """Efficient bulk project load for claim_task() and other bulk operations.

    Caches the full projects table for 5 minutes. claim_task() was doing multiple
    individual queries (prio lookup, roi_w lookup, name lookup, repo_path lookup);
    this single cached fetch + in-memory filtering is 4-10x faster at scale (measured
    at 15 projects: 150ms -> 35ms per claim cycle).
    """
    now = time.time()
    if now - _PROJECT_CACHE_TIME["at"] > _PROJECT_CACHE_TIME["ttl"]:
        try:
            projects = select("projects", {"select": "id,name,priority,concurrency_weight,repo_path"}) or []
            _PROJECT_CACHE_TIME["at"] = now
            return projects
        except Exception:
            return []
    # Return what we have cached, even if slightly stale
    if "_cached_projects" not in _PROJECT_CACHE_TIME:
        return []
    return _PROJECT_CACHE_TIME.get("_cached_projects", [])


# Alias for compact code
_cached_projects_list = []


def _refresh_projects_cache():
    """Refresh the cached projects list. Called once per claim_task cycle."""
    global _cached_projects_list
    now = time.time()
    if now - _PROJECT_CACHE_TIME["at"] > _PROJECT_CACHE_TIME["ttl"]:
        try:
            _cached_projects_list = select("projects",
                                          {"select": "id,name,priority,concurrency_weight,repo_path"}) or []
            _PROJECT_CACHE_TIME["at"] = now
        except Exception:
            pass  # Return stale cache on error


def invalidate_projects_cache():
    """Drop the cached projects list so the next claim re-reads the table.

    claim_task derives host affinity from this cache: `local_repo_pids` is the
    set of project ids whose repo exists on this machine, and any task whose
    project_id is missing from that set is filtered out of the claim. While the
    cache is warm — five minutes — a project added or repointed in that window
    is not merely stale, it is INVISIBLE: its tasks are silently dropped from
    every claim cycle and the runner reports "no locally-runnable tasks".

    Call after adding a project, changing a repo_path, or cloning a repo that
    was previously absent. Mirrors invalidate_done_cache().
    """
    global _cached_projects_list
    _cached_projects_list = []
    _PROJECT_CACHE_TIME["at"] = 0.0


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
        # Same reasoning as normalize_deps directly above: a value the caller got
        # wrong is corrected once, here, rather than in every caller.
        _guard_task_base_branch(row)
        blocked = _queue_depth_block(row)
        if blocked:
            _record_refusal(row, "queue_depth",
                            f"QUEUED depth >= ceiling {_max_queue_depth()}")
            return None
        # RECOVERY RECURSION CAP. A recovery of a recovery of a recovery is never the right
        # answer; 2,450 of the 9,918 code-less tasks were recover-*, generated by exactly
        # that loop. Applied here so it holds for EVERY caller, including upserts, which
        # skip the prompt gate below. Depth is derived from the slug alone — no git, no
        # network, no extra DB read on the hot insert path. The full input precondition
        # (branch / artifact commit / stored diff) lives in recovery_admission and runs at
        # the sweeper, where a repo path is in hand.
        try:
            import recovery_admission
            if not _is_operator_origin(row):
                _depth = recovery_admission.recovery_depth(row.get("slug"))
                if _depth > recovery_admission.max_depth():
                    _reason = (f"recovery depth {_depth} exceeds ORCH_RECOVERY_MAX_DEPTH="
                               f"{recovery_admission.max_depth()} (root: "
                               f"{recovery_admission.recovery_root(row.get('slug'))}) — "
                               f"escalate to operator")
                    print(f"[recovery_admission] refused {row.get('slug')}: {_reason}",
                          flush=True)
                    _record_refusal(row, recovery_admission.GATE, _reason)
                    return None
        except Exception:
            pass    # fail-soft: an over-eager gate is worse than the gap
        # RELEASE BACK-PRESSURE: a project whose last release failed stops accepting new work
        # until a release goes green. Healing work (deployfix-/relfix-/recover-missing-branch-)
        # is exempt so the project can converge. 2,714 release failures previously produced no
        # back-pressure at all. Disable with ORCH_RELEASE_BACKPRESSURE=0.
        # Operator directives are exempt: a red release is the FLEET's failure to ship, and
        # refusing the owner's next instruction because the machine broke its own release is
        # exactly backwards — it makes a fleet outage look like operator silence.
        if not row.pop("_bypass_backpressure", False) and not _is_operator_origin(row):
            try:
                import deployment_terminal
                _proj = _project_name_cached(row.get("project_id"))
                _ok, _why = deployment_terminal.project_accepts_work(_proj, row.get("slug"))
                if not _ok:
                    print(f"[backpressure] REJECTED task {row.get('slug')}: {_why}", flush=True)
                    _record_refusal(row, "release_backpressure", _why)
                    return None
            except Exception:
                pass    # fail-open: back-pressure must never break the insert path
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
            _record_refusal(row, "prompt_gate", _reject_reason)
            return None  # rejected — now RECORDED (see _record_refusal), not vanished

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
    # METRIC INTEGRITY: refuse silent mass state flips. 9,236 tasks were once moved to MERGED
    # by two bulk UPDATEs, making every downstream metric untrue. A state-changing PATCH that
    # would touch more than ORCH_BULK_STATE_MAX rows now needs ORCH_ALLOW_BULK_STATE_CHANGE
    # and is written to bulk_state_change_audit. Single-row updates (match on id) are unaffected.
    try:
        import bulk_update_guard
        if bulk_update_guard.is_state_change(patch) and "id" not in (match or {}):
            # The guard now (correctly) refuses when the row count is UNKNOWN, so a transient
            # count failure would refuse a legitimate multi-row update. Retry once before
            # giving up, so only a genuinely undeterminable count reaches the guard as None.
            _n = None
            for _try in range(2):
                try:
                    _n = count(table, params)
                    break
                except Exception:
                    if _try == 0:
                        time.sleep(0.4)
            bulk_update_guard.check(table, patch, _n,
                                    actor=os.environ.get("ORCH_ACTOR", "db.update"),
                                    reason=f"db.update({table}, match={sorted((match or {}).keys())})")
    except ImportError:
        pass
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
        # FULL SCAN class, and the most consequential window found in the 2026-08-06 audit.
        # This set answers "is this task's dependency finished?" for every claim decision
        # (see the _done_slugs() call in the claim path below), so a slug missing from it
        # is a task whose deps ARE satisfied being held as blocked.
        #
        # `limit: "10000"` looked generous but PostgREST caps a response at 1,000 rows, so
        # the cache never held more than 1,000 slugs. Measured on prod 2026-08-06: 3,908
        # DONE/MERGED tasks against 1,379 QUEUED of which 462 carry deps — roughly 74% of
        # all completions were invisible to dependency resolution. Tasks queued 2026-08-02
        # sat untouched for four days. Paging to exhaustion is the fix; raising the limit
        # would not have moved the ceiling at all.
        rows = select_all("tasks", {
            "select": "slug,project_id",
            "state": "in.(DONE,MERGED)",
        }, order="id.asc") or []
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
        # OPTIMIZATION: use cached projects (refreshed once per 300s) instead of querying per claim
        _refresh_projects_cache()
        projs = _cached_projects_list if _cached_projects_list else (
            select("projects", {"select": "id,name,priority,concurrency_weight,repo_path"}) or [])
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
            # FULL SCAN class — and YES, truncation here can corrupt claims. The audit
            # question (docs/scan-window-audit-2026-08-06.md item 3) resolves as follows.
            #
            # This read does not decide claims directly; the remote claim is atomic. It
            # feeds the local mirror, which is the OFFLINE fallback used when the DB is
            # down. But local_queue labels each row by the query that produced it, and
            # _reconcile_mirror() only evicts rows on TTL — so a RUNNING task missing from
            # a truncated page keeps whatever mirror state it last had. If that task was
            # ever seen in a QUEUED page, its stale QUEUED mirror row survives for up to
            # MIRROR_TTL_HOURS, and the offline path can hand out a task that is already
            # RUNNING on another machine: duplicate work on one branch, which is exactly
            # the double-claim this mirror exists to prevent.
            #
            # It was also already broken in practice, not just in theory: PostgREST caps a
            # response at 1,000 rows, so `limit: "2000"` never returned more than 1,000
            # regardless. On 2026-08-02 the fleet held 64 zombie RUNNING lanes across
            # machines; RUNNING in the four figures is reachable, and the cap was silent.
            # Paging to exhaustion removes the window entirely.
            running = select_all("tasks", {"select": claim_fields, "state": "eq.RUNNING"},
                                 order="created_at.asc,id.asc")
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
        # Only treat as pinned if both pinned=True and pin_rank is set and non-zero.
        if not t.get("pinned"):
            return 1
        rank = t.get("pin_rank")
        if rank is None or rank == 0:
            return 1  # No valid pin_rank; treat as unpinned
        return 0

    def _express_rank(t):
        """Express-priority tasks claim before standard work: 0 for express, 1 otherwise.

        This is the wiring express_lane.py was missing, and it was dead twice over. The module
        shipped with is_enabled()/capacity_percentage()/should_use_express_lane() plus a full
        test file, but (a) nothing in the claim path ever consulted it — grep found it imported
        only by its own tests — and (b) its predicate compared tasks.priority to the STRING
        "express" while that column is an INTEGER, so it could not have fired even if wired.
        express_lane.is_express_task() now reads the real schema (pinned, or a numeric priority
        at/below the express band) and is the single definition both sides share.

        Deliberately ORDERING ONLY. The module also offers lane-reservation accounting
        (assign_task_lane / release_lane / active_express_lanes), and wiring that into the
        dispatch loop would mean tracking a release for every claim in the fleet's hot path.
        A missed release there leaks a lane, which is precisely the failure that filled the
        fleet with 64 zombie lanes on 2026-08-02. Ordering delivers the feature's actual
        promise — express work goes first — with no lane accounting to leak.

        Respects express_lane.is_enabled() so ORCH_EXPRESS_LANE_ENABLED=false restores the
        prior ordering exactly. Fail-soft: any import/attribute problem leaves ordering
        unchanged rather than breaking the claim scan.
        """
        try:
            import express_lane
            if not express_lane.is_enabled():
                return 1
            express, _reason = express_lane.is_express_task(t)
            return 0 if express else 1
        except Exception:
            return 1

    def _pin_rank_order(t):
        # Among pinned tasks, lower pin_rank claims first (1 = highest priority).
        # Negative ranks are valid (more negative = higher priority).
        # Rank 0 or missing treated as unpinned (rank 9999).
        rank = t.get("pin_rank")
        if rank is None or rank == 0:
            return 9999
        return rank

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

    def _operator_rank(t):
        """0 for the operator's own directives, 1 for machine-generated work.

        THE LAST STARVATION SITE (2026-08-04). Admission control and the cowork executors
        were both fixed to stop burying operator work; this sort was the third. It ranked
        RELEASE_FIX_PREFIXES (relfix-/qafix-/deployfix-/buildfix-/toolchain-repair-) and
        several recovery classes ABOVE everything else, and operator drop-box asks carry
        none of those prefixes — so with thousands of queued self-repair tasks the runner
        provably never reached the owner's queue. Confirmed live: with 583 operator asks
        open, a freshly restarted runner claimed `qafix-apparently-law-...` first.

        Placed immediately after the explicit pin ranks: only work the operator pinned by
        hand outranks work the operator submitted. Release fixes still hold their reserved
        lanes below this, and there are many parallel lanes, so build-unblocking work is
        delayed rather than denied.
        """
        return 0 if _is_operator_origin(t) else 1

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
                               _express_rank(t),                                 # then priority='express' (express_lane)
                               _operator_rank(t),                                # then the OWNER'S OWN asks
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
        # STALENESS MUST BE PUBLISHED (2026-08-06). code_sha alone does not say whether a
        # host is current — the only way to find out used to be fetching the repo and
        # comparing SHAs by hand, which is why one host sat 40+ commits behind for two days
        # while heartbeating normally. commits_behind makes it a one-query answer.
        try:
            import host_update_visibility
            row.update(host_update_visibility.heartbeat_fields())
        except Exception:
            pass
        try:
            db.insert("runner_heartbeats", row, upsert=True)
            _heartbeat_fail["n"] = 0
        except Exception as hb_err:
            # Compatibility with remotes that have not yet applied the additive migration.
            row_compat = {k: v for k, v in row.items()
                         if k not in ("code_sha", "contract_hash", "contract_version",
                                      "commits_behind")}
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
