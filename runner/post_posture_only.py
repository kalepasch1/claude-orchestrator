#!/usr/bin/env python3
"""post_posture_only.py — keep db-steering/posture posting while the fleet is paused.

WHY THIS EXISTS. `db-steering/posture` is a REQUIRED status on kalepasch1/smarter and
kalepasch1/tomorrow, so when it stops being posted every pull request in those repos is
blocked -- not failing,
blocked, with the reason nowhere on the page. On 2026-09-22 that is exactly what
happened: two PRs sat unmergeable for hours with all nine real checks green.

WHY IT STOPPED, which is the part that matters. The fleet loop that posts it lives in
the ClaudeRunner job, and that job is deliberately paused:

    .runtime/maintenance.lock
    paused-at: 2026-09-22T16:47:36Z   (the last status was posted at 16:50)
    reason: concurrent orchestrator builds drove load average past 240 with <1 GB
            free of 52 GB, OOM-killing a lane's Nuxt build.
    requested-by: the repository owner.

That pause is correct and this module does not touch it. Measured at 18:24 the same
day, the condition still held: load average 57 and 99 MB of memory unused. Lifting
the lock to get a commit status posted would trade a merge for an OOM.

WHAT THIS DOES INSTEAD. The narrowest slice that produces the status:

    db_steering.scan_source()   each listed project, so findings are current
    db_deploy_gate.run_cycle()  the listed projects, so the status is posted

and nothing else. No remediation filing, no memo composition, no agent dispatch, no
builds -- all of which db_steering.run() would do, and all of which are what made the
machine unusable. This is Supabase reads and a handful of GitHub API calls: network,
not CPU.

IT STILL CHECKS THE LOAD. The whole reason the fleet is paused is load, so a job that
ignored load would be answering the wrong lesson. Above LOAD_CEILING it declines and
says so, because a commit status is never worth making a thrashing machine worse.

TO REMOVE:
    launchctl bootout gui/501/com.claudeorchestrator.posture-only
    rm ~/Library/LaunchAgents/com.claudeorchestrator.posture-only.plist

TO GO BACK TO THE REAL LOOP (which supersedes this entirely), once the machine is
free, follow the lock's own instructions:
    rm .runtime/maintenance.lock
    launchctl kickstart -k gui/501/com.claudeorchestrator.runner
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Every repo whose branch protection REQUIRES db-steering/posture must be listed here,
#: or its pull requests are blocked with every real check green. Until 2026-09-30 this
#: was a single project ("smarter"), and kalepasch1/tomorrow -- which also requires the
#: context -- received no posture status after the fleet was paused on 2026-09-22.
#: POSTURE_ONLY_PROJECTS is a comma list; the singular POSTURE_ONLY_PROJECT is still
#: honoured so an existing launchd environment keeps working.
DEFAULT_PROJECTS = "smarter,tomorrow"


def _projects() -> list:
    raw = os.environ.get("POSTURE_ONLY_PROJECTS") or os.environ.get("POSTURE_ONLY_PROJECT") or DEFAULT_PROJECTS
    return list(dict.fromkeys(p.strip() for p in raw.split(",") if p.strip()))


#: One core's worth of queue per core is already heavy; this box has been at 240.
LOAD_CEILING = float(os.environ.get("POSTURE_ONLY_LOAD_CEILING", "120"))


def _load1() -> float:
    try:
        return os.getloadavg()[0]
    except Exception:
        return 0.0


def _scan(project: str) -> dict:
    """Refresh one project's findings so the gate reads current posture."""
    import db_registry
    import db_steering

    sources = db_registry.list_sources(enabled_only=True, project=project) or []
    if not sources:
        return {"error": "no enabled source for project %r" % project}
    try:
        scan = db_steering.scan_source(sources[0], dry_run=False)
        delta = scan.get("delta") or {}
        return {
            "ok": scan.get("ok"),
            "new": len(delta.get("new") or []),
            "resolved": len(delta.get("resolved") or []),
        }
    except Exception as e:
        # A scan that fails must not stop the post: the previous findings are still
        # the best available answer, and a stale status is better than no status at
        # all on a REQUIRED check.
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:160])}


def main() -> dict:
    projects = _projects()
    out = {"projects": projects, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    load = _load1()
    out["load1"] = round(load, 2)
    if load > LOAD_CEILING:
        # Declining loudly, not silently: a guard that skips without saying so is the
        # defect this fleet keeps finding in itself.
        out["skipped"] = "load %.1f above ceiling %.1f; a commit status is not worth making this worse" % (load, LOAD_CEILING)
        return out

    # The gate reads findings, so they are refreshed first -- otherwise a fixed
    # high-severity finding keeps the status red until something else rescans.
    out["scan"] = {p: _scan(p) for p in projects}

    # ENABLED is read at import time from ORCH_DB_DEPLOY_GATE, so it is set before the
    # module is imported rather than after.
    os.environ["ORCH_DB_DEPLOY_GATE"] = "1"
    import db
    import db_deploy_gate

    rows = db.select("projects", {
        "select": "name,vercel_project,prod_branch,default_base,staging_branch,repo_path,superseded_by",
        "name": "in.(%s)" % ",".join(projects),
    }) or []
    missing = sorted(set(projects) - {str(r.get("name") or "") for r in rows})
    if missing:
        # Reported, not fatal: one unknown name must not stop the others posting.
        out["missing_projects"] = missing
    if not rows:
        out["error"] = "no projects rows for %r" % projects
        return out
    out["gate"] = db_deploy_gate.run_cycle(projects=rows)
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, default=str))
