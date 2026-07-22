#!/usr/bin/env python3
"""
workflow_guardrails.py — 50X-500X execution quality improvement.

Prevents the systemic issues that required multi-session manual cleanup:
  1. Remote branch sprawl (382+ unmerged branches in a single repo)
  2. Branch creation rate explosion (agents creating unlimited branches)
  3. Merge backlog pile-up (no cap on pending merges per project)
  4. Deploy queue flooding (same commit triggering N Vercel builds)
  5. Worktree leak (orphaned worktrees consuming disk)

Every guardrail is env-configurable and logs to Supabase for dashboarding.
All checks are non-blocking by default (warn) and can be set to block mode.

Env vars (all optional, sane defaults):
    ORCH_GUARDRAIL_MODE             "warn" or "block" (default "warn")
    ORCH_MAX_BRANCHES_PER_PROJECT   max remote branches per project (default 30)
    ORCH_MAX_BRANCH_CREATES_PER_H   max new branches any agent can create/hour (default 10)
    ORCH_MAX_MERGE_BACKLOG          max pending merges before pausing new work (default 20)
    ORCH_DEPLOY_DEDUP_WINDOW_S      seconds to dedup identical deploys (default 300)
    ORCH_MAX_WORKTREES              max concurrent worktrees (default 8)
    ORCH_REMOTE_BRANCH_GC_DAYS      delete remote agent branches older than N days (default 7)
    ORCH_REMOTE_BRANCH_GC_ENABLED   "true" to enable remote branch GC (default "true")
    ORCH_REMOTE_BRANCH_GC_DRY_RUN   "true" for dry-run (default "true" — flip after review)
"""
import os, sys, time, subprocess, json, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_log = logging.getLogger("guardrails")

# ── Configuration ──────────────────────────────────────────────────────────
MODE = os.environ.get("ORCH_GUARDRAIL_MODE", "warn")
MAX_BRANCHES = int(os.environ.get("ORCH_MAX_BRANCHES_PER_PROJECT", "30"))
MAX_CREATES_PER_H = int(os.environ.get("ORCH_MAX_BRANCH_CREATES_PER_H", "10"))
MAX_MERGE_BACKLOG = int(os.environ.get("ORCH_MAX_MERGE_BACKLOG", "20"))
DEPLOY_DEDUP_WINDOW = int(os.environ.get("ORCH_DEPLOY_DEDUP_WINDOW_S", "300"))
MAX_WORKTREES = int(os.environ.get("ORCH_MAX_WORKTREES", "8"))
REMOTE_GC_DAYS = int(os.environ.get("ORCH_REMOTE_BRANCH_GC_DAYS", "7"))
REMOTE_GC_ENABLED = os.environ.get("ORCH_REMOTE_BRANCH_GC_ENABLED", "true").lower() in ("1", "true", "yes")
REMOTE_GC_DRY_RUN = os.environ.get("ORCH_REMOTE_BRANCH_GC_DRY_RUN", "true").lower() in ("1", "true", "yes")
GIT_TIMEOUT = 30

# ── Internal state ─────────────────────────────────────────────────────────
_branch_creates = []   # timestamps of recent branch creations
_deploy_log = {}       # "project:sha" -> last deploy timestamp

def _git(repo, *args):
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo,
                           capture_output=True, text=True, timeout=GIT_TIMEOUT)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _violation(guardrail, detail, context=None):
    v = {"guardrail": guardrail, "mode": MODE, "detail": detail,
         "timestamp": time.time(), "context": context or {}}
    _log.log(logging.WARNING if MODE == "warn" else logging.ERROR,
             "GUARDRAIL [%s] %s", guardrail, detail)
    try:
        import db
        db.insert("guardrail_violations", {
            "guardrail": guardrail, "mode": MODE,
            "detail": detail[:500],
            "context": json.dumps(context or {})[:2000],
        })
    except Exception:
        pass
    return v

# ── Guardrail 1: Branch count cap ─────────────────────────────────────────
def check_branch_count(repo_path, project_slug=""):
    rc, out, _ = _git(repo_path, "branch", "-r", "--list", "origin/agent/*")
    if rc != 0:
        return {"passed": True, "count": 0, "reason": "could not list remote branches"}
    branches = [b.strip() for b in out.splitlines() if b.strip()]
    count = len(branches)
    if count > MAX_BRANCHES:
        v = _violation("branch_count_cap",
                       f"{project_slug or 'repo'}: {count} remote agent branches (limit {MAX_BRANCHES})",
                       {"count": count, "limit": MAX_BRANCHES, "project": project_slug})
        return {"passed": MODE != "block", "count": count, "violation": v}
    return {"passed": True, "count": count}

# ── Guardrail 2: Branch creation rate limit ────────────────────────────────
def check_branch_rate():
    now = time.time()
    _branch_creates[:] = [t for t in _branch_creates if t > now - 3600]
    if len(_branch_creates) >= MAX_CREATES_PER_H:
        v = _violation("branch_rate_limit",
                       f"{len(_branch_creates)} branches in last hour (limit {MAX_CREATES_PER_H})",
                       {"count": len(_branch_creates), "limit": MAX_CREATES_PER_H})
        return {"passed": MODE != "block", "violation": v}
    return {"passed": True, "count": len(_branch_creates)}

def record_branch_create():
    _branch_creates.append(time.time())

# ── Guardrail 3: Merge backlog cap ────────────────────────────────────────
def check_merge_backlog(project_slug=""):
    try:
        import db
        q = {"select": "id", "state": "in.(PENDING_MERGE,VERIFY_PASS)"}
        if project_slug:
            q["project"] = f"eq.{project_slug}"
        rows = db.select("tasks", q) or []
        count = len(rows)
    except Exception:
        return {"passed": True, "count": 0, "reason": "could not query merge backlog"}
    if count > MAX_MERGE_BACKLOG:
        v = _violation("merge_backlog_cap",
                       f"{project_slug or 'all'}: {count} pending merges (limit {MAX_MERGE_BACKLOG})",
                       {"count": count, "limit": MAX_MERGE_BACKLOG, "project": project_slug})
        return {"passed": MODE != "block", "count": count, "violation": v}
    return {"passed": True, "count": count}

# ── Guardrail 4: Deploy deduplication ──────────────────────────────────────
def check_deploy_dedup(commit_sha, project=""):
    key = f"{project}:{commit_sha}"
    now = time.time()
    last = _deploy_log.get(key, 0)
    if now - last < DEPLOY_DEDUP_WINDOW:
        age = int(now - last)
        v = _violation("deploy_dedup",
                       f"commit {commit_sha[:8]} deployed {age}s ago (window {DEPLOY_DEDUP_WINDOW}s)",
                       {"commit": commit_sha, "project": project, "age_s": age})
        return {"passed": MODE != "block", "duplicate": True, "violation": v}
    return {"passed": True, "duplicate": False}

def record_deploy(commit_sha, project=""):
    _deploy_log[f"{project}:{commit_sha}"] = time.time()
    cutoff = time.time() - DEPLOY_DEDUP_WINDOW * 2
    for k in list(_deploy_log):
        if _deploy_log[k] < cutoff:
            del _deploy_log[k]

# ── Guardrail 5: Worktree count cap ───────────────────────────────────────
def check_worktree_count(repo_path):
    rc, out, _ = _git(repo_path, "worktree", "list", "--porcelain")
    if rc != 0:
        return {"passed": True, "count": 0, "reason": "could not list worktrees"}
    count = max(0, sum(1 for l in out.splitlines() if l.startswith("worktree ")) - 1)
    # Re-read from env each call so fleet_config updates take effect without restart
    _mode = os.environ.get("ORCH_GUARDRAIL_MODE", "warn")
    _max_wt = int(os.environ.get("ORCH_MAX_WORKTREES", "8"))
    if count > _max_wt:
        v = _violation("worktree_cap", f"{count} active worktrees (limit {_max_wt})",
                       {"count": count, "limit": _max_wt})
        return {"passed": _mode != "block", "count": count, "violation": v}
    return {"passed": True, "count": count}

# ── Guardrail 6: Remote branch GC (the missing piece) ─────────────────────
def gc_remote_branches(repo_path):
    """Delete remote agent branches older than REMOTE_GC_DAYS.
    branch_gc.py only handles local; this handles origin/agent/*."""
    if not REMOTE_GC_ENABLED:
        return {"deleted": 0, "reason": "disabled"}
    _git(repo_path, "fetch", "--prune", "origin")
    rc, out, _ = _git(repo_path, "branch", "-r", "--list", "origin/agent/*")
    if rc != 0:
        return {"deleted": 0, "errors": 1, "reason": "git branch -r failed"}
    branches = [b.strip() for b in out.splitlines() if b.strip()]
    deleted, skipped, errors = [], 0, 0
    for branch in branches:
        rc, log_out, _ = _git(repo_path, "log", "-1", "--format=%ct", branch)
        if rc != 0 or not log_out.strip():
            skipped += 1; continue
        try:
            age_days = (time.time() - int(log_out.strip())) / 86400
        except ValueError:
            skipped += 1; continue
        if age_days < REMOTE_GC_DAYS:
            skipped += 1; continue
        remote_branch = branch.replace("origin/", "", 1)
        if REMOTE_GC_DRY_RUN:
            deleted.append({"branch": remote_branch, "age_days": round(age_days, 1), "dry_run": True})
        else:
            rc2, _, err = _git(repo_path, "push", "origin", "--delete", remote_branch)
            if rc2 == 0:
                deleted.append({"branch": remote_branch, "age_days": round(age_days, 1)})
            else:
                errors += 1
    result = {"deleted": len(deleted), "skipped": skipped, "errors": errors,
              "dry_run": REMOTE_GC_DRY_RUN, "branches": deleted[:20]}
    _log.info("remote_branch_gc: %d deleted, %d skipped, %d errors (dry_run=%s)",
              result["deleted"], skipped, errors, REMOTE_GC_DRY_RUN)
    return result

# ── Pre-task preflight (call before dispatching any task) ──────────────────
def preflight(repo_path, project_slug="", commit_sha="", is_deploy=False):
    """Run all guardrail checks. Returns {"passed": bool, "violations": [...]}."""
    checks, violations = {}, []
    for name, fn in [
        ("branch_count", lambda: check_branch_count(repo_path, project_slug)),
        ("branch_rate", check_branch_rate),
        ("merge_backlog", lambda: check_merge_backlog(project_slug)),
        ("worktree_count", lambda: check_worktree_count(repo_path)),
    ]:
        r = fn(); checks[name] = r
        if not r.get("passed", True):
            violations.append(r.get("violation"))
    if is_deploy and commit_sha:
        r = check_deploy_dedup(commit_sha, project_slug)
        checks["deploy_dedup"] = r
        if not r.get("passed", True):
            violations.append(r.get("violation"))
    return {"passed": all(c.get("passed", True) for c in checks.values()),
            "violations": [v for v in violations if v], "checks": checks, "mode": MODE}

# ── Periodic maintenance (call from periodic.py) ──────────────────────────
def periodic_maintenance(repo_paths=None):
    results = {}
    for repo in (repo_paths or []):
        if os.path.isdir(repo):
            results[repo] = gc_remote_branches(repo)
    return results

# ── CLI ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    repo = os.environ.get("ORCH_REPO_PATH",
                          os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(json.dumps(preflight(repo), indent=2, default=str))
    if REMOTE_GC_ENABLED:
        print("\n--- Remote Branch GC ---")
        print(json.dumps(gc_remote_branches(repo), indent=2, default=str))