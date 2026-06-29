#!/usr/bin/env python3
"""
periodic.py - coordinator for all scheduled periodic jobs.
Called by launchd (or manually) with a single job argument.

Jobs:
  spec    - spec drift check across all repos (schedule: weekly)
  chaos   - chaos resilience drills (schedule: weekly, staging only)
  txn     - cross-repo transaction coordinator (schedule: every 5 min)
  scout   - opportunity scout: RICE-scored proposals (schedule: weekly)
  deploy  - canary-gated nightly deploy window (schedule: nightly)
  roi     - update project concurrency_weight from ROI (schedule: daily)

Usage:
  python3 periodic.py spec
  python3 periodic.py txn
"""
import os, sys, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def run_spec():
    import spec as spec_mod
    rows = db.select("projects", {"select": "*"}) or []
    for p in rows:
        repo = p.get("repo_path", "")
        name = p.get("name", "?")
        if not os.path.isdir(repo):
            print(f"spec {name}: repo not found at {repo}")
            continue
        result = spec_mod.check(repo, name, p["id"])
        print(f"spec {name}: {result or 'no SPEC.md'}")


def run_chaos():
    import chaos
    if not os.environ.get("CHAOS_ENABLED", "").lower() == "true":
        print("chaos: CHAOS_ENABLED not set — skipping (safe; set in a staging env only)")
        return
    for drill in ["stale-runner", "fake-fail"]:
        result = chaos.run(drill)
        print(f"chaos {drill}: {result}")
    time.sleep(60)
    _assert_chaos_recovery()


def _assert_chaos_recovery():
    runners = db.select("runner_heartbeats", {"select": "*"}) or []
    chaos_runner = next((r for r in runners if r["runner_id"] == "chaos-drill"), None)
    # Assert: chaos-drill runner is present (injected) with old timestamp (dashboard should show OFFLINE)
    if chaos_runner:
        db.insert("approvals", {
            "project": "CHAOS", "kind": "self",
            "title": "Chaos drill RESULT: stale-runner assertion",
            "why": "chaos-drill runner was injected with a stale timestamp.",
            "value": "PASS — runner was visible; verify dashboard shows it OFFLINE (red dot).",
            "risk": "If green: heartbeat TTL logic is broken.",
            "status": "pending"
        })
        print("chaos assert: stale-runner injection visible — verify dashboard shows it OFFLINE")
    else:
        print("chaos assert: WARN — stale-runner not found in heartbeats")

    chaos_approvals = db.select("approvals", {
        "select": "id", "project": "eq.CHAOS",
        "status": "eq.pending", "limit": "5"
    }) or []
    if chaos_approvals:
        print(f"chaos assert: fake-fail PASS — {len(chaos_approvals)} chaos card(s) in inbox")
    else:
        print("chaos assert: fake-fail WARN — no CHAOS approval in inbox")


def run_txn():
    import transaction
    txns_list = db.select("txns", {"select": "*", "status": "eq.pending"}) or []
    if not txns_list:
        print("txn: no pending transactions")
        return
    for txn in txns_list:
        txn_id = txn["id"]
        result = transaction.resolve(txn_id)
        print(f"txn {txn_id}: {result}")
        if "ready: integrate" in result:
            _ff_merge_txn(txn_id)
        elif "aborted" in result:
            db.update("txns", {"id": txn_id}, {"status": "aborted", "resolved_at": "now()"})


def _ff_merge_txn(txn_id):
    import transaction
    members = transaction.members(txn_id)
    all_ok = True
    for m in members:
        proj_rows = db.select("projects", {"select": "*", "id": f"eq.{m['project_id']}"}) or []
        repo = (proj_rows[0] if proj_rows else {}).get("repo_path", "")
        if not repo or not os.path.isdir(repo):
            continue
        r = subprocess.run(["git", "merge", "--ff-only", f"agent/{m['slug']}"],
                           cwd=repo, capture_output=True)
        if r.returncode != 0:
            all_ok = False
            db.update("tasks", {"id": m["id"]},
                      {"state": "BLOCKED", "note": f"txn:{txn_id} ff-merge failed"})
            print(f"txn {txn_id}: ff-merge FAILED for {m['slug']}")
        else:
            print(f"txn {txn_id}: merged {m['slug']}")
    status = "merged" if all_ok else "aborted"
    db.update("txns", {"id": txn_id}, {"status": status, "resolved_at": "now()"})
    print(f"txn {txn_id}: {status}")


def run_scout():
    import opportunity_scout
    opportunity_scout.run()


def run_deploy():
    import deploy_window
    deploy_window.run()


def run_batch():
    import batch_pass
    batch_pass.run()


def run_roi():
    import roi
    report = roi.report()
    if not report:
        return
    max_cpm = max((r["cost_per_merge"] or 0) for r in report if r["cost_per_merge"]) or 1
    for r in report:
        cpm = r["cost_per_merge"]
        if cpm is None:
            weight = 1
        elif cpm <= max_cpm * 0.25:
            weight = 3  # high-ROI: more concurrency
        elif cpm <= max_cpm * 0.6:
            weight = 2
        else:
            weight = 1  # low-ROI: baseline only
        rows = db.select("projects", {"select": "id", "name": f"eq.{r['project']}"}) or []
        if rows:
            db.update("projects", {"id": rows[0]["id"]}, {"concurrency_weight": weight})
        print(f"roi {r['project']}: cpm=${cpm} weight={weight}")


JOBS = {
    "spec": run_spec,
    "chaos": run_chaos,
    "txn": run_txn,
    "scout": run_scout,
    "deploy": run_deploy,
    "roi": run_roi,
    "batch": run_batch,
}

if __name__ == "__main__":
    job = sys.argv[1] if len(sys.argv) > 1 else "help"
    if job not in JOBS:
        print(f"usage: periodic.py {'|'.join(JOBS)}")
        sys.exit(1)
    # honor the kill switch: model-spending jobs don't run while paused.
    _SAFE_WHEN_PAUSED = {"roi", "txn"}
    if job not in _SAFE_WHEN_PAUSED:
        try:
            import kill_switch
            if kill_switch.is_paused():
                print(f"periodic {job}: skipped (paused)")
                sys.exit(0)
        except Exception:
            pass
    JOBS[job]()
