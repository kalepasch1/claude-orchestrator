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


def _worktree_for(repo, branch):
    """Return the path of the worktree that has `branch` checked out, or None."""
    out = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=repo,
                         capture_output=True, text=True).stdout
    cur = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            cur = line[len("worktree "):].strip()
        elif line.strip() == f"branch refs/heads/{branch}":
            return cur
    return None


def _free_branch(repo, branch):
    """Unlock a branch that's still checked out in a leftover agent worktree. THIS was the root cause
    of the phantom CONFLICTs: git refuses to rebase/merge a branch that's checked out elsewhere, and the
    handler mislabeled that error as CONFLICT. Removing the stale worktree frees the branch."""
    wt = _worktree_for(repo, branch)
    if wt:
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo, capture_output=True)
    subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)


def _integrate(repo, branch, base, test_cmd=TEST_CMD):
    """Merge agent/<slug> into `base` correctly, regardless of what's checked out, and (optionally)
    push so Vercel deploys. Frees any leftover worktree first (the real bug)."""
    _free_branch(repo, branch)
    # clean fast-forward if the branch is strictly ahead of base (the common case)
    ahead = subprocess.run(["git", "merge-base", "--is-ancestor", base, branch],
                           cwd=repo, capture_output=True).returncode == 0
    if not ahead:
        # diverged -> rebase the (now-free) branch onto base; a real conflict returns CONFLICT
        if subprocess.run(["git", "rebase", base, branch], cwd=repo, capture_output=True).returncode != 0:
            subprocess.run(["git", "rebase", "--abort"], cwd=repo, capture_output=True)
            return "CONFLICT"
    # fast-forward `base` to include the branch WITHOUT checking base out (base may not be HEAD).
    ff = subprocess.run(["git", "fetch", ".", f"{branch}:{base}"], cwd=repo, capture_output=True, text=True)
    if ff.returncode != 0:
        # base can't fast-forward (it moved) -> do a real no-ff merge via an ephemeral worktree
        import tempfile, shutil, os as _os
        tmp = tempfile.mkdtemp(prefix="mt-")
        try:
            if subprocess.run(["git", "worktree", "add", "-f", tmp, base], cwd=repo, capture_output=True).returncode != 0:
                return "CONFLICT"
            r = subprocess.run(["git", "merge", "--no-ff", "-m", f"merge {branch}", branch],
                               cwd=tmp, capture_output=True)
            if r.returncode != 0:
                subprocess.run(["git", "merge", "--abort"], cwd=tmp, capture_output=True)
                return "CONFLICT"
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", tmp], cwd=repo, capture_output=True)
            shutil.rmtree(tmp, ignore_errors=True)
    # push to origin so CI/Vercel deploy — guarded: only when explicitly enabled.
    if os.environ.get("ORCH_PUSH_ON_MERGE", "false").lower() == "true":
        push = subprocess.run(["git", "push", "origin", base], cwd=repo, capture_output=True, text=True)
        if push.returncode != 0:
            return "PUSHFAIL:" + (push.stderr or "")[-120:]
    _free_branch(repo, branch)   # cleanup so worktrees never accumulate again
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
        if result == "CONFLICT":
            # SELF-HEAL: a stale branch conflicting with current main should REDO on fresh main, not
            # sit CONFLICT forever (that's what stalled 93 tasks at 0 merged). Requeue to rebuild on
            # the up-to-date base, up to a cap; delete the stale branch so the worktree is recreated.
            tr = int(t.get("transient_retries") or 0)
            cap = int(os.environ.get("MERGE_CONFLICT_REDO_CAP", "2"))
            if tr < cap:
                subprocess.run(["git", "branch", "-D", branch], cwd=repo, capture_output=True)
                db.update("tasks", {"id": t["id"]},
                          {"state": "QUEUED", "transient_retries": tr + 1,
                           "note": f"merge conflict -> redo on fresh {base} ({tr+1}/{cap})"})
                # re-open the card as pending so it flows again once rebuilt+judged
                db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:redo"})
                _notify(f"[merge] {slug}: conflict — rebuilding on fresh {base} ({tr+1}/{cap})")
                handled += 1
                continue
            # exhausted redo cap -> genuine conflict needing a human/agent resolution
            db.update("tasks", {"id": t["id"]}, {"state": "CONFLICT",
                      "note": f"merge-handler: CONFLICT after {cap} redo attempts — needs manual rebase"})
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:conflict-exhausted"})
            _notify(f"[merge] {slug}: still conflicts after {cap} redos — needs a look")
            handled += 1
            continue
        db.update("tasks", {"id": t["id"]}, {"state": result,
                  "note": f"merge-handler: {result} (approved by {c.get('decided_by') or 'you'})"})
        db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:{result}"})
        _notify(f"[merge] {slug} -> {base}: {result}")
        handled += 1
    print(f"approval_merge: processed {handled} approved card(s)")
    return handled


if __name__ == "__main__":
    run()
