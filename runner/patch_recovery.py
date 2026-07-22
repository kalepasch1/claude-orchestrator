"""
patch_recovery.py — patch-first recovery for failed/missing branches.

When a task's branch is missing (the #1 cause of recovery tasks), try:
1. Stored patch replay from task_artifacts
2. Cherry-pick from reflog
3. Template adaptation from similar merged diffs

Only fall back to a full model call if all mechanical recovery fails.
This is 10X-100X cheaper than re-running the agent.

Branch-detection and regeneration utilities (zero-spend, standalone):
- detect_branch(repo, slug)        — check local branches and worktrees
- query_cache_hints(slug, ...)     — query merged-diff library and artifact cache
- regenerate_from_intent(repo, ...) — infer/regenerate minimal patch from intent
"""
import os, subprocess, json, re
import db


def _git_commit_env():
    """Return a minimal env dict for git commit operations.

    Reads fleet-wide identity vars (non-sensitive: name/email for commits only).
    Does not spread os.environ — only passes what git needs to commit.
    """
    _name = os.environ.get("FLEET_GIT_AUTHOR_NAME", "Claude Agent")
    _email = os.environ.get("FLEET_GIT_AUTHOR_EMAIL", "agent@recovery.local")
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "GIT_AUTHOR_NAME": _name,
        "GIT_AUTHOR_EMAIL": _email,
        "GIT_COMMITTER_NAME": _name,
        "GIT_COMMITTER_EMAIL": _email,
    }

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
        env = _git_commit_env()
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

        # Apply the found similar diff directly (not the missing original slug's patch).
        patch = best_match.get("patch_diff", "")
        if not patch or len(patch.strip()) < 10:
            return {"ok": False, "method": "template", "branch": branch,
                    "reason": "similar diff found but patch_diff is empty"}
        return _apply_patch_to_branch(repo, patch, branch, base)
    except Exception as e:
        return {"ok": False, "method": "template", "branch": branch, "reason": str(e)[:200]}


# ---------------------------------------------------------------------------
# Standalone branch-detection and regeneration utilities (zero-agent-spend)
# These are NOT yet wired into recover() — they are isolated utilities.
# ---------------------------------------------------------------------------

def detect_branch(repo, slug):
    """Zero-spend detection: check local branches and worktrees for agent/<slug>.

    Returns dict with:
    - found: bool
    - location: 'local' | 'worktree' | None
    - branch: str
    - path: str | None  (worktree path when location=='worktree')
    """
    branch = f"agent/{slug}"

    # 1. Local branches — cheapest check
    r = _git(repo, "branch", "--list", branch)
    if r.returncode == 0 and branch in (r.stdout or ""):
        return {"found": True, "location": "local", "branch": branch, "path": None}

    # 2. Worktrees — branch may be checked out without existing as a local ref
    r = _git(repo, "worktree", "list", "--porcelain")
    if r.returncode == 0:
        cur_path = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("worktree "):
                cur_path = line[len("worktree "):].strip()
            elif line.strip() == f"branch refs/heads/{branch}":
                return {"found": True, "location": "worktree", "branch": branch, "path": cur_path}

    return {"found": False, "location": None, "branch": branch, "path": None}


def query_cache_hints(slug, intent_words=None, project=None):
    """Query merged-diff library and artifact cache for historical references.

    Checks (in priority order):
    1. task_artifacts for this exact slug (similarity 1.0)
    2. merged_diff_library for similar tasks by intent overlap
    3. knowledge table for patch-template entries by keyword match

    Returns list of hint dicts sorted by similarity descending:
    - source: 'task_artifacts' | 'merged_diff' | 'knowledge'
    - slug: str
    - similarity: float 0..1
    - patch_diff: str | None  (None when source is 'knowledge')
    - summary: str
    """
    hints = []
    words = list(intent_words or [])

    # 1. Exact slug hit in task_artifacts
    try:
        import task_artifacts
        art = task_artifacts.get_artifacts(slug)
        if art and len((art.get("patch_diff") or "").strip()) > 10:
            hints.append({
                "source": "task_artifacts",
                "slug": slug,
                "similarity": 1.0,
                "patch_diff": art["patch_diff"],
                "summary": f"stored artifact for {slug}",
            })
    except Exception:
        pass

    # 2. Merged-diff library: similar tasks by intent overlap
    if words:
        try:
            import merged_diff_library
            task = {"slug": slug, "prompt": " ".join(words), "project_id": project}
            for h in merged_diff_library.find(task, limit=3):
                hints.append({
                    "source": "merged_diff",
                    "slug": h.get("slug", ""),
                    "similarity": float(h.get("similarity", 0)),
                    "patch_diff": h.get("diff") or None,
                    "summary": h.get("summary", ""),
                })
        except Exception:
            pass

    # 3. Knowledge table: patch-template entries by keyword overlap
    try:
        rows = db.select("knowledge", {
            "select": "title,body,keywords",
            "tags": "cs.{patch-template}",
            "limit": "20",
        }) or []
        iw = set(words)
        for row in rows:
            kw = set(row.get("keywords") or [])
            if not kw or not iw:
                continue
            score = len(kw & iw) / max(len(kw | iw), 1)
            if score > 0:
                hints.append({
                    "source": "knowledge",
                    "slug": (row.get("title") or "").replace(" ", "-"),
                    "similarity": round(score, 3),
                    "patch_diff": None,
                    "summary": (row.get("body") or "")[:500],
                })
    except Exception:
        pass

    return sorted(hints, key=lambda h: h["similarity"], reverse=True)


def regenerate_from_intent(repo, slug, base, intent_words, template_id=None):
    """Last-resort regeneration: infer a minimal branch from the acceptance intent.

    Strategy (zero-agent-spend):
    1. If query_cache_hints() returns a replayable patch_diff, apply it.
    2. Otherwise create a minimal stub branch with a .recovery-intent file so
       the runner knows model spend is still needed, but the branch exists.

    Returns dict with:
    - ok: bool
    - method: 'cache_replay' | 'intent_stub' | 'failed'
    - branch: str
    - reason: str | None
    """
    branch = f"agent/{slug}"

    for hint in query_cache_hints(slug, intent_words):
        diff = hint.get("patch_diff") or ""
        if len(diff.strip()) < 10:
            continue
        result = _apply_diff_to_branch(repo, slug, branch, base, diff, hint["source"])
        if result["ok"]:
            return result

    return _create_intent_stub(repo, slug, branch, base, intent_words, template_id)


def _apply_diff_to_branch(repo, slug, branch, base, diff, source):
    """Apply a known diff to a fresh branch off base. Returns recover-style dict."""
    wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", f"regen-{slug}")
    try:
        wt_parent = os.path.dirname(wt)
        if wt_parent:
            os.makedirs(wt_parent, exist_ok=True)
        _git(repo, "branch", "-D", branch)
        _git(repo, "branch", branch, base)
        _free_branch(repo, branch)
        r = _git(repo, "worktree", "add", "-f", wt, branch, timeout=120)
        if r.returncode != 0:
            return {"ok": False, "method": "cache_replay", "branch": branch,
                    "reason": f"worktree setup failed: {r.stderr[:200]}"}

        proc = subprocess.run(["git", "apply", "--3way", "-"], cwd=wt,
                              input=diff, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return {"ok": False, "method": "cache_replay", "branch": branch,
                    "reason": f"diff apply failed: {proc.stderr[:200]}"}

        env = _git_commit_env()
        subprocess.run(["git", "add", "-A"], cwd=wt, env=env, capture_output=True)
        r2 = subprocess.run(["git", "commit", "--no-verify", "-m",
                            f"regen-from-cache({source}): {slug}"],
                           cwd=wt, env=env, capture_output=True, text=True)
        if r2.returncode != 0:
            return {"ok": False, "method": "cache_replay", "branch": branch,
                    "reason": f"commit failed: {r2.stderr[:200]}"}

        ahead = subprocess.run(["git", "rev-list", "--count", f"{base}..HEAD"],
                               cwd=wt, capture_output=True, text=True)
        if int((ahead.stdout or "0").strip() or "0") > 0:
            return {"ok": True, "method": "cache_replay", "branch": branch}
        return {"ok": False, "method": "cache_replay", "branch": branch,
                "reason": "diff produced no commits"}
    except Exception as e:
        return {"ok": False, "method": "cache_replay", "branch": branch, "reason": str(e)[:200]}
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", wt],
                      cwd=repo, capture_output=True)


def _create_intent_stub(repo, slug, branch, base, intent_words, template_id=None):
    """Create a minimal stub branch with recovery metadata. Last resort."""
    wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", f"stub-{slug}")
    try:
        wt_parent = os.path.dirname(wt)
        if wt_parent:
            os.makedirs(wt_parent, exist_ok=True)
        _free_branch(repo, branch)
        _git(repo, "branch", "-D", branch)
        _git(repo, "branch", branch, base)
        r = _git(repo, "worktree", "add", "-f", wt, branch, timeout=120)
        if r.returncode != 0:
            return {"ok": False, "method": "failed", "branch": branch,
                    "reason": f"worktree setup failed: {r.stderr[:200]}"}

        intent_text = " ".join(intent_words or [slug])
        stub_path = os.path.join(wt, f".recovery-intent-{slug}.txt")
        with open(stub_path, "w") as f:
            f.write(f"recovery-intent: {slug}\n")
            if template_id:
                f.write(f"template: {template_id}\n")
            f.write(f"intent: {intent_text}\n")
            f.write(f"base: {base}\n")

        env = _git_commit_env()
        subprocess.run(["git", "add", stub_path], cwd=wt, env=env, capture_output=True)
        r2 = subprocess.run(["git", "commit", "--no-verify", "-m",
                            f"recovery-intent-stub: {slug}\n\nintent: {intent_text}"],
                           cwd=wt, env=env, capture_output=True, text=True)
        if r2.returncode != 0:
            return {"ok": False, "method": "failed", "branch": branch,
                    "reason": f"stub commit failed: {r2.stderr[:200]}"}
        return {"ok": True, "method": "intent_stub", "branch": branch}
    except Exception as e:
        return {"ok": False, "method": "failed", "branch": branch, "reason": str(e)[:200]}
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", wt],
                      cwd=repo, capture_output=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _git(repo, *args, timeout=60):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
    }
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, timeout=timeout)


def _free_branch(repo, branch):
    """Remove any worktree that has this branch checked out."""
    try:
        import approval_merge
        approval_merge._free_branch(repo, branch)
    except Exception:
        pass
