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

LIMIT = int(os.environ.get("INTEGRATION_SWEEPER_LIMIT", "80"))
RUN_TRAIN = os.environ.get("INTEGRATION_SWEEPER_RUN_TRAIN", "true").lower() in ("true", "1", "yes")
RECOVERY_PREFIX = "recover-missing-branch-"
PRESSURE_KEY = "merge_train_pressure"
ACTIVE_STATES = "in.(QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED,QUARANTINED)"


def _branch_exists(repo, branch):
    if not repo or not os.path.isdir(repo):
        return False
    return subprocess.run(["git", "rev-parse", "--verify", branch],
                          cwd=repo, capture_output=True).returncode == 0


_FETCHED_AGENT_REFS = set()


def _fetch_agent_refs(repo):
    """One best-effort fetch of the shared agent/* namespace per repo per process.

    The fleet runs on TWO Macs sharing one Supabase queue: agent branches are created on
    whichever machine ran the task, so a purely local rev-parse on the other machine
    mislabels finished work as 'missing branch' and files recovery churn. Fetching
    refs/heads/agent/* into refs/remotes/origin/agent/* makes the check fleet-aware.
    Fail-soft: offline / no remote just means we fall back to local-only visibility.
    """
    if not repo or repo in _FETCHED_AGENT_REFS or not os.path.isdir(repo):
        return
    _FETCHED_AGENT_REFS.add(repo)
    try:
        subprocess.run(["git", "fetch", "origin",
                        "+refs/heads/agent/*:refs/remotes/origin/agent/*", "--prune"],
                       cwd=repo, capture_output=True, timeout=120)
    except Exception:
        pass


def _branch_exists_anywhere(repo, branch):
    """True if the branch exists locally OR on origin (the other runner's Mac)."""
    if _branch_exists(repo, branch):
        return True
    _fetch_agent_refs(repo)
    return _branch_exists(repo, f"refs/remotes/origin/{branch}")


def _normalize_base(repo, proj, requested):
    for b in (requested, proj.get("default_base"), proj.get("prod_branch"), "main", "master"):
        if b and _branch_exists(repo, b):
            return b
    return requested or proj.get("default_base") or proj.get("prod_branch") or "main"


def _looks_passed(task):
    note = (task.get("note") or "").lower()
    return (
        task.get("state") == "DONE"
        or "verify pass" in note
        or "passed tests" in note
        or "tests pass" in note
        or "work passed tests" in note
    )


def _existing_recovery(project_id, slug):
    if str(slug or "").startswith(RECOVERY_PREFIX):
        return True
    try:
        rows = db.select("tasks", {"select": "slug,state", "project_id": f"eq.{project_id}",
                                   "slug": f"eq.{RECOVERY_PREFIX}{slug}",
                                   "state": ACTIVE_STATES,
                                   "limit": "1"}) or []
        if rows:
            return True
        rework = db.select("tasks", {"select": "slug,state", "project_id": f"eq.{project_id}",
                                     "slug": f"like.rework-%-{RECOVERY_PREFIX}{slug}%",
                                     "state": ACTIVE_STATES,
                                     "limit": "1"}) or []
        return bool(rework)
    except Exception:
        return False


def _active_recovery_index(limit=5000):
    """Load active recovery/rework rows once so sweep does not do N DB reads."""
    rows = []
    for pattern in (f"{RECOVERY_PREFIX}%", f"rework-%-{RECOVERY_PREFIX}%"):
        try:
            rows.extend(db.select("tasks", {"select": "slug,state,project_id",
                                            "slug": f"like.{pattern}",
                                            "state": ACTIVE_STATES,
                                            "limit": str(limit)}) or [])
        except Exception:
            continue
    exact = set()
    rework = []
    for row in rows:
        slug = str(row.get("slug") or "")
        project_id = row.get("project_id")
        if slug.startswith(RECOVERY_PREFIX):
            exact.add((project_id, _recovery_root(slug)))
        elif RECOVERY_PREFIX in slug:
            rework.append((project_id, slug))
    return {"exact": exact, "rework": rework}


def _existing_recovery_indexed(project_id, slug, index):
    if str(slug or "").startswith(RECOVERY_PREFIX):
        return True
    if not index:
        return _existing_recovery(project_id, slug)
    root = _recovery_root(slug)
    if (project_id, root) in index.get("exact", set()):
        return True
    needle = f"{RECOVERY_PREFIX}{root}"
    return any(pid == project_id and needle in rework_slug
               for pid, rework_slug in index.get("rework", []))


def _recovery_root(slug):
    s = str(slug or "")
    while s.startswith(RECOVERY_PREFIX):
        s = s[len(RECOVERY_PREFIX):]
    return s


def recovery_dedup(limit=5000):
    """Collapse duplicate recovery rows without touching the original solved task.

    Recovery tasks are intentionally protected from the generic task_dedup pass, but the sweeper can
    still encounter stale DONE/BLOCKED recovery rows and accidentally create recoveries of recoveries.
    Keep one active representative per (project, original slug) and quarantine the rest so lanes go to
    real rebuilds instead of recursive backlog churn.
    """
    rows = db.select("tasks", {"select": "id,slug,state,project_id,created_at,note",
                               "slug": f"like.{RECOVERY_PREFIX}%",
                               "limit": str(limit),
                               "order": "created_at.asc"}) or []
    groups = {}
    for row in rows:
        groups.setdefault((row.get("project_id"), _recovery_root(row.get("slug"))), []).append(row)
    state_rank = {"MERGED": 0, "DONE": 1, "RUNNING": 2, "QUEUED": 3, "RETRY": 4,
                  "BLOCKED": 5, "QUARANTINED": 6}
    quarantined = duplicate_groups = 0
    for group in groups.values():
        if len(group) <= 1:
            continue
        duplicate_groups += 1
        group.sort(key=lambda r: (state_rank.get(r.get("state"), 9), r.get("created_at") or ""))
        keep = group[0]
        for dup in group[1:]:
            if dup.get("state") in ("MERGED", "QUARANTINED"):
                continue
            db.update("tasks", {"id": dup["id"]},
                      {"state": "QUARANTINED",
                       "note": f"recovery-dedup: duplicate of {keep.get('slug')}; keeping one recovery lane for {_recovery_root(keep.get('slug'))}",
                       "updated_at": "now()"})
            quarantined += 1
    return {"duplicate_groups": duplicate_groups, "quarantined": quarantined}


def _reuse_context(task, proj, repo, base):
    parts = []
    try:
        import result_cache
        sig = result_cache.signature(proj.get("name") or str(task.get("project_id")),
                                     task.get("prompt") or "", repo, base)
        hit = result_cache.lookup(sig)
        if hit:
            parts.append("RESULT CACHE HIT: reuse this prior result before drafting net-new code.\n"
                         f"Cached branch: {hit.get('branch')}\nSummary: {hit.get('summary')}")
    except Exception:
        pass
    try:
        import patch_transplant
        h = patch_transplant.hint(task)
        if h:
            parts.append(h)
    except Exception:
        pass
    try:
        import patch_templates
        _, body = patch_templates.build(task)
        parts.append(body)
    except Exception:
        pass
    return "\n\n".join(p for p in parts if p)


def _queue_recovery(task, proj, recovery_index=None):
    slug = task.get("slug")
    if not slug or _existing_recovery_indexed(task.get("project_id"), slug, recovery_index):
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
    force = task.get("force_coder") or "ollama"
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
        if recovery_index is not None:
            recovery_index.setdefault("exact", set()).add((task.get("project_id"), _recovery_root(slug)))
        return True
    except Exception:
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
            missing += 1
            if _queue_recovery(t, proj, recovery_index=recovery_index):
                recovery += 1
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


run = sweep


if __name__ == "__main__":
    import json
    print(json.dumps(sweep(), indent=2, default=str))
