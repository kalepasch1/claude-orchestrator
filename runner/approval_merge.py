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
  - auto-approval: low-risk cards (integrate/material + build/bugfix + tests pass + safe paths)
    are auto-approved + merged without human gates (ORCH_AUTOAPPROVE_LOWRISK=true by default)
  - no model spend (pure git + tests), so it doesn't touch the $/day budget
"""
import os, sys, re, subprocess, fnmatch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MARK = "merge-handler"          # decided_by sentinel => already processed
MARK_AUTO = "auto-policy"       # decided_by for auto-approved cards
MERGE_KINDS = ("verify", "material", "integrate")
TEST_CMD = os.environ.get("TEST_CMD", "npm test")
AUTOAPPROVE_ENABLED = os.environ.get("ORCH_AUTOAPPROVE_LOWRISK", "true").lower() in ("true", "1", "yes")

# Deny-list of sensitive path globs that should NOT be auto-approved
SENSITIVE_PATHS = [
    "*/pricing*", "*/price*", "*/cost*",
    "*/regulatory*", "*/compliance*", "*/legal*",
    "*/auth*", "*/login*", "*/password*", "*/token*", "*/oauth*",
    "*/rls*", "*/row_level_security*", "*/security*",
    "*/policy*", "*/permission*",
    "*/data_use*", "*/data_retention*", "*/gdpr*", "*/privacy*",
    "*/.env*", "*/secrets*",
]


def _touches_sensitive_paths(repo, branch, base):
    """Check if diff between base and branch touches any sensitive paths."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}..{branch}"],
            cwd=repo, capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return True  # Err on side of caution if we can't check
        changed_files = result.stdout.strip().split("\n") if result.stdout.strip() else []
        for file in changed_files:
            if not file:
                continue
            for pattern in SENSITIVE_PATHS:
                if fnmatch.fnmatch(file, pattern) or fnmatch.fnmatch(file.lower(), pattern.lower()):
                    return True
        return False
    except Exception as e:
        print(f"[approval_merge] warning: _touches_sensitive_paths failed: {e}")
        return True  # Err on side of caution


def _should_autoapprove(card, task):
    """Check if a card should be auto-approved (low-risk criteria)."""
    if not AUTOAPPROVE_ENABLED:
        return False
    # Low-risk: card kind in (integrate, material)
    if card.get("kind") not in ("integrate", "material"):
        return False
    # Task kind must be build or bugfix (not research, efficiency, self)
    task_kind = task.get("kind", "").lower()
    if task_kind not in ("build", "bugfix"):
        return False
    return True


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

    # Process both approved cards and pending cards that can be auto-approved
    approved_cards = db.select("approvals", {"select": "*", "status": "eq.approved"}) or []
    pending_cards = db.select("approvals", {"select": "*", "status": "eq.pending"}) or [] if AUTOAPPROVE_ENABLED else []
    cards = approved_cards + pending_cards

    projects = {p["id"]: p for p in (db.select("projects") or [])}
    handled = 0
    auto_approved = 0

    for c in cards:
        if c.get("kind") not in MERGE_KINDS:
            continue
        if str(c.get("decided_by") or "").startswith(MARK):
            continue  # already processed

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
            db.update("tasks", {"id": t["id"]}, {"state": "BLOCKED",
                      "note": f"approved, but {branch} no longer exists - re-queue to rebuild"})
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:branch-missing"})
            _notify(f"[merge] '{slug}' approved but branch {branch} is gone — re-queue to rebuild.")
            handled += 1
            continue

        # Auto-approve logic for pending cards
        is_auto_candidate = False
        if c.get("status") == "pending" and _should_autoapprove(c, t):
            # Check if diff touches sensitive paths
            if not _touches_sensitive_paths(repo, branch, base):
                # Mark as approved before attempting merge
                db.update("approvals", {"id": c["id"]}, {"status": "approved", "decided_by": f"{MARK_AUTO}:approved"})
                is_auto_candidate = True
                auto_approved += 1
                _notify(f"[auto-approve] {slug}: low-risk card auto-approved")

        # Two-key check: skip if needs second approval and doesn't have it
        if c.get("status") == "approved":  # Only merge approved cards
            if int(c.get("approvals_required") or 1) >= 2 and not c.get("second_approver"):
                continue

            result = _integrate(repo, branch, base, proj.get("test_cmd") or TEST_CMD)
            decided_marker = f"{MARK_AUTO}:{result}" if is_auto_candidate else f"{MARK}:{result}"
            db.update("tasks", {"id": t["id"]}, {"state": result,
                      "note": f"merge-handler: {result} (approved by {decided_marker})"})
            db.update("approvals", {"id": c["id"]}, {"decided_by": decided_marker})
            _notify(f"[merge] {slug} -> {base}: {result}")
            handled += 1

    print(f"approval_merge: processed {handled} card(s) ({auto_approved} auto-approved)")
    return handled


if __name__ == "__main__":
    run()
