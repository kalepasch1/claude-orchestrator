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
import datetime, json, os, re, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import approval_merge   # reuse _slug_from + _free_branch (the worktree-unlock fix)
import agentic_repair

MARK = "train"                                   # decided_by prefix => handled by the train
SKIP_PREFIXES = ("merge-handler", "train")       # cards already handled by any integration path
MERGE_KINDS = ("verify", "material", "integrate")
TEST_CMD = os.environ.get("TEST_CMD", "npm test")
TEST_TIMEOUT = int(os.environ.get("MERGE_TRAIN_TEST_TIMEOUT", "1800"))
MERGING_STATE = os.environ.get("MERGE_TRAIN_STATE", "RUNNING")
LOW_RISK_BATCH = int(os.environ.get("MERGE_TRAIN_LOW_RISK_BATCH", "8"))
STANDARD_BATCH = int(os.environ.get("MERGE_TRAIN_STANDARD_BATCH", "3"))
SENSITIVE_BATCH = int(os.environ.get("MERGE_TRAIN_SENSITIVE_BATCH", "1"))
PRESSURE_KEY = "merge_train_pressure"
SENSITIVE_RE = re.compile(r"secret|token|oauth|auth|rls|security|pricing|legal|compliance|regulatory|privacy|payment|stripe", re.I)
LOW_RISK_KINDS = {"docs", "chore", "lint", "format", "mechanical", "test", "tests"}


# ── git plumbing (each step never assumes what's checked out) ─────────────────

def _git(repo, *args, timeout=60):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)


def _branch_exists(repo, branch):
    return _git(repo, "rev-parse", "--verify", branch).returncode == 0


def _materialize_branch(repo, branch):
    """Fleet-aware branch lookup: if the branch is not local, try to fetch it from origin
    (the OTHER runner Mac pushes agent/* after verify). Creates a local branch ref from the
    remote so the train steps (rebase/ff) can proceed. Returns True when a local ref exists.
    Fail-soft on offline/no-remote — falls back to local-only behavior."""
    if _branch_exists(repo, branch):
        return True
    if not repo or not os.path.isdir(repo):
        return False
    try:
        _git(repo, "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", timeout=120)
        if _git(repo, "rev-parse", "--verify", f"refs/remotes/origin/{branch}").returncode != 0:
            return False
        return _git(repo, "branch", branch, f"refs/remotes/origin/{branch}").returncode == 0 \
            or _branch_exists(repo, branch)
    except Exception:
        return False


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


def _test_cmd_for(proj, repo):
    """Use a real package-root command when the repo root has no package.json."""
    cmd = proj.get("test_cmd") or TEST_CMD
    try:
        import build_gate
        if cmd and (os.path.isfile(os.path.join(repo, "package.json"))
                    or not build_gate._root_npm_cmd_without_package(repo, cmd)):
            return cmd
        for root in build_gate.dependency_prewarm.package_roots(repo):
            scripts = build_gate._load_scripts(root)
            for script in ("test", "test:unit", "typecheck", "type-check", "build"):
                if script in scripts:
                    return build_gate.script_cmd(repo, root, script)
        return build_gate.detect_build_cmd(repo) or cmd
    except Exception:
        return cmd


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


def _normalize_task_base(repo, proj, requested):
    for b in (requested, proj.get("default_base"), proj.get("prod_branch"), "main", "master"):
        if _branch_exists(repo, b):
            return b
    return requested or proj.get("default_base") or "main"


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


def _risk_level(card, task):
    blob = " ".join(str(x or "") for x in (
        card.get("kind"), card.get("title"), card.get("why"), task.get("kind"),
        task.get("slug"), task.get("prompt"), task.get("note")))
    if task.get("material") or card.get("kind") == "material" or SENSITIVE_RE.search(blob):
        return "sensitive"
    if str(task.get("kind") or "").lower() in LOW_RISK_KINDS or str(task.get("slug") or "").startswith(("batch-mech", "lint-", "docs-")):
        return "low"
    return "standard"


def _age_seconds(ts):
    if not ts:
        return 0
    raw = str(ts).replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(raw)
        now = datetime.datetime.now(datetime.timezone.utc) if dt.tzinfo else datetime.datetime.utcnow()
        return max(0, int((now - dt).total_seconds()))
    except Exception:
        return 0


def _record_pressure(by_project, projects):
    payload = {"generated_at": datetime.datetime.utcnow().isoformat(), "projects": {}}
    for pid, group in by_project.items():
        proj = projects.get(pid, {})
        name = proj.get("name") or str(pid)
        repo = proj.get("repo_path", "")
        p = {"passed_waiting": 0, "missing_branch": 0, "oldest_wait_age_s": 0,
             "risk": {"low": 0, "standard": 0, "sensitive": 0}}
        for card, slug, task in group:
            risk = _risk_level(card, task)
            p["risk"][risk] += 1
            if _materialize_branch(repo, f"agent/{slug}"):
                p["passed_waiting"] += 1
                p["oldest_wait_age_s"] = max(p["oldest_wait_age_s"], _age_seconds(card.get("created_at") or task.get("updated_at")))
            else:
                p["missing_branch"] += 1
        payload["projects"][name] = p
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


def _attribute_merge_outcome(slug, task):
    """Credit the original coder when a delayed train merge finally succeeds."""
    patch = {"integrated": True}
    for extra in (
        {"merge_attributed_by": "merge_train", "merged_at": "now()"},
        {},
    ):
        try:
            db.update("outcomes", {"slug": slug}, {**patch, **extra})
            return True
        except Exception:
            continue
    try:
        db.insert("outcomes", {"task_id": task.get("id"), "project": task.get("project_id"),
                               "slug": slug, "kind": task.get("kind") or "build",
                               "model": task.get("model") or "unknown",
                               "tests_passed": True, "integrated": True,
                               "usd": 0, "wall_ms": 0, "attempts": task.get("attempt") or 1})
        return True
    except Exception:
        return False


def _attribute_train_outcome(slug, task, outcome, integrated=False):
    patch = {"integrated": bool(integrated)}
    extras = {"train_outcome": outcome, "merge_attributed_by": "merge_train", "merged_at": "now()"} if integrated else {
        "train_outcome": outcome, "merge_attributed_by": "merge_train"}
    for candidate in ({**patch, **extras}, patch):
        try:
            db.update("outcomes", {"slug": slug}, candidate)
            return True
        except Exception:
            continue
    return False


def _select_batch(group):
    """Return the project's cards sorted (risk band, then age), DEDUPED by slug.

    Duplicate cards for one slug (240 were found for a single slug) used to flood
    every batch: keep the NEWEST card per slug and terminally mark the rest so
    they are never picked again. Cap enforcement moved to train_run, which only
    charges the cap for REAL integration attempts (merged/testfail/conflict) —
    non-actionable outcomes (waiting/redo/branch-missing) no longer starve cards
    whose branches actually exist (the 96%-pass / 2.75%-merge blockade)."""
    newest_by_slug = {}
    for card, slug, task in group:
        cur = newest_by_slug.get(slug)
        if cur is None or str(card.get("created_at") or "") > str(cur[0].get("created_at") or ""):
            newest_by_slug[slug] = (card, slug, task)
    for card, slug, task in group:
        keep = newest_by_slug.get(slug)
        if keep is not None and card.get("id") != keep[0].get("id"):
            try:
                db.update("approvals", {"id": card["id"]},
                          {"decided_by": f"{MARK}:dup-card", "status": "approved"})
            except Exception:
                pass
    annotated = [(card, slug, task, _risk_level(card, task))
                 for card, slug, task in newest_by_slug.values()]
    annotated.sort(key=lambda e: ({"low": 0, "standard": 1, "sensitive": 2}[e[3]],
                                  str(e[0].get("created_at") or "")))
    return annotated


def ensure_integration_card(project, slug, *, kind="integrate", title=None, why=None,
                            detail=None, status="approved", decided_by="canonical-train"):
    """Idempotently feed passed code into the single canonical integration train.

    Producers should not merge directly. They create/approve one code-merge card
    and let train_run serialize rebase, tests, fast-forward, and cleanup.
    """
    if not slug:
        return False
    title = title or f"merge of {slug}"
    cards = db.select("approvals", {"select": "id,slug,title,kind,status,decided_by",
                                    "kind": f"in.({','.join(MERGE_KINDS)})",
                                    "status": "in.(pending,approved)",
                                    "order": "created_at.desc",  # newest first — unordered scans missed dupes past the limit (240 dupes of one slug)
                                    "limit": os.environ.get("MERGE_CARD_DEDUP_SCAN", "4000")}) or []
    for c in cards:
        if str(c.get("decided_by") or "").startswith(SKIP_PREFIXES):
            continue
        cslug = approval_merge._slug_from(c)
        if cslug == slug:
            patch = {}
            if c.get("status") != status:
                patch["status"] = status
            if status == "approved" and not c.get("decided_by"):
                patch["decided_by"] = decided_by
            if patch:
                db.update("approvals", {"id": c["id"]}, patch)
            return False
    row = {"project": project, "kind": kind, "slug": slug, "title": title,
           "status": status, "why": why or "passed tests; queued for canonical merge train",
           "detail": detail or "", "decided_by": decided_by if status == "approved" else None}
    try:
        db.insert("approvals", row)
    except Exception:
        # Some older approval tables may not have a slug column. The title fallback
        # keeps approval_merge._slug_from compatible with those rows.
        row.pop("slug", None)
        db.insert("approvals", row)
    return True


# ── the train ─────────────────────────────────────────────────────────────────

def _pick_cards():
    """Approved merge-kind cards not yet handled by any integration path."""
    cards = db.select("approvals", {"select": "*", "status": "eq.approved",
                                    "kind": f"in.({','.join(MERGE_KINDS)})",
                                    "order": "created_at.desc",
                                    "limit": os.environ.get("MERGE_TRAIN_SCAN_LIMIT", "3000")}) or []
    return [c for c in cards
            if c.get("kind") in MERGE_KINDS
            and approval_merge._is_code_merge_card(c)
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
    task_base = _normalize_task_base(repo, proj, task.get("base_branch") or proj.get("default_base", "main"))
    branch = f"agent/{slug}"

    if not repo or not os.path.isdir(repo):
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:no-repo"})
        _log(pname, slug, "SKIP", "repo missing")
        return "no-repo"

    base = _integration_base(repo, proj, task_base)

    if not _materialize_branch(repo, branch):
        state = task.get("state")
        if state in ("QUEUED", "RUNNING", "RETRY"):
            _log(pname, slug, "WAIT", f"{branch} not created yet ({state})")
            return "waiting-branch"
        tr = int(task.get("transient_retries") or 0)
        cap = int(os.environ.get("MERGE_BRANCH_MISSING_REDO_CAP", "2"))
        if tr < cap:
            patch = agentic_repair.repair_patch(
                task, f"approved card is waiting for missing {branch}",
                category="missing-branch",
                directive=f"Reconstruct missing branch {branch} for the same task from artifacts, cache, patch templates, or minimal regeneration; then run checks and commit.")
            patch["transient_retries"] = tr + 1
            _task_patch(task, patch)
            _log(pname, slug, "REDO", f"branch missing, rebuild ({tr+1}/{cap})")
            return "redo"
        _task_patch(task, {"state": "BLOCKED",
                           "note": f"train: approved, but {branch} is still missing after {cap} rebuilds"})
        # Terminal for THIS card: mark it handled so it stops re-entering every pick cycle
        # (a completed recovery task files a fresh card). Unmarked missing-branch cards were
        # re-selected on every run and starved cards whose branches exist.
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:branch-missing"})
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
            patch = agentic_repair.repair_patch(
                task, f"train: rebase conflict on {branch} against {base}",
                category="conflict",
                directive=f"Rebuild the same task on fresh {base}, resolve the conflict in code, run tests, and commit.")
            patch["transient_retries"] = tr + 1
            _task_patch(task, patch)
            db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:redo"})
            _log(pname, slug, "REDO", f"rebase conflict, rebuild on fresh {base} ({tr+1}/{cap})")
            return "redo"
        _task_patch(task, {"state": "CONFLICT", "note": f"train: still conflicts after {cap} redos - needs manual rebase"})
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:conflict-exhausted"})
        _attribute_train_outcome(slug, task, "conflict", integrated=False)
        _log(pname, slug, "CONFLICT", f"redo cap {cap} exhausted")
        return "conflict"

    ok, tail = _run_tests(repo, _test_cmd_for(proj, repo))  # (3)
    if not ok:
        # NEVER force-merge red work.
        _task_patch(task, {"state": "TESTFAIL", "note": f"train: tests failed on rebased {branch}: {tail[:200]}"})
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:TESTFAIL"})
        _attribute_train_outcome(slug, task, "testfail", integrated=False)
        _log(pname, slug, "TESTFAIL", tail[:120])
        return "testfail"

    if not _ff_base(repo, branch, base):                          # (4)
        # base refused to fast-forward even after a clean rebase (it moved outside the train) —
        # treat like a stale-base conflict and route through the same redo pattern.
        tr = int(task.get("transient_retries") or 0)
        cap = int(os.environ.get("MERGE_CONFLICT_REDO_CAP", "2"))
        if tr < cap:
            _delete_branch(repo, branch)
            patch = agentic_repair.repair_patch(
                task, f"train: base moved and {branch} could not fast-forward onto {base}",
                category="conflict",
                directive=f"Rebuild the same task on fresh {base}, preserve the intended diff, run tests, and commit.")
            patch["transient_retries"] = tr + 1
            _task_patch(task, patch)
            db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:redo"})
            _log(pname, slug, "REDO", f"ff refused ({tr+1}/{cap})")
            return "redo"
        _task_patch(task, {"state": "CONFLICT", "note": f"train: base won't fast-forward after {cap} redos"})
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:conflict-exhausted"})
        _attribute_train_outcome(slug, task, "ff-conflict", integrated=False)
        _log(pname, slug, "CONFLICT", "ff refused, cap exhausted")
        return "conflict"

    push_err = _push_base(repo, base)                             # (5)
    note = f"train: MERGED into {base}"
    if push_err:
        note += f" ({push_err})"

    _task_patch(task, {"state": "MERGED", "note": note})  # (6)
    db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:MERGED"})
    _attribute_merge_outcome(slug, task)
    _attribute_train_outcome(slug, task, "merged", integrated=True)
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

    pressure = _record_pressure(by_project, projects)
    summary = {"projects": 0, "merged": 0, "redo": 0, "testfail": 0, "conflict": 0,
               "skipped": 0, "risk": {"low": 0, "standard": 0, "sensitive": 0},
               "pressure": pressure}
    caps = {"low": LOW_RISK_BATCH, "standard": STANDARD_BATCH, "sensitive": SENSITIVE_BATCH}
    ATTEMPT_OUTCOMES = ("merged", "testfail", "conflict")  # only real attempts consume the cap
    scan_cap = int(os.environ.get("MERGE_TRAIN_SCAN_PER_PROJECT", "200"))
    for pid, group in by_project.items():
        proj = projects.get(pid, {})
        summary["projects"] += 1
        used = {"low": 0, "standard": 0, "sensitive": 0}
        scanned = 0
        for card, slug, task, risk in _select_batch(group):
            if used[risk] >= caps[risk] or scanned >= scan_cap:
                continue
            scanned += 1
            summary["risk"][risk] += 1
            outcome = _integrate_card(card, slug, task, proj)
            if outcome in ATTEMPT_OUTCOMES:
                used[risk] += 1
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
