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
    last = datetime.datetime.fromisoformat(loop["last_run"].replace("Z", "+00:00")).timestamp()
    return time.time() - last >= loop.get("cadence_seconds", 1800)


def run_due():
    ensure_all()
    loops = db.select("loops", {"select": "*"}) or []
    fired = 0
    for loop in loops:
        if not _due(loop):
            continue
        typ, project = loop["type"], loop["project"]
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
    print(f"loops.run_due: fired {fired} loops"); return fired


if __name__ == "__main__":
    run_due()
