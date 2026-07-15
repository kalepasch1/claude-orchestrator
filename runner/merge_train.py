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
        5. push the unified dev/staging branch when enabled (ORCH_PUSH_ON_DEV_MERGE=true);
           direct prod pushes are blocked unless ORCH_ALLOW_DIRECT_PROD_MERGE=true
        6. mark task MERGED + card decided_by='train:MERGED'

Because the base only advances through the train, every later branch rebases onto the
just-advanced base — later members always see earlier members' work. Stale-base conflicts
become ordinary rebases; a REAL rebase conflict triggers the redo-on-fresh-base pattern
(delete stale branch, requeue the task to rebuild on the new base, capped by
MERGE_CONFLICT_REDO_CAP). Test failures mark the task TESTFAIL — the train NEVER force-merges.

Idempotent: handled cards get decided_by='train:*'; cards already handled by this train or by
the legacy merge-handler are skipped.
"""
import concurrent.futures, datetime, json, os, re, sys, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import events
import approval_merge   # reuse _slug_from + _free_branch (the worktree-unlock fix)
import agentic_repair
import repo_lock         # per-repo mutex: concurrent train_run() calls must not race git refs
import repo_hygiene      # strip stray untracked .js shadowing .ts before every test run
import semantic_merge    # AST-level auto-resolution for rebase conflicts
import integration_runtime


def emit(kind, **fields):
    """Public fail-soft event adapter used by integrations and diagnostics."""
    return events.emit(kind, **fields)

MARK = "train"                                   # decided_by prefix => handled by the train
SKIP_PREFIXES = ("merge-handler", "train")       # cards already handled by any integration path
MERGE_KINDS = ("verify", "material", "integrate")
TEST_CMD = os.environ.get("TEST_CMD", "npm test")

def _test_timeout():
    """Read at call time so fleet_config changes take effect without restart."""
    try:
        return int(os.environ.get("MERGE_TRAIN_TEST_TIMEOUT", "300"))
    except ValueError:
        return 300

TEST_TIMEOUT = _test_timeout()  # backward-compat module-level ref
MERGING_STATE = os.environ.get("MERGE_TRAIN_STATE", "RUNNING")
LOW_RISK_BATCH = int(os.environ.get("MERGE_TRAIN_LOW_RISK_BATCH", "8"))
STANDARD_BATCH = int(os.environ.get("MERGE_TRAIN_STANDARD_BATCH", "3"))
SENSITIVE_BATCH = int(os.environ.get("MERGE_TRAIN_SENSITIVE_BATCH", "1"))
PRESSURE_KEY = "merge_train_pressure"
SENSITIVE_RE = re.compile(r"secret|token|oauth|auth|rls|security|pricing|legal|compliance|regulatory|privacy|payment|stripe", re.I)
LOW_RISK_KINDS = {"docs", "chore", "lint", "format", "mechanical", "test", "tests"}


# ── git plumbing (each step never assumes what's checked out) ─────────────────

def _truthy(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return bool(default)
    return str(val).lower() in ("1", "true", "yes", "on")


def _staging_branch():
    return os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev")


def _push_enabled_for_base(base):
    staging = _staging_branch()
    if base == staging:
        return _truthy("ORCH_PUSH_ON_DEV_MERGE", True)
    if _truthy("ORCH_BATCH_DEV_RELEASE", True) and not _truthy("ORCH_ALLOW_DIRECT_PROD_MERGE", False):
        return False
    return _truthy("ORCH_PUSH_ON_MERGE", False)

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
    """Step 2: rebase the branch onto the CURRENT base in an ISOLATED worktree
    (approval_merge._rebase_isolated). The old `git rebase base branch` form checked the branch
    out in the repo's OWN primary checkout, and an aborted rebase left the main checkout parked
    on an agent branch — the runner then executed stale agent-branch code for hours (root cause
    of the 2026-07-08/09 checkout-drift incidents). Never mutate the main checkout here."""
    approval_merge._free_branch(repo, branch)
    if _git(repo, "merge-base", "--is-ancestor", base, branch).returncode == 0:
        return True  # already based on current base
    return approval_merge._rebase_isolated(repo, base, branch)


def _already_integrated(repo, branch, base):
    return _git(repo, "merge-base", "--is-ancestor", branch, base).returncode == 0


def _try_semantic_merge(repo, branch, base):
    """Attempt AST-level semantic merge when rebase fails.

    Identifies files changed on both sides since their merge-base, then uses
    semantic_merge to resolve non-overlapping edits without a full redo.
    Returns True if ALL conflicting files were auto-merged and a new commit
    was created on `branch` that sits on top of `base`. Returns False on any
    failure (caller falls through to existing redo logic).

    Fail-soft: any exception returns False.
    """
    try:
        # find the merge-base commit
        mb = _git(repo, "merge-base", branch, base)
        if mb.returncode != 0:
            return False
        merge_base = mb.stdout.strip()
        if not merge_base:
            return False

        # files changed on the branch side (merge-base..branch)
        branch_diff = _git(repo, "diff", "--name-only", merge_base, branch)
        base_diff = _git(repo, "diff", "--name-only", merge_base, base)
        if branch_diff.returncode != 0 or base_diff.returncode != 0:
            return False

        branch_files = set(branch_diff.stdout.strip().splitlines())
        base_files = set(base_diff.stdout.strip().splitlines())
        conflicting = branch_files & base_files
        if not conflicting:
            return False  # no overlapping files — rebase should have succeeded, don't mask the real issue

        # check all conflicting files can be auto-merged
        file_contents = {}  # filepath -> (ancestor, branch_ver, base_ver)
        for fp in conflicting:
            ancestor = _git(repo, "show", f"{merge_base}:{fp}")
            branch_ver = _git(repo, "show", f"{branch}:{fp}")
            base_ver = _git(repo, "show", f"{base}:{fp}")
            # any missing file (added/deleted on one side) — bail out, too complex
            if ancestor.returncode != 0 or branch_ver.returncode != 0 or base_ver.returncode != 0:
                return False
            file_contents[fp] = (ancestor.stdout, branch_ver.stdout, base_ver.stdout)

        # phase 1: check all files are mergeable before touching anything
        for fp, (anc, bv, basev) in file_contents.items():
            if not semantic_merge.can_auto_merge(anc, bv, basev, filepath=fp):
                return False

        # phase 2: merge all files
        merged_contents = {}
        for fp, (anc, bv, basev) in file_contents.items():
            result = semantic_merge.semantic_merge(anc, bv, basev, filepath=fp)
            if result.get("merged") is None:
                return False
            merged_contents[fp] = result["merged"]

        # phase 3: create a new commit on branch that sits on base with merged content
        # use a temporary worktree to avoid touching the main checkout
        wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt",
                          f"smerge-{branch.replace('/', '-')}")
        try:
            os.makedirs(os.path.dirname(wt), exist_ok=True)
            added = subprocess.run(["git", "worktree", "add", "-f", wt, branch], cwd=repo,
                                   capture_output=True, timeout=60)
            if added.returncode != 0 or not os.path.isdir(wt):
                return False

            # reset the worktree branch to base (all base content), then overlay merged files
            reset = subprocess.run(["git", "reset", "--hard", base], cwd=wt,
                                   capture_output=True, timeout=30)
            if reset.returncode != 0:
                return False

            # apply all branch-only changes (files branch touched that base didn't)
            branch_only = branch_files - conflicting
            for fp in branch_only:
                bv = _git(repo, "show", f"{branch}:{fp}")
                if bv.returncode != 0:
                    return False
                fp_abs = os.path.join(wt, fp)
                os.makedirs(os.path.dirname(fp_abs), exist_ok=True)
                with open(fp_abs, "w", errors="replace") as f:
                    f.write(bv.stdout)
                subprocess.run(["git", "add", fp], cwd=wt, capture_output=True)

            # write merged content for conflicting files
            for fp, content in merged_contents.items():
                fp_abs = os.path.join(wt, fp)
                os.makedirs(os.path.dirname(fp_abs), exist_ok=True)
                with open(fp_abs, "w", errors="replace") as f:
                    f.write(content)
                subprocess.run(["git", "add", fp], cwd=wt, capture_output=True)

            # commit
            msg = f"train: semantic merge of {branch} onto {base} (auto-resolved {len(merged_contents)} file(s))"
            commit = subprocess.run(["git", "commit", "--allow-empty", "-m", msg], cwd=wt,
                                    capture_output=True, timeout=30)
            if commit.returncode != 0:
                return False
            return True
        finally:
            try:
                subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo,
                               capture_output=True, timeout=30)
            except Exception:
                pass
    except Exception:
        return False


def _ensure_node_deps(repo):
    """A node repo whose node_modules is missing makes every test/typecheck fail with
    'cannot find module' — an ENVIRONMENT failure, not a code failure, that was TESTFAIL-ing
    all JS/TS merges (2026-07-10: smarter 'cannot find module vue'). Lazily install deps once
    per repo per process when they're absent. Idempotent; fail-soft (let the test surface the
    real error if install fails).

    2026-07-10: this walks the WHOLE repo tree and used to give each nested package.json its
    own fresh MERGE_TRAIN_NPM_TIMEOUT (default 600s) budget. In a repo with several nested
    packages, that's several independent 600s budgets stacked sequentially -- a single train
    process (holding that repo's exclusive lock the entire time) sat idle for 74+ minutes
    across a handful of installs, well past any one install's own timeout, blocking every
    other project's merges in that same train run. Now enforces one CUMULATIVE budget
    (MERGE_TRAIN_NPM_TOTAL_TIMEOUT, default 900s) across all installs triggered by a single
    call, so a monorepo with many nested packages can't multiply timeouts into an effectively
    unbounded hold on the repo lock."""
    total_budget = float(os.environ.get("MERGE_TRAIN_NPM_TOTAL_TIMEOUT", "900"))
    per_install_cap = int(os.environ.get("MERGE_TRAIN_NPM_TIMEOUT", "600"))
    deadline = time.monotonic() + total_budget
    try:
        for root, _dirs, files in os.walk(repo):
            if ".git" in root or "/node_modules" in root:
                _dirs[:] = [d for d in _dirs if d != "node_modules" and d != ".git"]
            if "package.json" in files and not os.path.isdir(os.path.join(root, "node_modules")):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break  # cumulative budget exhausted; leave any further packages uninstalled
                cmd = "npm ci" if os.path.isfile(os.path.join(root, "package-lock.json")) else "npm install"
                try:
                    subprocess.run(["bash", "-lc", cmd], cwd=root, capture_output=True,
                                   text=True, timeout=min(per_install_cap, remaining))
                except subprocess.TimeoutExpired:
                    # this one install is over budget -- move on rather than let a single
                    # slow/hung install consume the entire remaining cumulative budget doing
                    # nothing else useful.
                    continue
    except Exception:
        pass


def _run_tests(repo, test_cmd, ref=None):
    """Step 3: run the gate. Returns (ok, tail-of-output)."""
    if not test_cmd:
        return True, "no test_cmd configured"
    if ref:
        import shutil, tempfile
        root = tempfile.mkdtemp(prefix="merge-qa-")
        worktree = os.path.join(root, "candidate")
        try:
            added = _git(repo, "worktree", "add", "--detach", worktree, ref)
            if added.returncode != 0:
                return False, "could not create branch-exact QA worktree: " + (added.stderr or "")[-500:]
            for shared in ("node_modules", ".env", ".env.local"):
                src, dst = os.path.join(repo, shared), os.path.join(worktree, shared)
                if os.path.exists(src) and not os.path.exists(dst):
                    try: os.symlink(src, dst)
                    except OSError: pass
            return _run_tests(worktree, test_cmd)
        finally:
            _git(repo, "worktree", "remove", "--force", worktree)
            shutil.rmtree(root, ignore_errors=True)
    timeout = _test_timeout()
    if "npm" in test_cmd or "vitest" in test_cmd or "vue-tsc" in test_cmd or "tsc" in test_cmd or "jest" in test_cmd:
        # 2026-07-10: a leftover untracked compiled .js shadowing its .ts source (local build
        # residue, invisible to git status) broke every test run touching it -- twice today,
        # once at 10 files (beethoven, tracked -- needed a human) and once at 4106 (tomorrow,
        # all untracked). This strips only the untracked kind before every test run so the
        # gate can't be blocked by this class of bug again. See repo_hygiene.py.
        try:
            cleaned = repo_hygiene.clean_stray_js_duplicates(repo)
            if cleaned:
                print(f"merge_train: cleaned {len(cleaned)} stray untracked .js file(s) shadowing .ts in {repo}")
        except Exception:
            pass
        _ensure_node_deps(repo)
    try:
        r = subprocess.run(["bash", "-lc", test_cmd], cwd=repo, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"tests timed out after {timeout}s"
    if r.returncode != 0:
        tail = ((r.stdout or "")[-6000:] + (r.stderr or "")[-6000:]).strip()
        # One retry after a forced install if the failure looks like missing deps (env, not code).
        if any(s in tail.lower() for s in ("cannot find module", "module not found", "eresolve", "command not found")):
            _ensure_node_deps(repo)
            try:
                r2 = subprocess.run(["bash", "-lc", test_cmd], cwd=repo, capture_output=True,
                                    text=True, timeout=timeout)
                if r2.returncode == 0:
                    return True, "green (after dep install)"
                return False, ((r2.stdout or "")[-6000:] + (r2.stderr or "")[-6000:]).strip()
            except subprocess.TimeoutExpired:
                return False, f"tests timed out after {timeout}s"
        return False, tail
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
    (git fetch . branch:base — the approval_merge technique). No force, ever.

    SELF-HEAL (2026-07-14): a leaked ephemeral staging worktree (tempfile 'stg-*', left locked
    when a train process died) keeps `base` checked out forever, so git refuses the ff for
    EVERY card ("refusing to fetch into branch ... checked out at /tmp/stg-*") — this zeroed
    the merge rate. Detect that exact refusal, evict stale stg-* worktrees holding base, retry."""
    approval_merge._free_branch(repo, branch)
    r = _git(repo, "fetch", ".", f"{branch}:{base}")
    if r.returncode == 0:
        return True
    err = (r.stderr or "") + (r.stdout or "")
    if "refusing to fetch into branch" in err:
        out = _git(repo, "worktree", "list", "--porcelain").stdout or ""
        path = None
        for line in out.splitlines() + [""]:
            if line.startswith("worktree "):
                path = line[len("worktree "):].strip()
            elif line.startswith("branch ") and line.endswith(f"refs/heads/{base}"):
                bn = os.path.basename(path or "")
                if path and os.path.abspath(path) != os.path.abspath(repo) and bn.startswith("stg-"):
                    _git(repo, "worktree", "unlock", path)
                    _git(repo, "worktree", "remove", "--force", path)
        _git(repo, "worktree", "prune")
        r = _git(repo, "fetch", ".", f"{branch}:{base}")
        return r.returncode == 0
    return False


def _push_base(repo, base):
    """Step 5: push only when enabled for this base. Returns '' or an error tail.

    On a non-fast-forward rejection (origin moved while we merged — e.g. the other Mac pushed),
    reconcile once in an ISOLATED worktree: fetch origin/base, rebase local base's extra commits
    onto it, retry the push. Still failing -> return the error; the CALLER must NOT mark the task
    MERGED (a failed push previously counted as a merge and desynced the DB from GitHub)."""
    if not _push_enabled_for_base(base):
        return ""
    r = _git(repo, "push", "origin", base, timeout=300)
    if r.returncode == 0:
        return ""
    err = (r.stderr or "")
    if "non-fast-forward" in err or "fetch first" in err or "rejected" in err:
        try:
            _git(repo, "fetch", "origin", base, timeout=120)
            if approval_merge._rebase_isolated(repo, f"origin/{base}", base):
                r2 = _git(repo, "push", "origin", base, timeout=300)
                if r2.returncode == 0:
                    return ""
                err = (r2.stderr or "")
            else:
                return "PUSHFAIL:reconcile-rebase-conflict:" + err[-120:]
        except Exception as e:
            err = f"{e} | {err}"
    return "PUSHFAIL:" + err[-120:]


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
    dev = _staging_branch()
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
    # Prompts include a fleet-wide security/compliance boilerplate. Scanning the
    # complete prompt made virtually every ordinary task "sensitive" and reduced
    # the train to one attempt per project. Classify the task's identity and the
    # human/QA merge card; material remains an explicit fail-closed override.
    blob = " ".join(str(x or "") for x in (
        card.get("kind"), card.get("title"), card.get("why"), task.get("kind"),
        task.get("slug")))
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
        repo = db.localize_repo_path(proj.get("repo_path", ""))
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
    """Approved merge-kind cards not yet handled by any integration path.

    CORRECTION (2026-07-10): a same-day fix (#6) briefly treated ANY non-empty decided_by as
    "already handled" and filtered decided_by=is.null at the DB level. That was wrong:
    ensure_integration_card() stamps every freshly-created card with
    decided_by="canonical-train:sweeper" / "canonical-train:runner" as an ATTRIBUTION marker
    (who queued it for the train) at CREATION time, not a verdict. Only the train's own
    outcome markers (f"{MARK}:..." = "train:MERGED"/"train:TESTFAIL"/"train:redo"/etc., or the
    legacy "merge-handler:...") mean a card has actually been examined. Filtering on
    "any decided_by" made every card invisible to the train the instant it was created --
    a total-stall regression (zero cards ever picked, forever), worse than the slow-scan bug
    it was meant to fix. Reverted to the SKIP_PREFIXES prefix check. The real fix for the slow
    N+1 scan is in train_run(): task resolution is now batched into one query instead of one
    per card (see _resolve_tasks_batch below).
    """
    cards = db.select("approvals", {"select": "*", "status": "eq.approved",
                                    "kind": f"in.({','.join(MERGE_KINDS)})",
                                    "order": "created_at.desc",
                                    "limit": os.environ.get("MERGE_TRAIN_SCAN_LIMIT", "3000")}) or []
    return [c for c in cards
            if c.get("kind") in MERGE_KINDS
            and approval_merge._is_code_merge_card(c)
            and not str(c.get("decided_by") or "").startswith(SKIP_PREFIXES)]


def _resolve_task(card, tasks_by_slug=None):
    """Card -> (slug, task) using the same slug conventions as approval_merge.

    tasks_by_slug, if given, is a pre-fetched {slug: [tasks]} map (see _resolve_tasks_batch) --
    avoids one network round-trip per card. Falls back to a single-slug query when omitted, so
    existing callers/tests that exercise this function directly keep working unchanged.
    """
    slug = approval_merge._slug_from(card)
    if not slug:
        return None, None
    if tasks_by_slug is not None:
        tasks = tasks_by_slug.get(slug, [])
    else:
        tasks = db.select("tasks", {"select": "*", "slug": f"eq.{slug}"}) or []
    preferred = ("BLOCKED", MERGING_STATE, "DONE", "MERGED", "RUNNING", "QUEUED", "RETRY")
    t = next((x for state in preferred for x in tasks if x.get("state") == state),
             tasks[0] if tasks else None)
    return slug, t


def _resolve_tasks_batch(cards):
    """Batch task lookup for a set of cards into a single query.

    train_run() used to call _resolve_task() per card, each doing its own
    db.select("tasks", {"slug": f"eq.{slug}"}) network round-trip -- with hundreds/thousands
    of eligible cards per cycle this serialized network latency stalled every train invocation,
    which in turn queued up overlapping runs on the repo lock. Fetch every candidate slug's
    tasks in one in.(...) query and hand back a {slug: [tasks]} map for _resolve_task to use.
    """
    slugs = sorted({approval_merge._slug_from(c) for c in cards if approval_merge._slug_from(c)})
    if not slugs:
        return {}
    tasks_by_slug = {}
    # Supabase/PostgREST in.() lists have a practical URL-length ceiling; chunk defensively.
    chunk_size = int(os.environ.get("MERGE_TRAIN_SLUG_CHUNK", "200"))
    for i in range(0, len(slugs), chunk_size):
        chunk = slugs[i:i + chunk_size]
        rows = db.select("tasks", {"select": "*", "slug": f"in.({','.join(chunk)})"}) or []
        for t in rows:
            tasks_by_slug.setdefault(t.get("slug"), []).append(t)
    return tasks_by_slug


def _integrate_card(card, slug, task, proj, repo_override=None):
    """Run one card through the train steps. Returns the outcome string for the summary."""
    # 2026-07-11: proj["repo_path"] is one shared absolute path stored fleet-wide
    # (e.g. /Users/kpasch/Documents/foo). On a second machine with a different home
    # directory that path doesn't exist, so merge_train crashed on every single cycle
    # there (observed: 676+ consecutive FileNotFoundError tracebacks, zero successful
    # merges for hours, worked around same-day with a manual symlink farm on that one
    # machine). localize_repo_path() rewrites the /Users/<user>/ prefix to THIS host's
    # home when a local clone exists there, so this works on any machine without a
    # manual per-host workaround.
    repo = repo_override or db.localize_repo_path(proj.get("repo_path", ""))
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
    if _already_integrated(repo, branch, base):
        _task_patch(task, {"state": "MERGED",
                           "note": f"train: already integrated in {base}"})
        db.update("approvals", {"id": card["id"]},
                  {"decided_by": f"{MARK}:ALREADY_INTEGRATED"})
        _attribute_merge_outcome(slug, task)
        _attribute_train_outcome(slug, task, "already-integrated", integrated=True)
        approval_merge._free_branch(repo, branch)
        _log(pname, slug, "ALREADY", f"present in {base}; no ref advance")
        return "already-integrated"
    _task_patch(task, {"state": MERGING_STATE, "note": f"train: integrating {branch} into {base}"})

    if not _rebase_onto_base(repo, branch, base):                 # (2)
        # --- semantic merge attempt: try AST-level auto-resolution before expensive redo ---
        _semantic_ok = False
        try:
            _semantic_ok = _try_semantic_merge(repo, branch, base)
        except Exception:
            pass  # fail-soft: any error → fall through to redo
        if not _semantic_ok and os.environ.get("ORCH_MINIMAL_COMMIT_EXTRACTION", "true").lower() in ("1", "true", "yes", "on"):
            try:
                import minimal_commit
                approval_merge._free_branch(repo, branch)
                extracted = minimal_commit.extract(repo, branch, base, task)
                _semantic_ok = bool(extracted.get("ok"))
                if _semantic_ok:
                    _log(pname, slug, "MINIMAL_EXTRACT",
                         f"{len(extracted.get('files') or [])} task files onto fresh {base}")
            except Exception:
                _semantic_ok = False
        if _semantic_ok:
            _log(pname, slug, "SEMANTIC_MERGE", f"auto-resolved rebase conflict on {branch}")
            # branch now sits on base with merged content — fall through to step (3): tests
        else:
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

    test_cmd = _test_cmd_for(proj, repo)
    ok, tail = _run_tests(repo, test_cmd, branch)  # (3) branch-exact, never primary checkout
    if not ok and os.environ.get("ORCH_DIFFERENTIAL_QA", "true").lower() in ("1", "true", "yes", "on"):
        try:
            import differential_qa
            baseline = differential_qa.cached(repo, base, test_cmd)
            if baseline is None:
                baseline_ok, baseline_log = _run_tests(repo, test_cmd, base)
                differential_qa.store(repo, base, test_cmd, baseline_ok, baseline_log)
            else:
                baseline_ok, baseline_log = baseline.get("ok"), baseline.get("log", "")
            comparison = differential_qa.compare(tail, baseline_log)
            if not baseline_ok and comparison.get("allowed"):
                ok = True
                tail = "green by differential QA: " + comparison.get("reason", "")
        except Exception:
            pass
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
    if push_err:
        # PUSH-VERIFICATION GATE: a merge is not MERGED until origin actually has it. A failed
        # push previously only annotated the note while the task still went MERGED — DB said
        # shipped, GitHub master never advanced (observed 2026-07-09 02:23). Leave the card
        # undecided so the next train run retries; rebase/tests/ff are idempotent by then.
        _task_patch(task, {"state": "DONE",
                           "note": f"train: merged into local {base}; PUSH PENDING ({push_err})"})
        _attribute_train_outcome(slug, task, "push-pending", integrated=False)
        _log(pname, slug, "PUSH-PENDING", push_err[:120])
        return "push-pending"

    _task_patch(task, {"state": "MERGED", "note": f"train: MERGED into {base}"})  # (6)
    db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:MERGED"})
    _attribute_merge_outcome(slug, task)
    _attribute_train_outcome(slug, task, "merged", integrated=True)
    approval_merge._free_branch(repo, branch)   # cleanup so worktrees never accumulate
    _log(pname, slug, "MERGED", f"-> {base}")
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
    # Batched (one tasks query for every card's slug) instead of one query per card -- with
    # hundreds/thousands of eligible cards per cycle the old per-card N+1 pattern serialized
    # network latency and stalled every train invocation, queuing up overlapping runs on the
    # repo lock. See _resolve_tasks_batch.
    tasks_by_slug = _resolve_tasks_batch(cards)
    by_project = {}
    for c in cards:
        slug, t = _resolve_task(c, tasks_by_slug)
        if not slug:
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:no-slug"})
            continue
        if not t:
            db.update("approvals", {"id": c["id"]}, {"decided_by": f"{MARK}:no-task"})
            continue
        by_project.setdefault(t.get("project_id"), []).append((c, slug, t))

    pressure = _record_pressure(by_project, projects)
    summary = {"projects": 0, "merged": 0, "already_integrated": 0,
               "redo": 0, "testfail": 0, "conflict": 0,
               "skipped": 0, "project_errors": 0,
               "risk": {"low": 0, "standard": 0, "sensitive": 0},
               "pressure": pressure}
    caps = {"low": LOW_RISK_BATCH, "standard": STANDARD_BATCH, "sensitive": SENSITIVE_BATCH}
    ATTEMPT_OUTCOMES = ("merged", "testfail", "conflict", "push-pending")  # real attempts (tests ran) consume the cap
    scan_cap = int(os.environ.get("MERGE_TRAIN_SCAN_PER_PROJECT", "200"))
    def process_project(item):
        pid, group = item
        proj = projects.get(pid, {})
        result = {"projects": 1, "merged": 0, "already_integrated": 0,
                  "redo": 0, "testfail": 0,
                  "conflict": 0, "skipped": 0,
                  "risk": {"low": 0, "standard": 0, "sensitive": 0}}
        used = {"low": 0, "standard": 0, "sensitive": 0}
        scanned = 0
        # CONCURRENCY FIX (2026-07-08 merge-stall root cause): train_run() can be invoked
        # concurrently for the SAME project -- the 60s scheduler AND, inline, one call per
        # worker thread the instant its task finishes (runner.py integrate() -> train_run()).
        # Without this lock, two concurrent passes over the same project raced on the shared
        # repo's git refs (rebase/branch -f/fast-forward), producing spurious rebase conflicts
        # that were not real content conflicts. Serialize per-repo so only one train ever
        # touches a given project's working copy at a time. On a busy repo where another
        # thread is mid-train, skip this cycle rather than block indefinitely -- the next
        # scheduled pass (or the next task completion) will pick it back up.
        repo_path = db.localize_repo_path(proj.get("repo_path", ""))
        with repo_lock.hold(repo_path, timeout=300, priority=True) as got_lock:
            if not got_lock:
                result["skipped"] += len(group)
                print(f"merge_train: {proj.get('name') or pid} busy (another train holds the repo lock) — skipping this cycle")
                return result
            try:
                with integration_runtime.isolated_repo(repo_path, "merge_train") as integration_repo:
                    for card, slug, task, risk in _select_batch(group):
                        if used[risk] >= caps[risk] or scanned >= scan_cap:
                            continue
                        scanned += 1
                        result["risk"][risk] += 1
                        outcome = _integrate_card(
                            card, slug, task, proj, repo_override=integration_repo
                        )
                        if outcome in ATTEMPT_OUTCOMES:
                            used[risk] += 1
                        if outcome == "merged":
                            result["merged"] += 1
                        elif outcome == "already-integrated":
                            result["already_integrated"] += 1
                        elif outcome == "redo":
                            result["redo"] += 1
                        elif outcome == "testfail":
                            result["testfail"] += 1
                        elif outcome == "conflict":
                            result["conflict"] += 1
                        else:
                            result["skipped"] += 1
            except integration_runtime.IntegrationRuntimeError as exc:
                result["skipped"] += len(group)
                print(f"merge_train: {proj.get('name') or pid} isolation blocked: {exc}")
        return result

    def process_project_isolated(item):
        """One broken repo/toolchain must not abort every other project's train."""
        pid, group = item
        try:
            result = process_project(item)
            result["project_errors"] = 0
            return result
        except Exception as exc:
            pname = (projects.get(pid, {}) or {}).get("name") or str(pid)
            print(f"merge_train [{pname}] PROJECT-ERROR: {type(exc).__name__}: {str(exc)[:500]}",
                  flush=True)
            return {"projects": 1, "merged": 0, "already_integrated": 0,
                    "redo": 0, "testfail": 0, "conflict": 0,
                    "skipped": len(group), "project_errors": 1,
                    "risk": {"low": 0, "standard": 0, "sensitive": 0}}

    items = list(by_project.items())
    workers = min(len(items), max(1, int(os.environ.get("MERGE_TRAIN_PROJECT_WORKERS", "4"))))
    if items:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers,
                                                   thread_name_prefix="merge-project") as pool:
            results = list(pool.map(process_project_isolated, items))
        for result in results:
            for key in ("projects", "merged", "already_integrated", "redo",
                        "testfail", "conflict", "skipped", "project_errors"):
                summary[key] += result[key]
            for risk, count in result["risk"].items():
                summary["risk"][risk] += count
    print(f"merge_train: {summary['merged']} merged, {summary['already_integrated']} already, "
          f"{summary['redo']} redo, "
          f"{summary['testfail']} testfail, {summary['conflict']} conflict, "
          f"{summary['skipped']} skipped, {summary['project_errors']} project errors "
          f"across {summary['projects']} project(s)")
    return summary


_train_run_unleased = train_run


def train_run():
    """Run the whole merge pass under the cross-train single-flight lease."""
    timeout = float(os.environ.get("ORCH_INTEGRATION_LEASE_TIMEOUT_S", "0") or 0)
    with integration_runtime.global_lease("merge_train", timeout=timeout) as acquired:
        if not acquired:
            return {"skipped": "another integration or release train owns the global lease"}
        return _train_run_unleased()


# scheduler-compat alias: the train IS the integration path now
run = train_run


if __name__ == "__main__":
    import json
    # SINGLE-FLIGHT (2026-07-14): the 60s scheduler kept spawning new train processes while a
    # long pass (staging tests take minutes) was still running — 3-4 stacked merge_train.py
    # processes contended on the per-repo locks and burned RAM for zero extra merges. If another
    # instance is already running, exit immediately; the running pass covers this cycle.
    import fcntl
    _lock_path = os.path.join(os.environ.get("CLAUDE_ORCH_HOME",
                              os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime")),
                              "merge-train.single.lock")
    os.makedirs(os.path.dirname(_lock_path), exist_ok=True)
    _lock = open(_lock_path, "a+")
    try:
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        print(json.dumps({"skipped": "another merge_train instance is running"}))
        sys.exit(0)
    print(json.dumps(train_run(), indent=2, default=str))
