#!/usr/bin/env python3
"""
second_coder_bridge.py - bridge to a SECOND coding-capable Mac (Mac #2) running an open-source
coder (e.g. local Ollama model via aider). The remote worker takes independent branches, and its
output is judged by the same cross-model panel (judge.py) so quality stays uniform.

The bridge talks to a lightweight HTTP server on Mac #2 that wraps the local coder. Communication
is plain JSON over HTTP -- no auth beyond network isolation (the Macs sit on the same LAN).

Configure with env vars:

    ORCH_REMOTE_CODER_HOSTS=192.168.1.50:7819,192.168.1.51:7819   # comma-separated host:port
    ORCH_REMOTE_TIMEOUT=300          # per-request timeout in seconds (default 300)
    ORCH_REMOTE_POLL_INTERVAL=5      # seconds between polls (default 5)
    ORCH_REMOTE_MAX_CONCURRENT=4     # max concurrent jobs per remote coder (default 4)
"""
import os, sys, json, time, logging, threading, uuid
import urllib.request, urllib.error, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_TIMEOUT = int(os.environ.get("ORCH_REMOTE_TIMEOUT", "300"))
_POLL_INTERVAL = int(os.environ.get("ORCH_REMOTE_POLL_INTERVAL", "5"))
_MAX_CONCURRENT = int(os.environ.get("ORCH_REMOTE_MAX_CONCURRENT", "4"))

# In-memory registry: name -> {host, port, capabilities, last_seen, jobs_active}
_registry: dict = {}
_registry_lock = threading.Lock()

# Job tracking: job_id -> {coder_name, task, status, result, dispatched_at, ...}
_jobs: dict = {}
_jobs_lock = threading.Lock()

# Stats counters
_stats = {
    "dispatched": 0,
    "completed": 0,
    "failed": 0,
    "timeouts": 0,
    "discovery_runs": 0,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _http(host, port, path, payload=None, timeout=10):
    """Fire a JSON HTTP request. Returns parsed JSON or None on failure."""
    url = f"http://{host}:{port}{path}"
    data = json.dumps(payload).encode() if payload else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.debug("HTTP %s failed: %s", url, exc)
        return None


def _health(host, port, timeout=5):
    """Return True if the remote coder answers /health."""
    resp = _http(host, port, "/health", timeout=timeout)
    return bool(resp and resp.get("ok"))


def _parse_hosts():
    """Parse ORCH_REMOTE_CODER_HOSTS env var into [(host, port), ...]."""
    raw = os.environ.get("ORCH_REMOTE_CODER_HOSTS", "")
    if not raw.strip():
        return []
    pairs = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            h, p = entry.rsplit(":", 1)
            try:
                pairs.append((h.strip(), int(p)))
            except ValueError:
                log.warning("bad host:port entry: %s", entry)
        else:
            pairs.append((entry, 7819))  # default port
    return pairs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_remote_coder(name: str, host: str, port: int, capabilities: dict) -> bool:
    """Register a remote coder (Mac #2) with connection details and capability profile.

    capabilities example: {"cap": 5, "models": ["ollama/qwen2.5-coder"], "cost": 0}
    Returns True on successful registration, False on health-check failure.
    """
    try:
        alive = _health(host, port)
    except Exception:
        alive = False
    with _registry_lock:
        _registry[name] = {
            "host": host,
            "port": port,
            "capabilities": capabilities or {},
            "last_seen": time.time() if alive else 0,
            "jobs_active": 0,
            "healthy": alive,
        }
    if alive:
        log.info("registered remote coder %s at %s:%d", name, host, port)
    else:
        log.warning("registered remote coder %s at %s:%d (offline)", name, host, port)
    return alive


def discover() -> list:
    """Auto-discover remote coders on the LAN via HTTP health checks.

    Reads ORCH_REMOTE_CODER_HOSTS and probes each. Returns list of dicts for
    every host that answered /health, auto-registering them.
    """
    _stats["discovery_runs"] += 1
    found = []
    for host, port in _parse_hosts():
        resp = _http(host, port, "/health", timeout=5)
        if resp and resp.get("ok"):
            name = resp.get("name", f"{host}:{port}")
            caps = resp.get("capabilities", {})
            register_remote_coder(name, host, port, caps)
            found.append({"name": name, "host": host, "port": port, "capabilities": caps})
    return found


def is_available(name: str) -> bool:
    """Check if a named remote coder is reachable and not at capacity."""
    with _registry_lock:
        entry = _registry.get(name)
    if not entry:
        return False
    # Check capacity
    if entry["jobs_active"] >= _MAX_CONCURRENT:
        return False
    # Live health check
    alive = _health(entry["host"], entry["port"])
    if alive:
        with _registry_lock:
            if name in _registry:
                _registry[name]["last_seen"] = time.time()
                _registry[name]["healthy"] = True
    return alive


def dispatch(task: dict, coder_name: str) -> dict:
    """Send a task to a remote coder via HTTP POST.

    The remote coder works on its own branch (agent/{slug}-remote) in its own
    worktree. Returns a job handle: {job_id, status, coder_name}.
    """
    with _registry_lock:
        entry = _registry.get(coder_name)
    if not entry:
        return {"job_id": None, "status": "error", "error": f"unknown coder: {coder_name}"}
    if entry["jobs_active"] >= _MAX_CONCURRENT:
        return {"job_id": None, "status": "error", "error": f"{coder_name} at capacity"}

    job_id = str(uuid.uuid4())
    slug = task.get("slug", "unknown")
    branch = f"agent/{slug}-remote"

    payload = {
        "job_id": job_id,
        "task": task,
        "branch": branch,
    }

    resp = _http(entry["host"], entry["port"], "/dispatch", payload=payload, timeout=30)
    if not resp or resp.get("status") == "error":
        _stats["failed"] += 1
        return {
            "job_id": job_id,
            "status": "error",
            "error": (resp or {}).get("error", "dispatch failed"),
        }

    with _registry_lock:
        if coder_name in _registry:
            _registry[coder_name]["jobs_active"] += 1

    with _jobs_lock:
        _jobs[job_id] = {
            "coder_name": coder_name,
            "task": task,
            "branch": branch,
            "status": "dispatched",
            "result": None,
            "dispatched_at": time.time(),
        }

    _stats["dispatched"] += 1
    log.info("dispatched job %s to %s (branch %s)", job_id, coder_name, branch)
    return {"job_id": job_id, "status": "dispatched", "coder_name": coder_name, "branch": branch}


def poll_result(job_id: str) -> dict:
    """Poll a dispatched job's status from the remote coder.

    Returns {status: pending|running|done|failed, ...} with results when done.
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return {"status": "unknown", "error": f"no such job: {job_id}"}

    # If already terminal locally, return cached
    if job["status"] in ("done", "failed"):
        return {"status": job["status"], "result": job["result"]}

    with _registry_lock:
        entry = _registry.get(job["coder_name"])
    if not entry:
        return {"status": "error", "error": "coder no longer registered"}

    resp = _http(entry["host"], entry["port"], f"/status/{job_id}", timeout=10)
    if not resp:
        return {"status": "error", "error": "unreachable"}

    new_status = resp.get("status", "unknown")
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = new_status
            if new_status == "done":
                _jobs[job_id]["result"] = resp.get("result")
                _stats["completed"] += 1
                _dec_active(job["coder_name"])
            elif new_status == "failed":
                _jobs[job_id]["result"] = resp.get("result")
                _stats["failed"] += 1
                _dec_active(job["coder_name"])

    return {"status": new_status, "result": resp.get("result")}


def _dec_active(coder_name):
    """Decrement the active job count for a coder (call under _jobs_lock)."""
    with _registry_lock:
        if coder_name in _registry:
            _registry[coder_name]["jobs_active"] = max(0, _registry[coder_name]["jobs_active"] - 1)


def collect_result(job_id: str) -> dict:
    """Collect the finished result from a remote job.

    Fetches commit hash, diff stats, test results from the remote coder.
    This result feeds into the same judge panel (judge.py) as local coders.
    Returns a dict compatible with agentic_coders.run() output shape.
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return {"status": "error", "error": f"no such job: {job_id}"}
    if job["status"] not in ("done", "failed"):
        # Try one more poll
        poll = poll_result(job_id)
        if poll["status"] not in ("done", "failed"):
            return {"status": "pending", "error": "job not finished yet"}
        with _jobs_lock:
            job = _jobs.get(job_id)

    with _registry_lock:
        entry = _registry.get(job["coder_name"])

    if not entry:
        # Coder gone, but we have cached result
        result = job.get("result") or {}
        return {
            "status": job["status"],
            "commit": result.get("commit"),
            "diff_stats": result.get("diff_stats"),
            "test_results": result.get("test_results"),
            "text": result.get("text", ""),
            "cost_usd": result.get("cost_usd", 0.0),
            "returncode": 1 if job["status"] == "failed" else 0,
            "coder": job["coder_name"],
            "branch": job["branch"],
            "remote": True,
        }

    # Fetch detailed result from the remote coder
    resp = _http(entry["host"], entry["port"], f"/result/{job_id}", timeout=30)
    if not resp:
        resp = job.get("result") or {}

    return {
        "status": job["status"],
        "commit": resp.get("commit"),
        "diff_stats": resp.get("diff_stats"),
        "test_results": resp.get("test_results"),
        "text": resp.get("text", ""),
        "cost_usd": resp.get("cost_usd", 0.0),
        "input_tokens": resp.get("input_tokens", 0),
        "output_tokens": resp.get("output_tokens", 0),
        "returncode": resp.get("returncode", 1 if job["status"] == "failed" else 0),
        "coder": job["coder_name"],
        "branch": job["branch"],
        "remote": True,
        "latency_ms": int((time.time() - job["dispatched_at"]) * 1000),
    }


def pool_status() -> dict:
    """Combined status of local + remote coders: who's busy, who's free, capacity."""
    remotes = {}
    with _registry_lock:
        for name, entry in _registry.items():
            remotes[name] = {
                "host": entry["host"],
                "port": entry["port"],
                "healthy": entry.get("healthy", False),
                "jobs_active": entry["jobs_active"],
                "max_concurrent": _MAX_CONCURRENT,
                "free_slots": max(0, _MAX_CONCURRENT - entry["jobs_active"]),
                "last_seen": entry["last_seen"],
                "capabilities": entry["capabilities"],
            }

    # Try to include local coder info from agentic_coders
    local_coders = []
    try:
        import agentic_coders
        local_coders = agentic_coders.available()
    except Exception:
        pass

    return {
        "local": local_coders,
        "remote": remotes,
        "total_remote_free": sum(r["free_slots"] for r in remotes.values()),
        "total_remote_busy": sum(r["jobs_active"] for r in remotes.values()),
    }


def stats() -> dict:
    """Module statistics."""
    with _jobs_lock:
        active_jobs = sum(1 for j in _jobs.values() if j["status"] in ("dispatched", "running"))
    with _registry_lock:
        registered_count = len(_registry)
        healthy_count = sum(1 for e in _registry.values() if e.get("healthy"))

    return {
        **_stats,
        "active_jobs": active_jobs,
        "total_jobs": len(_jobs),
        "registered_coders": registered_count,
        "healthy_coders": healthy_count,
    }
