#!/usr/bin/env python3
"""
db.py - tiny Supabase (PostgREST) client over urllib. No third-party deps.
The runner uses the SERVICE ROLE key so it bypasses RLS. Set:
    SUPABASE_URL=https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY=<service-role key>   (keep secret; never ship to the web app)
"""
import os, re, json, socket, time, datetime, threading, urllib.request, urllib.parse, urllib.error

# ... rest of code ...

def claim_task(runner_id):
    """Atomically grab one QUEUED task whose deps are satisfied. ECONOMIC ORDERING: within a
    project-priority band, prefer higher-ROI projects (projects.concurrency_weight, set from
    cost-per-merge by roi.py) and then FIFO. This makes the highest expected-value work run first
    under any capacity limit — and stays correct across MULTIPLE machines because the final claim
    is an atomic optimistic PATCH (state=QUEUED -> RUNNING), so two runners never double-claim."""
    # ... rest of code ...

    queued = select("tasks", {"select": "id,slug,project_id,deps,confidence,created_at,kind,note",
                              "state": "eq.QUEUED",
                              "order": "created_at.asc",
                              "limit": str(CLAIM_SCAN_LIMIT)}) or []
    queued = [t for t in queued if t.get("project_id") not in paused_pids]  # skip paused projects

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
    # ... rest of code ...
