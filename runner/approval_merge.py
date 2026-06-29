#!/usr/bin/env python3
"""
approval_merge.py - closes the human-in-the-loop COMPLETION loop.

When you approve a merge card (dashboard/Slack just set status='approved'), nothing used to
happen. This job finds approved merge cards and actually performs the merge for the matching
task: local fast-forward merge of agent/<slug> into the project's base branch, gated by tests.

Safety:
  - honors the kill switch (won't run while paused; the scheduler also gates it)
  - honors two-key: cards needing 2 approvals are skipped until a second_approver is set
  - test gate: if tests fail or the merge isn't fast-forwardable, it does NOT merge (marks
    the task TESTFAIL/CONFLICT and leaves a note) - never force-merges
  - idempotent: marks each handled card via decided_by so it's never merged twice
  - no model spend (pure git + tests), so it doesn't touch the $/day budget
"""
import os, sys, re, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MARK = "merge-handler"          # decided_by sentinel => already processed
MERGE_KINDS = ("verify", "material", "integrate")
TEST_CMD = os.environ.get("TEST_CMD", "npm test")


def _slug_from(card):
    if card.get("slug"):
        return card["slug"]
    m = re.search(r"merge of ([A-Za-z0-9._\-/]+)", card.get("title", ""), re.I)
    return m.group(1) if m else None


def _branch_exists(repo, branch):
    return subprocess.run(["git", "rev-parse", "--verify", branch], cwd=repo,
                          capture_output=True).returncode == 0


def _integrate(repo, branch, base, test_cmd=TEST_CMD):
    """Local ff-merge with a test gate. Mirrors runner.integrate (local mode)."""
    if subprocess.run(["git", "rebase", base, branch], cwd=repo, capture_output=True).returncode != 0:
        subprocess.run(["git", "rebase", "--abort"], cwd=repo, capture_output=True)
        return "CONFLICT"
    subprocess.run(["git", "checkout", branch], cwd=repo, capture_output=True)
    if subprocess.run(TEST_CMD, cwd=repo, shell=True, capture_output=True).returncode != 0:
        subprocess.run(["git", "checkout", base], cwd=repo, capture_output=True)
        return "TESTFAIL"
    subprocess.run(["git", "checkout", base], cwd=repo, capture_output=True)
    subprocess.run(["git", "merge", "--ff-only", branch], cwd=repo, capture_output=True)
    return "MERGED"


def _notify(msg):
    try:
        import notify; notify.send(msg)
    except Exception:
        print(f"[approval_merge] {msg}")


def run():
    try:
        import kill_switch
        if kill_switch.is_paused():
            print("approval_merge: paused — skipping")
            return
    except Exception:
        pass

    cards = db.select("approvals", {"select": "*", "status": "eq.approved"}) or []
    projects = {p["id"]: p for p in (db.select("projects") or [])}
    handled = 0
    for c in cards:
        if c.get("kind") not in MERGE_KINDS:
            continue
        if str(c.get("decided_by") or "").startswith(MARK):
            continue  # already processed
        # two-key: needs a second approver before we merge
        if int(c.get("approvals_required") or 1) >= 2 and not c.get("second_approver"):
            continue
        slug = _slug_from(c)
        if not slug:
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:no-slug"})
            continue
        tasks = db.select("tasks", {"select": "*", "slug": f"eq.{slug}"}) or []
        t = next((x for x in tasks if x["state"] == "BLOCKED"), tasks[0] if tasks else None)
        if not t:
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:no-task"})
            continue
        proj = projects.get(t["project_id"], {})
        repo = proj.get("repo_path", "")
        base = t.get("base_branch") or proj.get("default_base", "main")
        branch = f"agent/{slug}"
        if not repo or not os.path.isdir(repo):
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:no-repo"})
            continue
        if not _branch_exists(repo, branch):
            # the agent branch is gone (e.g., old card) - don't silently re-spend; flag it
            db.update("tasks", {"id": t["id"]}, {"state": "BLOCKED",
                      "note": f"approved, but {branch} no longer exists - re-queue to rebuild"})
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:branch-missing"})
            _notify(f"[merge] '{slug}' approved but branch {branch} is gone — re-queue to rebuild.")
            handled += 1
            continue
        result = _integrate(repo, branch, base, proj.get("test_cmd") or TEST_CMD)
        db.update("tasks", {"id": t["id"]}, {"state": result,
                  "note": f"merge-handler: {result} (approved by {c.get('decided_by') or 'you'})"})
        db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:{result}"})
        _notify(f"[merge] {slug} -> {base}: {result}")
        handled += 1
    print(f"approval_merge: processed {handled} approved card(s)")
    return handled


if __name__ == "__main__":
    run()
