#!/usr/bin/env python3
"""
action_runner.py - executes ONLY the safe, you-clicked operator steps queued from the cockpit's
"Run for me" button. Defense-in-depth: even though action_drafter marked a command executable, this
re-validates it against the same SAFE allowlist + UNSAFE denylist right before running, runs it in the
correct repo, captures the result, and marks the linked approval done. Anything not on the allowlist is
refused and left for you to run manually.

NEVER runs: secrets/token/key writes, payments/transfers, deletes/drops, force pushes, revokes.
The user must have clicked "Run for me" (which inserts the action_runs row) — nothing auto-executes.
"""
import os, sys, subprocess, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
from action_drafter import SAFE_CMD, UNSAFE


def _repo_for(approval_id: str) -> str:
    a = (db.select("approvals", {"select": "project", "id": f"eq.{approval_id}"}) or [{}])[0]
    name = a.get("project")
    p = (db.select("projects", {"select": "repo_path", "name": f"eq.{name}"}) or [{}])[0]
    return p.get("repo_path", "")


def run() -> int:
    # honor the global kill switch: no execution while paused
    try:
        import kill_switch
        if kill_switch.is_paused():
            print("action_runner: paused"); return 0
    except Exception:
        pass
    jobs = db.select("action_runs", {"select": "*", "status": "eq.queued", "limit": "5"}) or []
    ran = 0
    for j in jobs:
        cmd = (j.get("cmd") or "").strip()
        # hard re-validation right before executing
        if not cmd or not SAFE_CMD.match(cmd) or UNSAFE.search(cmd):
            db.update("action_runs", {"id": j["id"]},
                      {"status": "failed", "result": "refused: not on safe allowlist — run manually",
                       "finished_at": datetime.datetime.utcnow().isoformat()})
            continue
        repo = _repo_for(j.get("approval_id"))
        if not repo or not os.path.isdir(repo):
            db.update("action_runs", {"id": j["id"]},
                      {"status": "failed", "result": "repo not found on this machine",
                       "finished_at": datetime.datetime.utcnow().isoformat()})
            continue
        db.update("action_runs", {"id": j["id"]}, {"status": "running"})
        try:
            p = subprocess.run(["bash", "-lc", cmd], cwd=repo, capture_output=True, text=True, timeout=600)
            ok = p.returncode == 0
            out = (p.stdout[-1500:] + "\n" + p.stderr[-500:]).strip()
            db.update("action_runs", {"id": j["id"]},
                      {"status": "done" if ok else "failed", "result": out[:2000],
                       "finished_at": datetime.datetime.utcnow().isoformat()})
            if ok and j.get("approval_id"):
                db.update("approvals", {"id": j["approval_id"]},
                          {"status": "approved", "exec_status": "done",
                           "decided_by": "run-for-me", "decided_at": "now()"})
            ran += 1
        except Exception as e:
            db.update("action_runs", {"id": j["id"]},
                      {"status": "failed", "result": str(e)[:500],
                       "finished_at": datetime.datetime.utcnow().isoformat()})
    if ran:
        print(f"action_runner: executed {ran} safe operator step(s)")
    return ran


def auto_execute() -> int:
    """Auto-run the SAFE majority: executable action items whose exact command has SUCCEEDED before
    (track record) get queued automatically — no click — with the same allowlist re-check + the runner's
    result capture (so a failure is visible and reversible). OFF unless ORCH_AUTO_EXEC_SAFE=true."""
    if os.environ.get("ORCH_AUTO_EXEC_SAFE", "false").lower() != "true":
        return 0
    try:
        import kill_switch
        if kill_switch.is_paused():
            return 0
    except Exception:
        pass
    # commands proven safe by a prior successful run
    proven = {r.get("cmd") for r in (db.select("action_runs", {"select": "cmd,status",
              "status": "eq.done"}) or []) if r.get("cmd")}
    cards = db.select("approvals", {"select": "id,draft_cmd", "status": "eq.pending",
                                    "kind": "eq.operator", "executable": "eq.true",
                                    "exec_status": "is.null", "limit": "20"}) or []
    queued = 0
    for a in cards:
        cmd = (a.get("draft_cmd") or "").strip()
        if not cmd or cmd not in proven or not SAFE_CMD.match(cmd) or UNSAFE.search(cmd):
            continue
        db.insert("action_runs", {"approval_id": a["id"], "cmd": cmd,
                                  "requested_by": "auto-exec", "status": "queued"})
        db.update("approvals", {"id": a["id"]}, {"exec_status": "queued", "auto_exec_ok": True})
        queued += 1
    if queued:
        print(f"action_runner.auto_execute: queued {queued} proven-safe operator step(s)")
    return queued


if __name__ == "__main__":
    auto_execute()
    run()
