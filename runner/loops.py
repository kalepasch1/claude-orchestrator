#!/usr/bin/env python3
"""
loops.py - ensures EVERY app has continuous autonomous learning + remediation loops, and
runs the ones that are due. The orchestrator manages these per-app loops (cadence + config
in the `loops` table). Types:
  remediate -> watchdog (health -> auto-fix)      optimize -> optimizer/efficiency scan
  learn     -> opportunity_scout (new ideas)      review   -> self_review (meta-improvement)
Run frequently (e.g. every 5 min); it only fires loops past their cadence.
"""
import os, sys, time, datetime, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

DEFAULTS = {"remediate": 300, "optimize": 86400, "learn": 604800, "review": 86400}
HERE = os.path.dirname(os.path.abspath(__file__))


def _parse_ts(value):
    """Parse Supabase timestamps even when PostgREST trims fractional seconds."""
    raw = str(value or "").replace("Z", "+00:00")
    if "." in raw:
        head, tail = raw.split(".", 1)
        zone = ""
        for sep in ("+", "-"):
            idx = tail.find(sep)
            if idx > 0:
                zone = tail[idx:]
                tail = tail[:idx]
                break
        tail = (tail + "000000")[:6]
        raw = f"{head}.{tail}{zone}"
    return datetime.datetime.fromisoformat(raw).timestamp()


def ensure_all():
    projects = db.select("projects", {"select": "name"}) or []
    existing = {(l["project"], l["type"]) for l in (db.select("loops", {"select": "project,type"}) or [])}
    made = 0
    for p in projects:
        for typ, cad in DEFAULTS.items():
            if (p["name"], typ) not in existing:
                db.insert("loops", {"project": p["name"], "type": typ, "cadence_seconds": cad, "enabled": True})
                made += 1
    print(f"loops.ensure_all: created {made} missing loops"); return made


def _due(loop):
    if not loop.get("enabled"):
        return False
    if not loop.get("last_run"):
        return True
    last = _parse_ts(loop["last_run"])
    return time.time() - last >= loop.get("cadence_seconds", 1800)


def run_due():
    ensure_all()
    loops = db.select("loops", {"select": "*"}) or []
    due = [loop for loop in loops if _due(loop)]
    if not due:
        print("loops.run_due: fired 0 loops")
        return 0

    # These handlers already iterate the whole portfolio internally. The old
    # per-row dispatch ran the same fleet scan once for every app (roughly 15x).
    # Only optimizer-pass is truly scoped by the loop row's repo.
    fleet_handler_types = {loop.get("type") for loop in due if loop.get("type") != "optimize"}
    fired_fleet_handlers = set()
    try:
        operator_pending = bool(db.select("tasks", {
            "select": "id", "state": "in.(QUEUED,RUNNING,DONE,RETRY)",
            "submitted_by": "not.is.null", "limit": "1",
        }) or db.select("tasks", {
            "select": "id", "state": "in.(QUEUED,RUNNING,DONE,RETRY)",
            "slug": "like.dropbox-*", "limit": "1",
        }) or [])
    except Exception:
        operator_pending = True
    fired = 0
    deferred = 0
    for loop in due:
        typ, project = loop["type"], loop["project"]
        if operator_pending and typ in {"review", "learn", "optimize", "colosseum", "creative_gen", "growth_learn"}:
            deferred += 1
            continue
        if typ in fleet_handler_types and typ in fired_fleet_handlers:
            # The one fleet-wide call covers this row; advance its receipt without
            # re-running the same handler for every project.
            db.update("loops", {"id": loop["id"]}, {"last_run": datetime.datetime.utcnow().isoformat()})
            continue
        if typ in fleet_handler_types:
            # Mark before invocation: a failing fleet handler must not be retried
            # once per remaining app in the same scheduler cycle.
            fired_fleet_handlers.add(typ)
        try:
            if typ == "remediate":
                import watchdog; watchdog.check()
            elif typ == "review":
                import self_review; self_review.run()
            elif typ == "learn":
                import opportunity_scout; opportunity_scout.run()
            elif typ == "colosseum":
                import growth_colosseum; growth_colosseum.run()
            elif typ == "bd_autopilot":
                import bd_autopilot_tick; bd_autopilot_tick.run()
            elif typ == "creative_gen":
                import growth_creative_gen; growth_creative_gen.run()
            elif typ == "growth_learn":
                import growth_learn; growth_learn.run()
            elif typ == "security_rls":
                import rls_guard; rls_guard.run()
            elif typ == "deploy_watch":
                import deploy_watch; deploy_watch.run()
            elif typ == "queue_groom":
                import queue_groom; queue_groom.run()
            elif typ == "deploy_canary":
                import deploy_canary; deploy_canary.run()
            elif typ == "preflight":
                import preflight_gate; preflight_gate.run()
            elif typ == "optimize":
                repo = (db.select("projects", {"select": "repo_path", "name": f"eq.{project}"}) or [{}])[0].get("repo_path")
                if repo and os.path.isdir(repo):
                    subprocess.run(["bash", os.path.join(HERE, "..", "scripts", "optimizer-pass.sh")],
                                   cwd=repo, capture_output=True)
        except Exception as e:
            print(f"loop {typ}/{project} error: {e}")
        db.update("loops", {"id": loop["id"]}, {"last_run": datetime.datetime.utcnow().isoformat()})
        fired += 1
    print(f"loops.run_due: fired {fired} handlers; deferred {deferred} speculative rows")
    return fired


if __name__ == "__main__":
    run_due()
