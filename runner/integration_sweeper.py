#!/usr/bin/env python3
"""Find tested-but-unintegrated work and feed it into the canonical merge train.

If passed work lost its agent branch, queue a tiny recovery task instead of
spending a full fresh draft immediately. Recovery prompts are reuse-first:
result cache, patch transplant, and patch templates are injected before any
agentic coder sees the task.
"""
import datetime
import json
import os
import sys
import subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import merge_train

try:
    import branch_prediction_predictor as _bp_predictor
    _ML_AVAILABLE = True
except Exception:
    _ML_AVAILABLE = False

LIMIT = int(os.environ.get("INTEGRATION_SWEEPER_LIMIT", "80"))
RUN_TRAIN = os.environ.get("INTEGRATION_SWEEPER_RUN_TRAIN", "true").lower() in ("true", "1", "yes")
RECOVERY_PREFIX = "recover-missing-branch-"
PRESSURE_KEY = "merge_train_pressure"
ACTIVE_STATES = "in.(QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED,QUARANTINED)"

def _existing_recovery(project_id, slug):
    # Placeholder implementation for _existing_recovery function
    pass

def _normalize_base(repo, proj, base_branch):
    # Placeholder implementation for _normalize_base function
    return base_branch

def _reuse_context(task, proj, repo, base):
    # Placeholder implementation for _reuse_context function
    return ""

def _branch_exists(repo, branch):
    if not repo or not os.path.isdir(repo):
        return False
    return subprocess.run(["git", "rev-parse", "--verify", branch],
                          cwd=repo, capture_output=True).returncode == 0

def _branch_exists_anywhere(repo, branch):
    # Placeholder implementation for _branch_exists_anywhere function
    return False

# Added function to handle missing agent branches
def _handle_missing_branch(task, proj):
    slug = task.get("slug")
    if not slug or _existing_recovery(task.get("project_id"), slug):
        return False
    repo = proj.get("repo_path", "")
    base = _normalize_base(repo, proj, task.get("base_branch") or proj.get("default_base") or proj.get("prod_branch") or "main")
    reuse = _reuse_context(task, proj, repo, base)
    recovery_slug = f"{RECOVERY_PREFIX}{slug}"
    prompt = (
        "Recover tested-but-not-integrated work whose agent branch is missing.\n"
        f"Goal: recreate the smallest equivalent patch, commit it on agent/{recovery_slug}, "
        "run the project build/tests, and let the canonical merge train integrate it.\n"
        "Do not add new scope. Prefer cache/transplant/template context below before drafting.\n\n"
        f"Original slug: {slug}\n"
        f"Original task note: {(task.get('note') or '')[:1200]}\n\n"
        f"{reuse}\n\n"
        "Original prompt:\n"
        f"{task.get('prompt') or ''}"
    )
    # Coder choice: material/complex work must NOT be force-pinned to local ollama — that is exactly
    # why 160+ recoveries quarantined (ollama can't rebuild things like implement-platform). Only
    # keep a cheap local coder when the original explicitly used one; otherwise let the router pick a
    # capable coder (force_coder=None). Material work never gets forced onto ollama.
    orig = task.get("force_coder")
    if task.get("material"):
        force = None if (not orig or orig == "ollama") else orig
    else:
        force = orig or "ollama"
    row = {"project_id": task.get("project_id"), "slug": recovery_slug, "prompt": prompt,
           "base_branch": base, "kind": task.get("kind") or "bugfix", "state": "QUEUED",
           "deps": [], "material": bool(task.get("material")),
           "force_coder": force,
           "model": force,
           "note": f"integration_sweeper: rebuild missing branch for {slug} using reuse-first context"}
    try:
        db.insert("tasks", row, upsert=True)
        db.update("tasks", {"id": task["id"]},
                  {"note": f"integration_sweeper: missing branch; queued recovery {recovery_slug}"})
        return True
    except Exception:
        return False

# Modified _queue_recovery function to use the new _handle_missing_branch function
def _queue_recovery(task, proj):
    if not _branch_exists_anywhere(proj.get("repo_path", ""), f"agent/{task.get('slug')}"):
        return _handle_missing_branch(task, proj)
    return False

def _age_seconds(ts):
    if not ts:
        return 0
    raw = str(ts).replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(raw)
        if dt.tzinfo:
            now = datetime.datetime.now(datetime.timezone.utc)
        else:
            now = datetime.datetime.utcnow()
        return max(0, int((now - dt).total_seconds()))
    except Exception:
        return 0


def pressure(limit=1000):
    projects = {p["id"]: p for p in (db.select("projects") or [])}
    rows = db.select("tasks", {"select": "id,slug,project_id,state,note,updated_at",
                               "state": "in.(DONE,BLOCKED,RUNNING)",
                               "order": "updated_at.asc",
                               "limit": str(limit)}) or []
    out = {}
    for t in rows:
        if not _looks_passed(t):
            continue
        proj = projects.get(t.get("project_id")) or {}
        name = proj.get("name") or str(t.get("project_id"))
        repo = proj.get("repo_path", "")
        branch = f"agent/{t.get('slug')}"
        bucket = out.setdefault(name, {"passed_waiting": 0, "missing_branch": 0,
                                       "oldest_wait_age_s": 0})
        if _branch_exists_anywhere(repo, branch):
            bucket["passed_waiting"] += 1
            bucket["oldest_wait_age_s"] = max(bucket["oldest_wait_age_s"], _age_seconds(t.get("updated_at")))
        else:
            bucket["missing_branch"] += 1
    payload = {"generated_at": datetime.datetime.utcnow().isoformat(), "projects": out}
    try:
        db.insert("controls", {"key": PRESSURE_KEY, "value": json.dumps(payload),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".runtime", "merge_train_pressure.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(payload, f, indent=2)
        except OSError:
            pass
    return payload


def sweep(limit=LIMIT, run_train=RUN_TRAIN):
    dedup = recovery_dedup()
    projects = {p["id"]: p for p in (db.select("projects") or [])}
    rows = db.select("tasks", {"select": "id,slug,project_id,state,note,kind,prompt,base_branch,material,force_coder,model,updated_at",
                               "state": "in.(DONE,BLOCKED,RUNNING)",
                               "order": "updated_at.asc",
                               "limit": str(limit)}) or []
    recovery_index = _active_recovery_index()
    queued = missing = skipped = recovery = 0
    for t in rows:
        if t.get("state") == "RUNNING" and "verify pass" not in (t.get("note") or "").lower():
            skipped += 1
            continue
        if not _looks_passed(t):
            skipped += 1
            continue
        slug = t.get("slug")
        # NESTING GUARD: never file recovery for anything that already IS recovery work,
        # including rework-* wrappers around recovery slugs — recovery-of-recovery churn
        # ("rework-missing-branch-recover-missing-branch-...") burned lanes for days.
        if RECOVERY_PREFIX in str(slug or ""):
            skipped += 1
            continue
        proj = projects.get(t.get("project_id")) or {}
        repo = proj.get("repo_path", "")
        if not _branch_exists_anywhere(repo, f"agent/{slug}"):
            # Branch gone. If the work already landed upstream, CLOSE it (no rebuild) — this is what
            # kills the phantom missing_branch recount + endless recovery churn on merged work.
            if _already_integrated(repo, slug):
                if t.get("state") != "MERGED":
                    db.update("tasks", {"id": t["id"]},
                              {"state": "MERGED",
                               "note": "integration_sweeper: work already in integration branch; closed (branch GC'd)"})
                continue
            if _queue_recovery(t, proj, recovery_index=recovery_index):
                missing += 1
                recovery += 1
            elif _has_live_recovery(t.get("project_id"), slug):
                missing += 1  # rebuild still in flight — leave the original open
            else:
                # branch gone, not integrated, and recovery is exhausted (quarantined/dead): stop
                # re-counting + re-sweeping this forever. Close it so pressure reflects reality.
                db.update("tasks", {"id": t["id"]},
                          {"state": "QUARANTINED",
                           "note": "integration_sweeper: branch lost and recovery exhausted; closed to stop phantom missing_branch churn"})
            continue
        created = merge_train.ensure_integration_card(
            proj.get("name") or str(t.get("project_id")),
            slug,
            kind="integrate",
            title=f"merge of {slug}",
            why="integration sweeper found passed work with an agent branch",
            detail=(t.get("note") or "")[-2000:],
            status="approved",
            decided_by="canonical-train:sweeper",
        )
        if created:
            queued += 1
        if t.get("state") != "DONE":
            db.update("tasks", {"id": t["id"]},
                      {"state": "DONE", "note": "integration_sweeper: queued for canonical merge train"})
    train = merge_train.train_run() if run_train and queued else {}
    press = pressure(limit=max(limit, 200))
    out = {"queued": queued, "missing_branch": missing, "recovery_queued": recovery,
           "recovery_dedup": dedup,
           "skipped": skipped, "pressure": press, "train": train}
    print(f"integration_sweeper: queued={queued} missing_branch={missing} "
          f"recovery_queued={recovery} skipped={skipped} train={train}")
    return out


def local_branch_audit(repo, slugs=None, limit=200):
    """Read-only audit of local agent/* branch state vs pending task slugs.

    For each slug, classifies the branch as: local, remote_only, or missing.
    Also lists stale worktrees (agent/* branches checked out but task not running).
    Does not write to git or the DB. Fail-soft on unavailable repo or DB.

    Returns:
        {
          "local": [{"slug": ..., "branch": ...}, ...],
          "remote_only": [{"slug": ..., "branch": ...}, ...],
          "missing": [{"slug": ..., "branch": ...}, ...],
          "stale_worktrees": [{"branch": ..., "worktree": ...}, ...],
          "reflog_hints": [{"slug": ..., "sha": ...}, ...],
        }
    """
    local_set = set()
    remote_set = set()
    wt_map = {}

    if repo and os.path.isdir(repo):
        _fetch_agent_refs(repo)
        try:
            r = subprocess.run(
                ["git", "branch", "--list", "agent/*", "--format=%(refname:short)"],
                cwd=repo, capture_output=True, text=True, timeout=30,
            )
            local_set = {line.strip() for line in r.stdout.splitlines() if line.strip()}
        except Exception:
            pass
        try:
            r = subprocess.run(
                ["git", "branch", "-r", "--list", "origin/agent/*", "--format=%(refname:short)"],
                cwd=repo, capture_output=True, text=True, timeout=30,
            )
            for line in r.stdout.splitlines():
                b = line.strip()
                if b.startswith("origin/"):
                    remote_set.add(b[len("origin/"):])
        except Exception:
            pass
        try:
            r = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=repo, capture_output=True, text=True, timeout=30,
            )
            wt_path = None
            for line in r.stdout.splitlines():
                if line.startswith("worktree "):
                    wt_path = line[len("worktree "):].strip()
                elif line.startswith("branch refs/heads/"):
                    b = line[len("branch refs/heads/"):].strip()
                    if b.startswith("agent/"):
                        wt_map[b] = wt_path
                elif not line.strip():
                    wt_path = None
        except Exception:
            pass

    if slugs is None:
        try:
            rows = db.select("tasks", {
                "select": "slug",
                "state": "in.(QUEUED,RUNNING,DONE,BLOCKED)",
                "order": "updated_at.desc",
                "limit": str(limit),
            }) or []
            slugs = [row["slug"] for row in rows if row.get("slug")]
        except Exception:
            slugs = []

    local_out, remote_only_out, missing_out = [], [], []
    for slug in slugs:
        branch = f"agent/{slug}"
        if branch in local_set:
            local_out.append({"slug": slug, "branch": branch})
        elif branch in remote_set:
            remote_only_out.append({"slug": slug, "branch": branch})
        else:
            missing_out.append({"slug": slug, "branch": branch})

    running_slugs = set()
    try:
        rows = db.select("tasks", {
            "select": "slug",
            "state": "in.(RUNNING,RETRY)",
        }) or []
        running_slugs = {r["slug"] for r in rows if r.get("slug")}
    except Exception:
        pass
    stale_wt = [
        {"branch": b, "worktree": wt_map[b]}
        for b in wt_map
        if b.startswith("agent/") and b[len("agent/"):] not in running_slugs
    ]

    missing_slugs = {item["slug"] for item in missing_out}
    reflog_hints = []
    if missing_slugs and repo and os.path.isdir(repo):
        try:
            r = subprocess.run(
                ["git", "reflog", "--format=%H %gs"],
                cwd=repo, capture_output=True, text=True, timeout=30,
            )
            seen = set()
            for line in r.stdout.splitlines():
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                sha, ref_action = parts
                for slug in missing_slugs:
                    if slug in ref_action and slug not in seen:
                        seen.add(slug)
                        reflog_hints.append({"slug": slug, "sha": sha})
        except Exception:
            pass

    return {
        "local": local_out,
        "remote_only": remote_only_out,
        "missing": missing_out,
        "stale_worktrees": stale_wt,
        "reflog_hints": reflog_hints,
    }


run = sweep


if __name__ == "__main__":
    import json
    print(json.dumps(sweep(), indent=2, default=str))
