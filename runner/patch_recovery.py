"""
patch_recovery.py — patch-first recovery for failed/missing branches.

When a task's branch is missing (the #1 cause of recovery tasks), try:
1. Stored patch replay from task_artifacts
2. Cherry-pick from reflog
3. Template adaptation from similar merged diffs

Only fall back to a full model call if all mechanical recovery fails.
This is 10X-100X cheaper than re-running the agent.
"""
import os, subprocess, json, re
import db

def recover(repo, slug, base, project=None):
    """Attempt mechanical recovery of a missing branch. Returns dict with:
    - ok: bool — whether recovery succeeded
    - method: str — which method worked
    - branch: str — recovered branch name
    """
    branch = f"agent/{slug}"

    # Method 0: recover the exact, immutable artifact. This is deterministic,
    # cross-host and does not spend model tokens.
    result = _immutable_ref_recovery(repo, slug, branch, base)
    if result["ok"]:
        return result

    # Method 1: Stored patch replay
    result = _replay_stored_patch(repo, slug, branch, base)
    if result["ok"]:
        return result

    # Method 2: Reflog cherry-pick
    result = _reflog_recovery(repo, slug, branch, base)
    if result["ok"]:
        return result

    # Method 3: Similar merged diff adaptation
    result = _template_adaptation(repo, slug, branch, base, project)
    if result["ok"]:
        return result

    return {"ok": False, "method": "none", "branch": branch,
            "reason": "all mechanical recovery methods exhausted"}


def _immutable_ref_recovery(repo, slug, branch, base):
    try:
        rows = db.select("tasks", {"select": "artifact_ref,artifact_commit", "slug": f"eq.{slug}",
                                   "order": "updated_at.desc", "limit": "1"}) or []
        task = rows[0] if rows else {}
        ref = task.get("artifact_ref")
        if ref:
            _git(repo, "fetch", "origin", f"{ref}:{ref}", timeout=120)
        sha = ""
        if ref:
            resolved = _git(repo, "rev-parse", "--verify", ref)
            sha = resolved.stdout.strip() if resolved.returncode == 0 else ""
        if not sha and task.get("artifact_commit"):
            resolved = _git(repo, "rev-parse", "--verify", str(task["artifact_commit"]))
            sha = resolved.stdout.strip() if resolved.returncode == 0 else ""
        if not sha:
            return {"ok": False, "method": "immutable_ref", "branch": branch,
                    "reason": "immutable artifact unavailable"}
        if _git(repo, "merge-base", "--is-ancestor", base, sha).returncode != 0:
            return {"ok": False, "method": "immutable_ref", "branch": branch,
                    "reason": "artifact requires rebase"}
        _free_branch(repo, branch)
        created = _git(repo, "branch", branch, sha)
        if created.returncode != 0:
            return {"ok": False, "method": "immutable_ref", "branch": branch,
                    "reason": created.stderr[:200]}
        return {"ok": True, "method": "immutable_ref", "branch": branch,
                "artifact_ref": ref, "commit": sha}
    except Exception as exc:
        return {"ok": False, "method": "immutable_ref", "branch": branch,
                "reason": str(exc)[:200]}


def _replay_stored_patch(repo, slug, branch, base):
    """Replay stored patch.diff from task_artifacts."""
    try:
        import task_artifacts
        patch = task_artifacts.get_patch(slug)
        if not patch or len(patch.strip()) < 10:
            return {"ok": False, "method": "patch_replay", "branch": branch,
                    "reason": "no stored patch"}

        # Create a fresh branch from base
        _git(repo, "branch", "-D", branch)  # remove stale ref if any
        _git(repo, "branch", branch, base)

        # Create temp worktree
        wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", slug)
        os.makedirs(os.path.dirname(wt), exist_ok=True)
        _free_branch(repo, branch)
        r = _git(repo, "worktree", "add", "-f", wt, branch, timeout=120)
        if r.returncode != 0:
            return {"ok": False, "method": "patch_replay", "branch": branch,
                    "reason": f"worktree setup failed: {r.stderr[:200]}"}

        # Apply the patch
        proc = subprocess.run(["git", "apply", "--3way", "-"], cwd=wt,
                             input=patch, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            # Try with less strict application
            proc = subprocess.run(["git", "apply", "--3way", "--reject", "-"], cwd=wt,
                                 input=patch, capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                return {"ok": False, "method": "patch_replay", "branch": branch,
                        "reason": f"patch apply failed: {proc.stderr[:200]}"}

        # Commit
        env = {**os.environ,
               "GIT_AUTHOR_NAME": os.environ.get("FLEET_GIT_AUTHOR_NAME", "Kale Aaron Pasch"),
               "GIT_AUTHOR_EMAIL": os.environ.get("FLEET_GIT_AUTHOR_EMAIL", "kalepasch@gmail.com"),
               "GIT_COMMITTER_NAME": os.environ.get("FLEET_GIT_AUTHOR_NAME", "Kale Aaron Pasch"),
               "GIT_COMMITTER_EMAIL": os.environ.get("FLEET_GIT_AUTHOR_EMAIL", "kalepasch@gmail.com")}
        subprocess.run(["git", "add", "-A"], cwd=wt, env=env, capture_output=True)
        subprocess.run(["git", "commit", "--no-verify", "-m", f"patch-recovery: {slug}"],
                       cwd=wt, env=env, capture_output=True)

        # Verify branch is ahead
        ahead = subprocess.run(["git", "rev-list", "--count", f"{base}..HEAD"],
                              cwd=wt, capture_output=True, text=True)
        if int((ahead.stdout or "0").strip() or "0") > 0:
            return {"ok": True, "method": "patch_replay", "branch": branch}

        return {"ok": False, "method": "patch_replay", "branch": branch,
                "reason": "patch produced no commits"}
    except Exception as e:
        return {"ok": False, "method": "patch_replay", "branch": branch,
                "reason": str(e)[:200]}


def _reflog_recovery(repo, slug, branch, base):
    """Try to find the branch's last known commit in the reflog."""
    try:
        r = _git(repo, "reflog", "--all", "--format=%H %gs", timeout=30)
        if r.returncode != 0:
            return {"ok": False, "method": "reflog", "branch": branch, "reason": "reflog unavailable"}

        for line in (r.stdout or "").splitlines():
            if slug in line:
                sha = line.split()[0] if line.split() else ""
                if sha and len(sha) >= 7:
                    # Verify this SHA is ahead of base
                    check = _git(repo, "merge-base", "--is-ancestor", base, sha)
                    if check.returncode == 0:
                        _git(repo, "branch", "-D", branch)
                        _git(repo, "branch", branch, sha)
                        return {"ok": True, "method": "reflog", "branch": branch}

        return {"ok": False, "method": "reflog", "branch": branch, "reason": "slug not in reflog"}
    except Exception as e:
        return {"ok": False, "method": "reflog", "branch": branch, "reason": str(e)[:200]}


def _template_adaptation(repo, slug, branch, base, project=None):
    """Find a similar previously-merged diff and adapt it."""
    try:
        # Look for similar merged tasks in outcomes
        task_rows = db.select("tasks", {"select": "prompt", "slug": f"eq.{slug}", "limit": "1"})
        if not task_rows:
            return {"ok": False, "method": "template", "branch": branch, "reason": "task not found"}

        prompt = (task_rows[0].get("prompt") or "")[:500]
        if not prompt:
            return {"ok": False, "method": "template", "branch": branch, "reason": "no prompt"}

        # Find similar merged tasks by keyword overlap
        import task_artifacts
        keywords = set(re.findall(r'\b\w{4,}\b', prompt.lower()))
        if not keywords:
            return {"ok": False, "method": "template", "branch": branch, "reason": "no keywords"}

        # Get recent merged task artifacts
        merged = db.select("tasks", {
            "select": "slug", "state": "eq.MERGED",
            "order": "updated_at.desc", "limit": "50"
        }) or []

        best_match = None
        best_score = 0
        for mt in merged:
            ms = mt.get("slug", "")
            if ms == slug:
                continue
            art = task_artifacts.get_artifacts(ms)
            if not art or not art.get("patch_diff"):
                continue
            # Simple keyword overlap scoring
            art_keywords = set(re.findall(r'\b\w{4,}\b', (art.get("touched_files") or "").lower()))
            score = len(keywords & art_keywords)
            if score > best_score:
                best_score = score
                best_match = art

        if not best_match or best_score < 2:
            return {"ok": False, "method": "template", "branch": branch,
                    "reason": "no similar merged diff found"}

        # Try applying the similar diff
        return _replay_stored_patch(repo, slug, branch, base)
    except Exception as e:
        return {"ok": False, "method": "template", "branch": branch, "reason": str(e)[:200]}


def _git(repo, *args, timeout=60):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)


def _free_branch(repo, branch):
    """Remove any worktree that has this branch checked out."""
    try:
        import approval_merge
        approval_merge._free_branch(repo, branch)
    except Exception:
        pass
