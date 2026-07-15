#!/usr/bin/env python3
"""
approval_merge.py - closes the human-in-the-loop COMPLETION loop.

When you approve a merge card (dashboard/Slack just set status='approved'), nothing used to
happen. This job finds approved merge cards and actually performs the merge for the matching
task: local fast-forward merge of agent/<slug> into the project's base branch, gated by tests.

Safety:
  - honors the kill switch (won't run while paused; the scheduler also gates it)
  - code-merge cards are automatic by default; legal/operator cards are out of scope
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
import agentic_repair

MARK = "merge-handler"          # decided_by sentinel => already processed
MARK_AUTO = "auto-policy"       # decided_by for auto-approved cards
MERGE_KINDS = ("verify", "material", "integrate")
TEST_CMD = os.environ.get("TEST_CMD", "npm test")
AUTOAPPROVE_ENABLED = os.environ.get("ORCH_AUTOAPPROVE_LOWRISK", "true").lower() in ("true", "1", "yes")
AUTO_MERGE_APPROVALS = os.environ.get("ORCH_AUTO_MERGE_APPROVALS", "true").lower() in ("true", "1", "yes")

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


def _is_code_merge_card(card):
    title = card.get("title") or ""
    return bool(card.get("slug") or re.search(r"\bmerge of\b", title, re.I))


def _branch_exists(repo, branch):
    return subprocess.run(["git", "rev-parse", "--verify", branch], cwd=repo,
                          capture_output=True).returncode == 0


def _detect_prod_branch(repo, proj):
    for b in (proj.get("prod_branch"), proj.get("default_base"), "main", "master"):
        if b and subprocess.run(["git", "rev-parse", "--verify", b], cwd=repo,
                                capture_output=True).returncode == 0:
            return b
    return proj.get("default_base") or "main"


def _integration_base(repo, proj, task_base):
    if os.environ.get("ORCH_CODE_MERGE_TARGET", "dev").lower() not in ("dev", "staging", "integration"):
        return task_base
    dev = os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev")
    try:
        if subprocess.run(["git", "rev-parse", "--verify", dev], cwd=repo,
                          capture_output=True).returncode != 0:
            subprocess.run(["git", "branch", dev, _detect_prod_branch(repo, proj)],
                           cwd=repo, capture_output=True)
    except OSError:
        return task_base
    return dev


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


def _primary_worktree(repo):
    """Git lists the repository's main worktree first, even from a linked one."""
    out = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=repo,
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("worktree "):
            return line[len("worktree "):].strip()
    return None


def _free_branch(repo, branch):
    """Unlock a branch that's still checked out in a leftover agent worktree. THIS was the root cause
    of the phantom CONFLICTs: git refuses to rebase/merge a branch that's checked out elsewhere, and the
    handler mislabeled that error as CONFLICT. Removing the stale worktree frees the branch."""
    wt = _worktree_for(repo, branch)
    if wt:
        primary = _primary_worktree(repo)
        if primary and os.path.realpath(wt) == os.path.realpath(primary):
            return False
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo, capture_output=True)
    subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)
    return True


def _rebase_isolated(repo, base, branch):
    """Rebase `branch` onto `base` WITHOUT ever checking `branch` out in `repo` itself.

    `git rebase <base> <branch>` is shorthand for `git checkout <branch> && git rebase <base>` —
    every prior call site here did that directly in `repo`, the orchestrator's OWN primary
    checkout. A successful rebase left `repo` parked on `branch` afterward (only the conflict
    path tried `git rebase --abort`, which restores the branch you were on *before* the rebase
    started — but if a PRIOR call had already left `repo` on some other stray branch, abort just
    puts it back on that same wrong branch, not master). This is very likely the root cause of
    the 2026-07-08 finding that `repo`'s checked-out branch kept changing between unrelated
    checks minutes apart during a manual session.

    Fixed the same way the no-ff-merge fallback below already does it (that path already got
    this right, this one hadn't caught up): a `-f`-forced isolated worktree, so it works even
    though `branch` is very likely also checked out somewhere else already. Returns True on a
    clean rebase, False on conflict (branch's ref is left as it was, matching the original
    --abort behavior) or if the worktree itself couldn't be created."""
    wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt",
                      f"rebase-{branch.replace('/', '-')}")
    try:
        os.makedirs(os.path.dirname(wt), exist_ok=True)
        added = subprocess.run(["git", "worktree", "add", "-f", wt, branch], cwd=repo,
                               capture_output=True, timeout=60)
        if added.returncode != 0 or not os.path.isdir(wt):
            return False
        ok = subprocess.run(["git", "rebase", base], cwd=wt, capture_output=True).returncode == 0
        if not ok:
            subprocess.run(["git", "rebase", "--abort"], cwd=wt, capture_output=True)
        return ok
    finally:
        try:
            subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo,
                           capture_output=True, timeout=30)
        except Exception:
            pass


def _integrate(repo, branch, base, test_cmd=TEST_CMD):
    """Merge agent/<slug> into `base` correctly, regardless of what's checked out, and (optionally)
    push so Vercel deploys. Frees any leftover worktree first (the real bug)."""
    _free_branch(repo, branch)
    # clean fast-forward if the branch is strictly ahead of base (the common case)
    ahead = subprocess.run(["git", "merge-base", "--is-ancestor", base, branch],
                           cwd=repo, capture_output=True).returncode == 0
    if not ahead:
        # diverged -> rebase the (now-free) branch onto base; a real conflict returns CONFLICT
        if not _rebase_isolated(repo, base, branch):
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
    if os.environ.get("ORCH_CANONICAL_INTEGRATION", "true").lower() in ("true", "1", "yes"):
        import merge_train
        print("approval_merge: delegated to canonical merge_train")
        return merge_train.train_run()

    # Process both approved cards and pending code-merge cards. Legal/operator cards should not
    # reach this handler; material "Legal review needed" cards intentionally lack a merge slug.
    common = {"select": "*", "kind": "in.(verify,material,integrate)",
              "order": "created_at.asc", "limit": os.environ.get("MERGE_APPROVAL_SCAN_LIMIT", "2000")}
    approved_cards = db.select("approvals", {**common, "status": "eq.approved"}) or []
    pending_cards = db.select("approvals", {**common, "status": "eq.pending"}) or [] if (AUTOAPPROVE_ENABLED or AUTO_MERGE_APPROVALS) else []
    cards = approved_cards + pending_cards

    projects = {p["id"]: p for p in (db.select("projects") or [])}
    handled = 0
    auto_approved = 0
    seen_tasks = set()

    for c in cards:
        if c.get("kind") not in MERGE_KINDS:
            continue
        if not _is_code_merge_card(c):
            continue
        if str(c.get("decided_by") or "").startswith(MARK):
            continue  # already processed

        # OWNER POLICY: merges auto-approve (QA/build-gated) EXCEPT when the change moves the legal-
        # licensing / regulatory posture — those stay for the owner/counsel and are never auto-merged.
        try:
            import legal_filter
            if legal_filter.requires_owner_approval(c, kind=c.get("kind") or "",
                                                    radar_tag=c.get("radar_tag") or ""):
                continue
        except Exception:
            pass

        slug = _slug_from(c)
        if not slug:
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:no-slug"})
            continue

        tasks = db.select("tasks", {"select": "*", "slug": f"eq.{slug}"}) or []
        t = next((x for x in tasks if x["state"] == "BLOCKED"), tasks[0] if tasks else None)
        if not t:
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:no-task"})
            continue
        task_key = (t.get("project_id"), slug)
        if task_key in seen_tasks:
            update = {"decided_by": f"{MARK}:duplicate"}
            if c.get("status") == "pending":
                update["status"] = "approved"
            db.update("approvals", {"id": c["id"]}, update)
            handled += 1
            continue
        seen_tasks.add(task_key)

        proj = projects.get(t["project_id"], {})
        repo = proj.get("repo_path", "")
        task_base = t.get("base_branch") or proj.get("default_base", "main")
        base = _integration_base(repo, proj, task_base)
        branch = f"agent/{slug}"

        if not repo or not os.path.isdir(repo):
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:no-repo"})
            continue

        if not _branch_exists(repo, branch):
            patch = agentic_repair.repair_patch(
                t, f"approved, but {branch} no longer exists",
                category="missing-branch",
                directive=f"Reconstruct missing branch {branch} for this same task from artifacts/cache/templates or regenerate the minimal equivalent patch, run checks, and commit.")
            db.update("tasks", {"id": t["id"]}, patch)
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:branch-missing"})
            _notify(f"[merge] '{slug}' approved but branch {branch} is gone — re-queue to rebuild.")
            handled += 1
            continue
        # Auto-approve logic for pending code-merge cards.
        is_auto_candidate = False
        if c.get("status") == "pending":
            if AUTO_MERGE_APPROVALS or (_should_autoapprove(c, t) and not _touches_sensitive_paths(repo, branch, base)):
                db.update("approvals", {"id": c["id"]}, {"status": "approved", "decided_by": f"{MARK_AUTO}:approved"})
                is_auto_candidate = True
                auto_approved += 1
                _notify(f"[auto-approve] {slug}: code-merge card auto-approved")

        if c.get("status") != "approved" and not is_auto_candidate:
            continue
        # Two-key only applies when automatic code-merge approvals are explicitly disabled.
        if not AUTO_MERGE_APPROVALS and int(c.get("approvals_required") or 1) >= 2 and not c.get("second_approver"):
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
                patch = agentic_repair.repair_patch(
                    t, f"merge conflict integrating {branch} into {base}",
                    category="conflict",
                    directive=f"Resolve the merge conflict by rebuilding the same task on fresh {base}, run tests, and commit.")
                patch["transient_retries"] = tr + 1
                db.update("tasks", {"id": t["id"]}, patch)
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
        decided_marker = f"{MARK_AUTO}:{result}" if is_auto_candidate else f"{MARK}:{result}"
        db.update("tasks", {"id": t["id"]}, {"state": result,
                  "note": f"merge-handler: {result} (approved by {c.get('decided_by') or 'you'})"})
        db.update("approvals", {"id": c["id"]}, {"decided_by": decided_marker})
        _notify(f"[merge] {slug} -> {base}: {result}")
        handled += 1
    print(f"approval_merge: processed {handled} card(s) ({auto_approved} auto-approved)")
    return handled


if __name__ == "__main__":
    run()
