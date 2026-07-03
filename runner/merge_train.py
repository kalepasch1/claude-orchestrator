#!/usr/bin/env python3
"""
merge_train.py - the serialized integration train. This REPLACES direct/parallel merging as THE
integration path for approved work.

Why a train: when several approved branches merge independently, each one was built (and judged)
against a base that the *previous* merge just moved — so branch N+1 lands on a base it never saw,
producing the stale-base conflicts and phantom TESTFAILs that stalled the queue. The train fixes
that structurally by SERIALIZING integration per project:

    for each project, one branch at a time (oldest approval first):
        1. refresh the base ref
        2. rebase agent/<slug> onto the CURRENT base (freeing any leftover agent worktree first,
           via approval_merge._free_branch — the phantom-CONFLICT root cause)
        3. run the project's test command on the rebased branch
        4. fast-forward the base to the branch (no force, no no-ff surprises)
        5. optionally push (ORCH_PUSH_ON_MERGE=true; normally false for dev batching)
        6. mark task MERGED + card decided_by='train:MERGED'

Because the base only advances through the train, every later branch rebases onto the
just-advanced base — later members always see earlier members' work. Stale-base conflicts
become ordinary rebases; a REAL rebase conflict triggers the redo-on-fresh-base pattern
(delete stale branch, requeue the task to rebuild on the new base, capped by
MERGE_CONFLICT_REDO_CAP). Test failures mark the task TESTFAIL — the train NEVER force-merges.

Idempotent: handled cards get decided_by='train:*'; cards already handled by this train or by
the legacy merge-handler are skipped.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import approval_merge   # reuse _slug_from + _free_branch (the worktree-unlock fix)

MARK = "train"                                   # decided_by prefix => handled by the train
SKIP_PREFIXES = ("merge-handler", "train")       # cards already handled by any integration path
MERGE_KINDS = ("verify", "material", "integrate")
TEST_CMD = os.environ.get("TEST_CMD", "npm test")
TEST_TIMEOUT = int(os.environ.get("MERGE_TRAIN_TEST_TIMEOUT", "1800"))
MERGING_STATE = os.environ.get("MERGE_TRAIN_STATE", "RUNNING")


# ── git plumbing (each step never assumes what's checked out) ─────────────────

def _git(repo, *args, timeout=60):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)


def _branch_exists(repo, branch):
    return _git(repo, "rev-parse", "--verify", branch).returncode == 0


def _task_patch(task, patch):
    db.update("tasks", {"id": task["id"]}, patch)


def _refresh_base(repo, base):
    """Step 1: make sure our view of the base is fresh (best-effort fetch from origin)."""
    try:
        _git(repo, "fetch", "origin", base, timeout=120)
    except Exception:
        pass  # no remote / offline is fine — the local base ref is the source of truth then


def _rebase_onto_base(repo, branch, base):
    """Step 2: rebase the branch onto the CURRENT base. Frees any leftover agent worktree first
    (approval_merge._free_branch — git refuses to rebase a branch checked out elsewhere, and that
    error used to be mislabeled CONFLICT). Returns True on success, False on a real conflict."""
    approval_merge._free_branch(repo, branch)
    if _git(repo, "merge-base", "--is-ancestor", base, branch).returncode == 0:
        return True  # already based on current base
    if _git(repo, "rebase", base, branch, timeout=300).returncode != 0:
        _git(repo, "rebase", "--abort")
        return False
    return True


def _run_tests(repo, test_cmd):
    """Step 3: run the gate. Returns (ok, tail-of-output)."""
    if not test_cmd:
        return True, "no test_cmd configured"
    try:
        r = subprocess.run(["bash", "-lc", test_cmd], cwd=repo, capture_output=True,
                           text=True, timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"tests timed out after {TEST_TIMEOUT}s"
    if r.returncode != 0:
        return False, ((r.stdout or "")[-300:] + (r.stderr or "")[-300:]).strip()
    return True, "green"


def _ff_base(repo, branch, base):
    """Step 4: fast-forward base to the rebased branch WITHOUT checking base out
    (git fetch . branch:base — the approval_merge technique). No force, ever."""
    approval_merge._free_branch(repo, branch)
    return _git(repo, "fetch", ".", f"{branch}:{base}").returncode == 0


def _push_base(repo, base):
    """Step 5: push only when explicitly enabled. Returns '' or an error tail."""
    if os.environ.get("ORCH_PUSH_ON_MERGE", "false").lower() != "true":
        return ""
    r = _git(repo, "push", "origin", base, timeout=300)
    return "" if r.returncode == 0 else "PUSHFAIL:" + (r.stderr or "")[-120:]


def _detect_prod_branch(repo, proj):
    for b in (proj.get("prod_branch"), proj.get("default_base"), "main", "master"):
        if b and _git(repo, "rev-parse", "--verify", b).returncode == 0:
            return b
    return proj.get("default_base") or "main"


def _integration_base(repo, proj, task_base):
    if os.environ.get("ORCH_CODE_MERGE_TARGET", "dev").lower() not in ("dev", "staging", "integration"):
        return task_base
    dev = os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev")
    try:
        if _git(repo, "rev-parse", "--verify", dev).returncode != 0:
            _git(repo, "branch", dev, _detect_prod_branch(repo, proj))
    except OSError:
        return task_base
    return dev


def _delete_branch(repo, branch):
    _git(repo, "branch", "-D", branch)


def _log(project, slug, outcome, extra=""):
    line = f"merge_train [{project}] {slug}: {outcome}"
    if extra:
        line += f" ({extra})"
    print(line)


# ── the train ─────────────────────────────────────────────────────────────────

def _pick_cards():
    """Approved merge-kind cards not yet handled by any integration path."""
    cards = db.select("approvals", {"select": "*", "status": "eq.approved"}) or []
    return [c for c in cards
            if c.get("kind") in MERGE_KINDS
            and not str(c.get("decided_by") or "").startswith(SKIP_PREFIXES)]


def _resolve_task(card):
    """Card -> (slug, task) using the same slug conventions as approval_merge."""
    slug = approval_merge._slug_from(card)
    if not slug:
        return None, None
    tasks = db.select("tasks", {"select": "*", "slug": f"eq.{slug}"}) or []
    preferred = ("BLOCKED", MERGING_STATE, "DONE", "MERGED", "RUNNING", "QUEUED", "RETRY")
    t = next((x for state in preferred for x in tasks if x.get("state") == state),
             tasks[0] if tasks else None)
    return slug, t


def _integrate_card(card, slug, task, proj):
    """Run one card through the train steps. Returns the outcome string for the summary."""
    repo = proj.get("repo_path", "")
    pname = proj.get("name") or str(task.get("project_id"))
    task_base = task.get("base_branch") or proj.get("default_base", "main")
    branch = f"agent/{slug}"

    if not repo or not os.path.isdir(repo):
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:no-repo"})
        _log(pname, slug, "SKIP", "repo missing")
        return "no-repo"

    base = _integration_base(repo, proj, task_base)

    if not _branch_exists(repo, branch):
        state = task.get("state")
        if state in ("QUEUED", "RUNNING", "RETRY"):
            _log(pname, slug, "WAIT", f"{branch} not created yet ({state})")
            return "waiting-branch"
        tr = int(task.get("transient_retries") or 0)
        cap = int(os.environ.get("MERGE_BRANCH_MISSING_REDO_CAP", "2"))
        if tr < cap:
            _task_patch(task, {"state": "QUEUED", "transient_retries": tr + 1,
                               "note": f"train: approved card is waiting for {branch}; rebuild branch ({tr+1}/{cap})"})
            _log(pname, slug, "REDO", f"branch missing, rebuild ({tr+1}/{cap})")
            return "redo"
        _task_patch(task, {"state": "BLOCKED",
                           "note": f"train: approved, but {branch} is still missing after {cap} rebuilds"})
        _log(pname, slug, "BLOCKED", "branch missing")
        return "branch-missing"

    _refresh_base(repo, base)                                     # (1)
    _task_patch(task, {"state": MERGING_STATE, "note": f"train: integrating {branch} into {base}"})

    if not _rebase_onto_base(repo, branch, base):                 # (2)
        # redo-on-fresh-base: a stale branch conflicting with the advanced base should be REBUILT
        # on the new base, not rot as CONFLICT (that's what stalled the queue before).
        tr = int(task.get("transient_retries") or 0)
        cap = int(os.environ.get("MERGE_CONFLICT_REDO_CAP", "2"))
        if tr < cap:
            _delete_branch(repo, branch)
            _task_patch(task, {"state": "QUEUED", "transient_retries": tr + 1,
                               "note": f"train: rebase conflict -> redo on fresh {base} ({tr+1}/{cap})"})
            db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:redo"})
            _log(pname, slug, "REDO", f"rebase conflict, rebuild on fresh {base} ({tr+1}/{cap})")
            return "redo"
        _task_patch(task, {"state": "CONFLICT", "note": f"train: still conflicts after {cap} redos - needs manual rebase"})
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:conflict-exhausted"})
        _log(pname, slug, "CONFLICT", f"redo cap {cap} exhausted")
        return "conflict"

    ok, tail = _run_tests(repo, proj.get("test_cmd") or TEST_CMD)  # (3)
    if not ok:
        # NEVER force-merge red work.
        _task_patch(task, {"state": "TESTFAIL", "note": f"train: tests failed on rebased {branch}: {tail[:200]}"})
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:TESTFAIL"})
        _log(pname, slug, "TESTFAIL", tail[:120])
        return "testfail"

    if not _ff_base(repo, branch, base):                          # (4)
        # base refused to fast-forward even after a clean rebase (it moved outside the train) —
        # treat like a stale-base conflict and route through the same redo pattern.
        tr = int(task.get("transient_retries") or 0)
        cap = int(os.environ.get("MERGE_CONFLICT_REDO_CAP", "2"))
        if tr < cap:
            _delete_branch(repo, branch)
            _task_patch(task, {"state": "QUEUED", "transient_retries": tr + 1,
                               "note": f"train: base moved, could not ff -> redo on fresh {base} ({tr+1}/{cap})"})
            db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:redo"})
            _log(pname, slug, "REDO", f"ff refused ({tr+1}/{cap})")
            return "redo"
        _task_patch(task, {"state": "CONFLICT", "note": f"train: base won't fast-forward after {cap} redos"})
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:conflict-exhausted"})
        _log(pname, slug, "CONFLICT", "ff refused, cap exhausted")
        return "conflict"

    push_err = _push_base(repo, base)                             # (5)
    note = f"train: MERGED into {base}"
    if push_err:
        note += f" ({push_err})"

    _task_patch(task, {"state": "MERGED", "note": note})  # (6)
    db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:MERGED"})
    approval_merge._free_branch(repo, branch)   # cleanup so worktrees never accumulate
    _log(pname, slug, "MERGED", f"-> {base}" + (f", {push_err}" if push_err else ""))
    return "merged"


def _paused():
    try:
        import kill_switch
        return kill_switch.is_paused()
    except Exception:
        return False


def train_run():
    """Entry point: run the integration train across all projects (serialized per project)."""
    if _paused():
        print("merge_train: paused — skipping")
        return {"paused": True}

    cards = _pick_cards()
    projects = {p["id"]: p for p in (db.select("projects") or [])}

    # Resolve every card to its task, then group by project so each project is a serial train.
    by_project = {}
    for c in cards:
        slug, t = _resolve_task(c)
        if not slug:
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:no-slug"})
            continue
        if not t:
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:no-task"})
            continue
        by_project.setdefault(t.get("project_id"), []).append((c, slug, t))

    summary = {"projects": 0, "merged": 0, "redo": 0, "testfail": 0, "conflict": 0, "skipped": 0}
    for pid, group in by_project.items():
        proj = projects.get(pid, {})
        summary["projects"] += 1
        # oldest approval first: later branches always rebase onto the just-advanced base
        group.sort(key=lambda e: str(e[0].get("created_at") or ""))
        for card, slug, task in group:
            outcome = _integrate_card(card, slug, task, proj)
            if outcome == "merged":
                summary["merged"] += 1
            elif outcome == "redo":
                summary["redo"] += 1
            elif outcome == "testfail":
                summary["testfail"] += 1
            elif outcome == "conflict":
                summary["conflict"] += 1
            else:
                summary["skipped"] += 1
    print(f"merge_train: {summary['merged']} merged, {summary['redo']} redo, "
          f"{summary['testfail']} testfail, {summary['conflict']} conflict, "
          f"{summary['skipped']} skipped across {summary['projects']} project(s)")
    return summary


# scheduler-compat alias: the train IS the integration path now
run = train_run


if __name__ == "__main__":
    import json
    print(json.dumps(train_run(), indent=2, default=str))
