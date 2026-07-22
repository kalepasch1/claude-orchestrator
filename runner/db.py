#!/usr/bin/env python3
"""
db.py - tiny Supabase (PostgREST) client over urllib. No third-party deps.
The runner uses the SERVICE ROLE key so it bypasses RLS. Set:
    SUPABASE_URL=https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY=<service-role key>   (keep secret; never ship to the web app)
The .env file in runner/ is auto-loaded at import time by the _load_env() helper below.
"""
import os, re, json, socket, time, datetime, threading, urllib.request, urllib.parse, urllib.error

# ... rest of code ...

def test_trigger(task_id):
    """Atomically transition a QUEUED task to TESTING to signal that the test suite has been
    initiated. Called immediately after enqueue so tests start before a runner claims the task.
    Returns the updated row on success, None if the task was already claimed or in another state.
    Fail-soft: any DB error returns None so callers never break on test-trigger failure."""
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
RECOVERY_PREFIX = "recover-missing-branch-"
CANARY_PREFIX = "canary-"
IMPROVEMENT_PREFIX = "improve-"
RELEASE_FIX_PREFIXES = ("relfix-", "qafix-", "deployfix-", "buildfix-")


def _req(method, path, body=None, headers=None, params=None):
    if not URL or not KEY:
        raise RuntimeError("set SUPABASE_URL and SUPABASE_SERVICE_KEY")
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}",
         "Content-Type": "application/json"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path + qs, data=data, method=method, headers=h)
    attempts = HTTP_RETRIES + 1 if method == "GET" else 1
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if method != "GET" or e.code not in HTTP_RETRY_STATUSES or attempt >= attempts - 1:
                raise
            time.sleep(min(8, 2 ** attempt))
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            if method != "GET" or attempt >= attempts - 1:
                raise
            time.sleep(min(8, 2 ** attempt))


def select(table, params=None):
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
    h = {"Prefer": "return=representation" + (",resolution=merge-duplicates" if upsert else "")}
    try:
        return _req("POST", f"/rest/v1/{table}", body=row, headers=h)
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


def upsert(table, row):
    """Compatibility helper for modules that store idempotent control rows."""
    return insert(table, row, upsert=True)


def update(table, match, patch):
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


def claim_task(runner_id):
    """Atomically grab one QUEUED or TESTING task whose deps are satisfied. ECONOMIC ORDERING:
    within a project-priority band, prefer higher-ROI projects (projects.concurrency_weight, set
    from cost-per-merge by roi.py) and then FIFO. This makes the highest expected-value work run
    first under any capacity limit — and stays correct across MULTIPLE machines because the final
    claim is an atomic optimistic PATCH (state=QUEUED/TESTING -> RUNNING), so two runners never
    double-claim."""
    prio, roi_w, project_names, paused_pids = {}, {}, {}, set()
    try:
        projs = select("projects", {"select": "id,name,priority,concurrency_weight"}) or []
        prio = {p["id"]: (p.get("priority") if p.get("priority") is not None else 5) for p in projs}
        roi_w = {p["id"]: (p.get("concurrency_weight") if p.get("concurrency_weight") is not None else 1)
                 for p in projs}
        project_names = {p["id"]: p.get("name") for p in projs}
        name2id = {p["name"]: p["id"] for p in projs}
        paused_names = {c["project"] for c in (select("controls", {"select": "project,paused,updated_by",
                        "scope": "eq.project", "paused": "is.true"}) or [])
                        if c.get("project") and c.get("updated_by") != "remote-quarantine"}
        paused_pids = {name2id[n] for n in paused_names if n in name2id}
    except Exception:
        pass
    queued = select("tasks", {"select": "id,slug,project_id,deps,confidence,created_at,kind,note,state",
                              "state": "in.(QUEUED,TESTING)",
                              "order": "created_at.asc",
                              "limit": str(CLAIM_SCAN_LIMIT)}) or []
    queued = [t for t in queued if t.get("project_id") not in paused_pids]  # skip paused projects

    def _churn(t):
        s = str(t.get("slug") or "")
        return 1 if deprio_churn and (s.startswith("cont-") or s.startswith("batch-mech")) else 0

    thermal_rank = _thermal_rank_map()
    ev_rank = _ev_rank_map()

    def _task_priority(t):
        return _num(t.get("priority"), 1000)

    def _ev_rank(t):
        return ev_rank.get(str(t.get("id")), 1000000)

    def _thermal_rank(t):
        return thermal_rank.get(str(t.get("id")), 1000000)

    def _confidence_rank(t):
        # Last-resort EV fallback writes higher confidence for better tasks.
        return -_num(t.get("confidence"), 0.0)

    queued.sort(key=lambda t: (_churn(t),                                        # real work before churn
                               _thermal_rank(t),                                 # EV/min thermal map
                               _task_priority(t),                                # EV/task priority when present
                               _ev_rank(t),                                      # controls.ev_ranking fallback
                               _confidence_rank(t),                              # tasks.confidence fallback
                               last_act.get(t.get("project_id"), ""),           # least-recently-served first
                               prio.get(t.get("project_id"), 5),
                               -float(roi_w.get(t.get("project_id"), 1) or 1),
                               t.get("created_at") or ""))
    done = {t["slug"] for t in select("tasks", {"select": "slug", "state": "in.(DONE,MERGED)"})}
    for t in queued or []:
        pid = t.get("project_id")
        if pid and active_by_project.get(pid, 0) >= _project_lane_limit(t):
            continue
        if all(d in done for d in (t.get("deps") or [])):
            # optimistic claim: flip to RUNNING only if still QUEUED or TESTING
            cur_state = t.get("state", "QUEUED")
            res = _req("PATCH", "/rest/v1/tasks",
                       body={"state": "RUNNING", "account": runner_id, "updated_at": "now()"},
                       headers={"Prefer": "return=representation"},
                       params={"id": f"eq.{t['id']}", "state": f"eq.{cur_state}"})
            if res:
                if pid:
                    active_by_project[pid] = active_by_project.get(pid, 0) + 1
                return res[0]
    return None


def set_pin(slug, rank=1):
    """Pin a QUEUED task so it sorts before the normal fairness round-robin.
    rank is a positive int; lower = higher priority (1 = top). Pass rank=0 to unpin."""
    pinned = rank > 0
    return update("tasks", {"slug": slug}, {"pinned": pinned, "pin_rank": rank})


def heartbeat(runner_id, hostname, active):
    insert("runner_heartbeats",
           {"runner_id": runner_id, "hostname": hostname, "active_tasks": active,
            "last_seen": "now()"}, upsert=True)
    if os.environ.get("ORCH_LOGICAL_RUNNERS", "true").lower() not in ("true", "1", "yes"):
        return
    try:
        target = max(1, min(10, int(os.environ.get("ORCH_RUNNER_FLEET_TARGET", "8"))))
        for i in range(2, target + 1):
            lane_id = f"{runner_id}-lane-{i}"
            insert("runner_heartbeats",
                   {"runner_id": lane_id, "hostname": f"{hostname} lane {i}",
                    "active_tasks": 1 if active >= i else 0, "last_seen": "now()"},
                   upsert=True)
    except Exception:
        pass
