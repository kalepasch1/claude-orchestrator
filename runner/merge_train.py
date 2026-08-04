#!/usr/bin/env python3
from __future__ import annotations
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
        4. fast-forward the base to the rebased branch (no force, no no-ff surprises)
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
import datetime, json, os, re, sys, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
# RESTORED 2026-07-31 (overwrite-class recovery; static_sanity gate)
_RELFIX_PREFIXES = ("relfix-", "qafix-", "deployfix-", "buildfix-", "copyfix-")
try:
    import verify as _verify_mod
except Exception:
    _verify_mod = None

import events
import approval_merge   # reuse _slug_from + _free_branch (the worktree-unlock fix)
import integration_runtime
import agentic_repair
import repo_lock        # FIX 2026-07-28: was used at the per-repo serialization site but never
                        # imported -> every train_run() crashed with NameError before integrating
                        # anything (the silent integration-stall root cause).
import concurrent.futures   # FIX 2026-07-28: used by the multi-project ThreadPoolExecutor path, never imported
import repo_hygiene         # FIX 2026-07-28: used pre-test-run (stray .js cleanup), never imported (fail-soft masked it)
import semantic_merge       # FIX 2026-07-28: used by the auto-merge path, never imported
try:
    import pipeline_metrics as _pm
except Exception:
    _pm = None

MARK = "train"                                   # decided_by prefix => handled by the train
# Non-code policy decisions are terminal approval artifacts, not merge work.  If
# they are re-read here, the no-slug fallback needlessly churns the queue and can
# make legacy policy cards look like active integrations.
SKIP_PREFIXES = ("merge-handler", "train", "auto-policy")
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
LOW_RISK_BATCH = int(os.environ.get("MERGE_TRAIN_LOW_RISK_BATCH", "8").strip('"'))
STANDARD_BATCH = int(os.environ.get("MERGE_TRAIN_STANDARD_BATCH", "3").strip('"'))
SENSITIVE_BATCH = int(os.environ.get("MERGE_TRAIN_SENSITIVE_BATCH", "1").strip('"'))
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
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _already_integrated(repo, branch, base):
    """True when branch's tip is already an ancestor of base (nothing left to merge).

    RESTORED 2026-07-31: this helper was dropped by an overwrite while its call
    site survived — every project's train pass then died with NameError, which
    process_project_isolated swallowed into "project_errors", producing
    "0 merged / 58x skipped" on every pass since Jul 28 (the no-prod-deploys
    incident). One line of code; three days of frozen releases.
    """
    return _git(repo, "merge-base", "--is-ancestor", branch, base).returncode == 0


def _branch_exists(repo, branch):
    return _git(repo, "rev-parse", "--verify", branch).returncode == 0


def _materialize_branch(repo, branch):
    """Fleet-aware branch lookup with worktree recovery.

    Resolution order (cheapest first):
      1. Local branch ref exists → True
      2. Worktree has the branch checked out → extract commit, create ref
      3. Fetch from origin (fleet peer may have pushed it)
    Returns True when a local ref exists after all recovery attempts.
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


def _freeze_integration_identity(repo, branch, task, slug):
    """Freeze the post-rebase candidate before any QA or base mutation."""
    import task_refs
    rebased_result = _git(repo, "rev-parse", branch)
    if rebased_result.returncode:
        raise RuntimeError(rebased_result.stderr[-160:] or "rebased commit missing")
    rebased = rebased_result.stdout.strip()
    identity = task_refs.publish(repo, task.get("id") or slug,
                                 task.get("attempt") or 1, rebased,
                                 namespace="integrations")
    if not identity.get("ok"):
        raise RuntimeError(identity.get("reason") or "integration ref failed")
    return {"artifact_commit": rebased, "artifact_ref": identity["ref"]}


def _refresh_base(repo, base):
    """Step 1: make sure our view of the base is fresh (best-effort fetch from origin)."""
    try:
        _git(repo, "fetch", "origin", base, timeout=120)
    except Exception:
        pass  # no remote / offline is fine — the local base ref is the source of truth then


def _post_fork_regression(repo, branch, base, orig_fork):
    """Detect a CLEAN rebase that silently deletes improvements merged after the
    branch forked (operator directive 2026-07-31 — the second wipe vector).

    The conflict path is already safe (no whole-file theirs on source). But a
    branch forked BEFORE an improvement landed can delete that improvement with
    zero git conflict. Guard: lines base gained since fork vs lines the rebased
    branch deletes; overlap >= MERGE_REGRESSION_LINE_THRESHOLD -> hold.
    Returns (ok, detail); fail-open on its own errors.
    """
    try:
        if not orig_fork:
            return True, ""
        thresh = int(os.environ.get("MERGE_REGRESSION_LINE_THRESHOLD", "3"))
        gained = _git(repo, "diff", "--unified=0", orig_fork, base, timeout=120).stdout or ""
        removed = _git(repo, "diff", "--unified=0", base, branch, timeout=120).stdout or ""

        def collect(diff, sign):
            per, cur = {}, None
            for line in diff.splitlines():
                if line.startswith("+++ b/"):
                    cur = line[6:]
                elif cur and line.startswith(sign) and not line.startswith(sign * 3):
                    t = line[1:].strip()
                    if len(t) > 3:
                        per.setdefault(cur, set()).add(t)
            return per

        gained_lines = collect(gained, "+")
        removed_lines = collect(removed, "-")
        hits = []
        for f, rem in removed_lines.items():
            overlap = rem & gained_lines.get(f, set())
            if len(overlap) >= thresh:
                hits.append(f"{f} (-{len(overlap)} recently-improved lines)")
        if hits:
            return False, "; ".join(hits[:6])
        return True, ""
    except Exception:
        return True, ""


def _regression_gate(repo, base, branch, candidate_sha):
    """CONTENT anti-regression gate (2026-08-02 operator directive). Returns (ok, detail).

    _post_fork_regression() above only compares raw text lines the BASE gained SINCE the
    branch forked against lines the branch deletes. Every confirmed historical loss slipped
    past it because the improvement predated the fork point (improvement_miner b9a8fd26,
    pipeline_contract task_fields, integration_sweeper a780345c/d26357a6) or the loss
    happened on the auto_conflict_resolver path, which never calls it at all.

    This gate is content-based: it diffs the rebased candidate against the CURRENT base and
    fails on a function/class that base has but the candidate lost or stubbed, on any new
    undefined name, on a deleted lockfile/CI config, and on unexplained mass deletion.

    FAIL-CLOSED: an import error, a guard crash, or an unreadable tree all return False.
    Opt out only with ORCH_MERGE_REGRESSION_GUARD=false.
    """
    if os.environ.get("ORCH_MERGE_REGRESSION_GUARD", "true").strip().lower() in (
            "0", "false", "no", "off"):
        return True, "regression guard disabled by ORCH_MERGE_REGRESSION_GUARD"
    try:
        import regression_guard
    except Exception as exc:
        return False, (f"regression guard unavailable (fail-closed): "
                       f"{type(exc).__name__}: {exc}")
    try:
        msg = _git(repo, "log", "--format=%s%n%b", f"{base}..{branch}", timeout=60).stdout or ""
    except Exception:
        msg = ""
    try:
        return regression_guard.gate(repo, base, candidate_sha or branch, commit_message=msg)
    except Exception as exc:
        return False, f"regression guard error (fail-closed): {type(exc).__name__}: {exc}"


def _divergent_gate(repo, base, branch):
    """PRE-merge divergent-authorship gate (2026-08-02). Returns (ok, detail).

    _regression_gate above compares the merge RESULT against the base, which cannot see the
    add/add shape: when neither the base nor anything before it contained the file, both
    sides authored it from scratch and there is no "lost symbol relative to base" to find.
    That is exactly how 71cfd4ca6 dropped CANARY_ENABLED/CANARY_PERCENT from
    gpt1_canary_router.py while every base-vs-result check stayed green.

    This gate runs on the two SIDES before any resolution and routes divergent files to a
    namespacing/manual path instead of letting --ours/--theirs/--union guess.

    FAIL-CLOSED: an import error or a guard crash returns False.
    Opt out only with ORCH_DIVERGENT_GUARD_ENABLED=false.
    """
    if os.environ.get("ORCH_MERGE_DIVERGENT_GATE", "true").strip().lower() in (
            "0", "false", "no", "off"):
        return True, "divergent guard disabled by ORCH_MERGE_DIVERGENT_GATE"
    try:
        import divergent_authorship_guard
    except Exception as exc:
        return False, (f"divergent authorship guard unavailable (fail-closed): "
                       f"{type(exc).__name__}: {exc}")
    try:
        return divergent_authorship_guard.gate(repo, base, branch)
    except Exception as exc:
        return False, f"divergent authorship guard error (fail-closed): {type(exc).__name__}: {exc}"


def _stub_gate(repo, proj, base, branch):
    """MERGE-path stub gate (2026-08-02). Returns (ok, detail).

    stub_guard has existed as a PERIODIC sweep only, so the 206 shadowed re-exports it can
    detect were free to merge and were caught (if at all) hours later by the next sweep. A
    barrel that adds `export const assertEcpCounterparty = () => ({})` next to
    `export * from './real'` compiles, tests green, and silently disables a regulatory gate
    the moment it lands. A periodic scan is a report; only a gate is a guarantee.

    FAIL-CLOSED: an import error or a guard crash returns False.
    Opt out only with ORCH_MERGE_STUB_GATE=false / ORCH_STUB_GUARD_ENABLED=false.
    """
    if os.environ.get("ORCH_MERGE_STUB_GATE", "true").strip().lower() in (
            "0", "false", "no", "off"):
        return True, "stub gate disabled by ORCH_MERGE_STUB_GATE"
    try:
        import stub_guard
    except Exception as exc:
        return False, f"stub guard unavailable (fail-closed): {type(exc).__name__}: {exc}"
    try:
        result = stub_guard.check_repo(repo, branch, (proj or {}).get("name"), base=base)
    except Exception as exc:
        return False, f"stub guard error (fail-closed): {type(exc).__name__}: {exc}"
    if result.get("skipped"):
        return True, f"stub gate: {result['skipped']}"
    blocking = [v for v in result.get("violations", []) if v.get("severity") == "block"]
    if not blocking:
        return True, f"stub gate clean ({result.get('files', 0)} file(s))"
    if stub_guard.BREAK_GLASS:
        return True, "stub gate BREAK-GLASS override (ORCH_STUB_GUARD_BREAK_GLASS)"
    detail = " | ".join("[%s] %s%s: %s" % (v["code"], v.get("path"),
                                           ("::" + v["symbol"]) if v.get("symbol") else "",
                                           v.get("detail", ""))
                        for v in blocking[:8])
    if len(blocking) > 8:
        detail += f" | ... and {len(blocking) - 8} more"
    return False, detail


def _quarantine_regression_failure(repo, card, slug, task, pname, branch, base, detail, t0=None):
    """Park ONE candidate that would DESTROY code in base; the train continues.

    Mirrors _quarantine_build_failure's shape exactly so the existing remediation fleet can
    act on it: 'regressfail' rows carry the specific findings in the note (file::symbol +
    reason) so remediation bots can restore the exact symbols instead of guessing. Never
    falls through to a merge — nothing below the call site runs for a red candidate.
    """
    head = ("integrate REGRESSFAIL — merge would DELETE or STUB code that exists in "
            f"{base}; restore the named symbols before merging. branch={branch} base={base} "
            "(merge-train regression guard; NOT merged, NOT pushed)")
    tail = (detail or "")[-1200:]
    tr = int(task.get("transient_retries") or 0)
    cap = int(os.environ.get("MERGE_REGRESSION_REDO_CAP", "2"))
    state = "QUARANTINED"
    if tr < cap:
        try:
            patch = agentic_repair.repair_patch(
                task, f"{head}\n{tail}", category="regressfail",
                directive=("Re-apply your change on top of the CURRENT base WITHOUT removing "
                           "or stubbing any existing function, class, method, lockfile or CI "
                           "config. Restore every symbol named in the findings above with its "
                           "full original body, keep your own new code, then run the tests."))
        except Exception:
            patch = {"state": "QUEUED", "account": None, "updated_at": "now()"}
        patch["transient_retries"] = tr + 1
        patch["note"] = f"{head} [regression-quarantine {tr + 1}/{cap}] {tail}"[:1800]
        state = f"repair {tr + 1}/{cap}"
    else:
        patch = {"state": "QUARANTINED", "account": None, "updated_at": "now()",
                 "note": (f"merge-train-regression-guard: quarantined as regressfail after {cap} "
                          f"repair attempts. {head} Findings: {tail}")[:900]}
    try:
        _task_patch(task, patch)
    except Exception:
        try:
            _task_patch(task, {"state": "BLOCKED", "account": None, "updated_at": "now()",
                               "note": patch.get("note", head)[:900]})
        except Exception:
            pass
    try:
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:REGRESSFAIL"})
    except Exception:
        pass
    _attribute_train_outcome(slug, task, "regressfail", integrated=False)
    try:
        import json as _json, time as _time
        db.insert("coordination_tasks", {"task_type": "merge_regression_blocked",
            "payload": _json.dumps({"at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                                    "slug": slug, "branch": branch, "base": base,
                                    "findings": (detail or "")[:2000]})[:4000]}, upsert=False)
    except Exception:
        pass
    if _pm:
        try:
            _pm.record(slug, task.get("kind") or "unknown", ok=False,
                       duration_ms=int((time.monotonic() - t0) * 1000) if t0 else 0,
                       gate_decision="REGRESSFAIL", gate_reason=(detail or "")[:200])
        except Exception:
            pass
    _log(pname, slug, "REGRESSFAIL", f"{state}; {(detail or '')[:120]}")
    return "regressfail"


def _rebase_onto_base(repo, branch, base):
    """Step 2: rebase the branch onto the CURRENT base. Returns (ok, conflict_detail).
    Frees any leftover agent worktree first (approval_merge._free_branch — git refuses to
    rebase a branch checked out elsewhere, and that error used to be mislabeled CONFLICT).
    conflict_detail is a newline-separated list of conflicting filenames (empty on success),
    captured before --abort so repair directives can name the specific files."""
    approval_merge._free_branch(repo, branch)
    if _git(repo, "merge-base", "--is-ancestor", base, branch).returncode == 0:
        return True, ""  # already based on current base
    if _git(repo, "rebase", base, branch, timeout=300).returncode != 0:
        detail = (_git(repo, "diff", "--name-only", "--diff-filter=U").stdout or "").strip()
        _git(repo, "rebase", "--abort")
        return False, detail
    return True, ""



# (duplicate _run_tests removed 2026-07-31 — runtime always used the later def)

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


def _ensure_node_deps(repo, test_cmd=""):
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
    total_budget = float(os.environ.get("MERGE_TRAIN_NPM_TOTAL_TIMEOUT", "180"))
    per_install_cap = int(os.environ.get("MERGE_TRAIN_NPM_TIMEOUT", "600"))
    deadline = time.monotonic() + total_budget
    # The gate runs in repo unless the command explicitly changes directory or
    # uses npm --prefix. Walking every package in a monorepo hydrated unrelated
    # examples/services and turned one branch check into a 15-minute lock hold.
    roots = [repo]
    for pattern in (r"(?:^|[;&])\s*cd\s+([^\s;&]+)", r"--prefix(?:=|\s+)([^\s;&]+)"):
        for match in re.finditer(pattern, test_cmd or ""):
            candidate = match.group(1).strip("'\"")
            if not os.path.isabs(candidate):
                candidate = os.path.join(repo, candidate)
            if os.path.isdir(candidate):
                roots.append(candidate)
    roots = list(dict.fromkeys(os.path.realpath(root) for root in roots))
    try:
        for root in roots:
            if (os.path.isfile(os.path.join(root, "package.json"))
                    and not os.path.isdir(os.path.join(root, "node_modules"))):
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
        try:
            import commit_overlay
            with commit_overlay.checkout(repo, ref, prefix="merge-qa-overlay-") as overlay:
                candidate = overlay["path"]
                for shared in ("node_modules",):
                    src, dst = os.path.join(repo, shared), os.path.join(candidate, shared)
                    if os.path.exists(src) and not os.path.exists(dst):
                        try:
                            os.symlink(src, dst)
                        except OSError:
                            pass
                ok, detail = _run_tests(candidate, test_cmd)
                return ok, f"overlay:{overlay['commit'][:12]} {detail}"
        except Exception as exc:
            return False, f"could not create branch-exact QA overlay: {exc}"
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
        _ensure_node_deps(repo, test_cmd)
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


# ── production build gate (FAIL-CLOSED) ──────────────────────────────────────────────
#
# 2026-08-02: the train merged and PUSHED code that had never been compiled. The only
# pre-merge check was _test_cmd_for(), which returns `npm test` for any repo with a root
# package.json — so on every Next/Nuxt app the PRODUCTION BUILD never ran before the base
# was fast-forwarded and pushed to origin. 19,262 merged tasks against 90 successful
# releases (and the permanent stream of red Vercel deploys) came out of exactly this hole.
#
# Everything below is deliberately FAIL-CLOSED. build_gate.run_build() itself fail-OPENS on
# an empty command (`if not build_cmd: return True, "no build_cmd (skipped)"`), so the
# command must be resolved and validated HERE, before run_build is ever called. An
# undeterminable build command, a failed import, or any exception raised inside run_build
# is a BUILD FAILURE — never a pass. That is the exact inversion of the old behaviour.
#
# Gate ORDER in _integrate_card: (2c) content regression guard -> (3) tests -> (3b) THIS
# build gate -> (4) fast-forward -> (5) push. Cheapest gate first; the build is the most
# expensive check we run, so it only ever sees candidates that already passed the others.

def _build_gate_enabled():
    """Read at call time so a fleet_config/env change takes effect without a restart."""
    return _truthy("ORCH_MERGE_BUILD_GATE", True)


def _build_timeout():
    try:
        return int(os.environ.get("MERGE_TRAIN_BUILD_TIMEOUT", "900"))
    except ValueError:
        return 900


def _build_cmd_for(proj, repo):
    """Resolve the project's REAL production build command.

    Deliberately does NOT reuse _test_cmd_for(): that helper falls back to TEST_CMD
    ('npm test'), which is precisely what made the old gate meaningless. Order is
    build_gate.build_cmd_for() (project row `build_cmd` reconciled with detection, and
    persisted back onto the project) then a bare detect_build_cmd() if the DB write path
    is unavailable. Returns '' when nothing can be determined — the caller treats that as
    FAILURE, not as "nothing to do".
    """
    try:
        import build_gate
    except Exception:
        return ""
    try:
        cmd = build_gate.build_cmd_for(proj, repo)
        if cmd:
            return str(cmd).strip()
    except Exception:
        pass  # DB unavailable / no build_cmd column — fall back to pure detection
    try:
        return str(build_gate.detect_build_cmd(repo) or "").strip()
    except Exception:
        return ""


def _built_or_run(repo, commit, build_cmd, kind="merge-build"):
    """Build an exact commit, reusing a durable proof when one exists.

    Mirrors _verified_or_run()'s proof_graph cache (commit + dependency fingerprint +
    command + kind) so an unchanged SHA is not rebuilt on every train pass. kind defaults
    to 'merge-build' so build proofs can never alias the 'merge-qa' test proofs.
    Only GREEN results are recorded; failures are never cached.
    """
    import build_gate
    cacheable = bool(re.fullmatch(r"[0-9a-fA-F]{40,64}", str(commit or "")))
    if cacheable:
        try:
            import proof_graph
            if proof_graph.reusable_verification(repo, commit, build_cmd, kind):
                return True, "reused exact commit/dependency build proof"
        except Exception:
            pass
    ok, log = build_gate.run_build(repo, commit, build_cmd, timeout=_build_timeout())
    if ok and cacheable:
        try:
            import proof_graph
            proof_graph.record_verification(repo, commit, build_cmd, kind, True)
        except Exception:
            pass
    return ok, log


def _build_gate(repo, proj, branch, candidate_sha):
    """Run the production build on the candidate. Returns (ok, detail).

    FAIL-CLOSED: every path that is not a proven-green build returns False.
    """
    if not _build_gate_enabled():
        # Explicit operator opt-out only (ORCH_MERGE_BUILD_GATE=false). Default is ENABLED.
        return True, "build gate disabled by ORCH_MERGE_BUILD_GATE"
    build_cmd = _build_cmd_for(proj, repo)
    if not build_cmd:
        # NOT a pass. run_build() would return (True, "no build_cmd (skipped)") here; that
        # silent skip is the fail-open this gate exists to remove.
        return False, ("no production build command could be determined for this repo "
                       "(set projects.build_cmd, a package.json build script, vercel.json "
                       "buildCommand, or DEFAULT_BUILD_CMD) — fail-closed, not skipped")
    try:
        ok, log = _built_or_run(repo, candidate_sha or branch, build_cmd)
    except Exception as exc:
        # An exception is a FAILURE. release_train.py used to `except Exception: pass` here
        # and release anyway; the train must never do that.
        return False, f"$ {build_cmd}\nbuild gate error (fail-closed): {type(exc).__name__}: {exc}"
    if ok:
        return True, f"build green: {build_cmd} ({str(log or '')[:120]})"
    # Same tail convention as _run_tests(): last 6000 chars of the captured output.
    return False, f"$ {build_cmd}\n{(log or '').strip()[-6000:]}"


def _quarantine_build_failure(repo, card, slug, task, pname, branch, base, detail, t0=None):
    """Park ONE build-red candidate; the train continues with the next card/project.

    Reuses the fleet's existing quarantine mechanism: 'buildfail' is a repairable category
    (blocker_quarantine.classify -> 'buildfail' -> _repair_original), so under the redo cap
    the SAME task/branch is re-queued through agentic_repair with the build log attached —
    that is what auto_remediate/build_fixer key off. Past the cap the row is parked in the
    terminal QUARANTINED state with blocker_quarantine's note shape. The note always opens
    with runner.py's canonical 'integrate BUILDFAIL — production build red' marker so the
    existing remediation regexes (auto_remediate._ENV_BUILDFAIL, postmortem._BUILD_FAIL,
    blocker_quarantine._BUILD) match it.
    """
    head = ("integrate BUILDFAIL — production build red; fix build/type errors before merge. "
            f"branch={branch} base={base} (merge-train build gate; NOT merged, NOT pushed)")
    tail = (detail or "")[-1200:]
    tr = int(task.get("transient_retries") or 0)
    cap = int(os.environ.get("MERGE_BUILD_REDO_CAP", "2"))
    state = "QUARANTINED"
    if tr < cap:
        try:
            patch = agentic_repair.repair_patch(
                task, f"{head}\n{tail}", category="buildfail",
                directive=("Make the production build pass on this SAME branch with the smallest "
                           "possible change (types/imports/config). Do not add features. Run the "
                           "project's real build command locally and confirm it exits 0 before "
                           "committing."))
        except Exception:
            patch = {"state": "QUEUED", "account": None, "updated_at": "now()"}
        patch["transient_retries"] = tr + 1
        patch["note"] = f"{head} [build-quarantine {tr + 1}/{cap}] {tail}"[:1800]
        state = f"repair {tr + 1}/{cap}"
    else:
        patch = {"state": "QUARANTINED", "account": None, "updated_at": "now()",
                 "note": (f"merge-train-build-gate: quarantined as buildfail after {cap} build "
                          f"repair attempts. {head} Original blocker: {tail}")[:900]}
    try:
        _task_patch(task, patch)
    except Exception:
        # QUARANTINED may be rejected by a stricter schema — park as BLOCKED instead, which
        # blocker_quarantine._candidate_rows() also picks up. Never fall through to a merge.
        try:
            _task_patch(task, {"state": "BLOCKED", "account": None, "updated_at": "now()",
                               "note": patch.get("note", head)[:900]})
        except Exception:
            pass
    try:
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:BUILDFAIL"})
    except Exception:
        pass
    _attribute_train_outcome(slug, task, "buildfail", integrated=False)
    if _pm:
        try:
            _pm.record(slug, task.get("kind") or "unknown", ok=False,
                       duration_ms=int((time.monotonic() - t0) * 1000) if t0 else 0,
                       gate_decision="BUILDFAIL", gate_reason=(detail or "")[:200])
        except Exception:
            pass
    _log(pname, slug, "BUILDFAIL", f"{state}; {(detail or '')[:120]}")
    return "buildfail"


def _verified_or_run(repo, commit, command, kind="merge-qa"):
    """Resume exact-commit QA from a durable dependency-addressed proof.

    A train may be interrupted after an expensive typecheck succeeds but before
    the branch fast-forwards. Persisting the success lets the next owner resume
    at the integration step without rerunning the same command. Failed or
    mismatched commit/dependency proofs are never reused.
    """
    if not command:
        return True, "no test_cmd configured"
    import re
    cacheable = bool(re.fullmatch(r"[0-9a-fA-F]{40,64}", str(commit or "")))
    try:
        import proof_graph
        if cacheable and proof_graph.reusable_verification(repo, commit, command, kind):
            return True, "reused exact commit/dependency verification proof"
    except Exception:
        proof_graph = None
    ok, tail = _run_tests(repo, command, commit)
    if ok and cacheable:
        try:
            import proof_graph
            proof_graph.record_verification(repo, commit, command, kind, True)
        except Exception:
            pass
    return ok, tail


def _commit_identity(repo, ref):
    """Resolve a ref without making mocked/non-local test repositories fatal."""
    try:
        resolved = _git(repo, "rev-parse", ref).stdout.strip()
        return resolved or ref
    except (OSError, subprocess.SubprocessError):
        return ref


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
    """Step 5: push only when explicitly enabled. Returns '' or an error tail.

    On a non-fast-forward rejection (origin moved while we merged — e.g. the other Mac pushed),
    reconcile once in an ISOLATED worktree: fetch origin/base, rebase local base's extra commits
    onto it, retry the push. Still failing -> return the error; the CALLER must NOT mark the task
    MERGED (a failed push previously counted as a merge and desynced the DB from GitHub)."""
    if os.environ.get("ORCH_PUSH_ON_MERGE", "false").lower() != "true":
        return ""
    # Ensure auth before push — the PAT may not have been injected yet if
    # task_refs.publish() hasn't run for this repo in this process.
    # Root cause of "Not logged in · Please run /login" failures.
    try:
        import task_refs
        task_refs._ensure_auth(repo)
    except Exception:
        pass  # best-effort; push will fail with a clear error if auth is missing
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


def _verify_push(repo, base):
    """Contract guarantee: verify origin/{base} matches local {base} after push.

    Returns '' on success, error string if the remote ref does not match.
    This prevents the DB/GitHub desync observed 2026-07-09 where a task was
    marked MERGED but the push silently failed to advance origin."""
    try:
        local = _git(repo, "rev-parse", base)
        remote = _git(repo, "rev-parse", f"origin/{base}")
        if local.returncode != 0 or remote.returncode != 0:
            return "VERIFY:rev-parse-failed"
        local_sha = (local.stdout or "").strip()
        remote_sha = (remote.stdout or "").strip()
        if local_sha and remote_sha and local_sha == remote_sha:
            return ""
        # Stale fetch cache — refetch and recheck once
        _git(repo, "fetch", "origin", base, timeout=60)
        remote2 = _git(repo, "rev-parse", f"origin/{base}")
        remote2_sha = (remote2.stdout or "").strip()
        if local_sha == remote2_sha:
            return ""
        return f"VERIFY:sha-mismatch local={local_sha[:10]} remote={remote2_sha[:10]}"
    except Exception as e:
        return f"VERIFY:exception:{e}"


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


def _delete_branch(repo, branch, reason="merge-train redo"):
    """Free the branch NAME for a clean rebuild without destroying its COMMITS.

    FIX 2026-08-04 (cowork audit): both call sites are redo-on-conflict paths — a rebase
    conflict or a base that refused to fast-forward. Neither means the work is worthless,
    but this used to `branch -D` AND `push origin --delete`, which removed the durable copy
    that runner._durable_share_branch() had just created at commit time. Committed work
    then existed nowhere, and the orchestrator filed a recover-missing-branch-<slug> task to
    generate it again from scratch (3,332 such tasks, 23.6% of all output).

    branch_durability.safe_delete archives the tip under refs/archive/ first, so the redo
    still gets a clean branch name while the original commits stay recoverable by sha.
    """
    try:
        import branch_durability
        branch_durability.safe_delete(repo, branch, reason=reason, delete_remote=True)
        return
    except Exception as exc:
        # Fail SAFE, not closed: if the guard is unavailable, keep the branch rather than
        # fall back to the destructive path. A stuck branch is recoverable; deleted work is not.
        print(f"[merge_train] branch durability guard unavailable for {branch} "
              f"({type(exc).__name__}: {exc}); NOT deleting")


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
    # cowork fix 2026-08-02: sentinel train_guard reads the FILE mtime, but the DB
    # upsert above succeeds, so the file never updated -> perpetual false train-stale.
    try:
        _pf = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".runtime", "merge_train_pressure.json")
        with open(_pf, "w") as _f:
            json.dump(payload, _f, indent=2)
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


def _is_relfix(slug):
    """True when the slug belongs to a release-fix family."""
    return str(slug or "").startswith(_RELFIX_PREFIXES)


def _bounded_contract_review(repo, base, dependents, project):
    """Run advisory model review outside the train process with a hard deadline.

    Local inference can occasionally ignore a socket-level timeout while loading
    or evaluating a model.  Keeping it in-process then strands the global merge
    lease.  A separate client process can be terminated safely; rebase and test
    gates remain in the parent and are never bypassed.
    """
    try:
        timeout = max(1, int(os.environ.get("ORCH_TRAIN_CONTRACT_VERIFY_TIMEOUT", "120")))
    except ValueError:
        timeout = 120
    runner_dir = os.path.dirname(os.path.abspath(__file__))
    payload = json.dumps({"repo": repo, "base": base,
                          "dependents": dependents, "project": project})
    script = (
        "import json,sys; sys.path.insert(0,sys.argv[1]); import verify; "
        "p=json.loads(sys.argv[2]); "
        "print(json.dumps(verify.review_diff(p['repo'], base=p['base'], "
        "dependents=p.get('dependents'), project=p.get('project'))))"
    )
    try:
        run = subprocess.run([sys.executable, "-c", script, runner_dir, payload],
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"contract review timed out after {timeout}s"
    if run.returncode:
        return None, (run.stderr or run.stdout or "contract review worker failed")[-300:]
    try:
        return json.loads(run.stdout.strip()), ""
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, "contract review worker returned invalid JSON"


def _verify_contract(repo, branch, base, slug, task, project_name):
    """Contract-first verification gate: cheap-model diff review BEFORE test execution.

    The runner applies verify.review_diff() before integration for tasks it executes
    itself, but the merge train previously skipped this step entirely -- branches that
    were approved and queued for the train landed without any diff-level safety review.
    Release fixes (relfix-*, qafix-*, etc.) are especially risky because they are
    high-priority, auto-approved, and target production-blocking issues, so an unsafe
    diff can reach production faster than normal work.

    This gate runs verify.review_diff() on the rebased branch BEFORE tests. A "fail"
    verdict blocks the merge (same as a TESTFAIL) and routes the task for rework.

    Gated by ORCH_TRAIN_CONTRACT_VERIFY (default "true"). When the env var
    ORCH_TRAIN_CONTRACT_VERIFY_RELFIX_ONLY is "true" (default), only release-fix
    slugs are verified; set to "false" to verify every branch in the train.

    Fail-soft: any error during verification is logged and treated as a pass so
    that verify infrastructure outages never block the merge train.
    """
    if not _truthy("ORCH_TRAIN_CONTRACT_VERIFY", default=True):
        return True, ""
    relfix_only = _truthy("ORCH_TRAIN_CONTRACT_VERIFY_RELFIX_ONLY", default=True)
    if relfix_only and not _is_relfix(slug):
        return True, ""
    if _verify_mod is None:
        return True, "verify module unavailable"
    try:
        # Collect blast-radius dependents for the verify prompt (same as runner.py)
        dependents = None
        try:
            import blast_radius
            dependents = blast_radius.dependents(repo, branch, base)
        except Exception:
            pass
        result, worker_error = _bounded_contract_review(
            repo, base, dependents, project_name,
        )
        if result is None:
            _log(project_name, slug, "CONTRACT_VERIFY:ERROR", worker_error[:120])
            return True, f"verify error (fail-soft pass): {worker_error}"
        verdict = str(result.get("verdict", "pass")).lower()
        notes = str(result.get("notes", ""))[:300]
        reviewer = result.get("by", "unknown")
        _log(project_name, slug, f"CONTRACT_VERIFY:{verdict.upper()}", f"by {reviewer}: {notes[:120]}")
        if verdict.startswith("fail"):
            return False, f"contract verify failed ({reviewer}): {notes}"
        return True, f"contract verify passed ({reviewer})"
    except Exception as e:
        # Fail-soft: verification infra errors must not block the train
        _log(project_name, slug, "CONTRACT_VERIFY:ERROR", str(e)[:120])
        return True, f"verify error (fail-soft pass): {e}"


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
    # FIX 2026-07-28: value_scores was referenced but never defined (latent NameError on the
    # integration path). Build it from value_router.estimate_value, fail-soft to 0 so a scoring
    # error can never stall the train — ordering degrades to (risk band, age) which is safe.
    value_scores = {}
    try:
        import value_router
        for card, slug, task, _risk in annotated:
            key = str(task.get("id") or task.get("slug") or "")
            try:
                value_scores[key] = float(value_router.estimate_value(task) or 0)
            except Exception:
                value_scores[key] = 0.0
    except Exception:
        value_scores = {}
    annotated.sort(key=lambda e: ({"low": 0, "standard": 1, "sensitive": 2}[e[3]],
                                  -value_scores.get(str(e[2].get("id") or e[2].get("slug") or ""), 0),
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
    _t0 = time.monotonic()  # RESTORED 2026-07-31: _dur_ms timing base
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
        # Add diagnostic logging for missing branch issue
        print(f"DIAGNOSTIC: Missing branch {branch} after {cap} rebuild attempts in project {pname}")
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

    _orig_fork = _git(repo, "merge-base", branch, base).stdout.strip()  # pre-rebase fork point
    rebase_ok, conflict_detail = _rebase_onto_base(repo, branch, base)  # (2)
    if not rebase_ok:
        # redo-on-fresh-base: a stale branch conflicting with the advanced base should be REBUILT
        # on the new base, not rot as CONFLICT (that's what stalled the queue before).
        tr = int(task.get("transient_retries") or 0)
        cap = int(os.environ.get("MERGE_CONFLICT_REDO_CAP", "2"))
        files_hint = (f" Conflicting files: {conflict_detail}." if conflict_detail else "")
        if tr < cap:
            _delete_branch(repo, branch)
            patch = agentic_repair.repair_patch(
                task, f"train: rebase conflict on {branch} against {base}.{files_hint}",
                category="conflict",
                directive=(f"Rebuild the same task on fresh {base}, resolve the conflict in "
                           f"code, run tests, and commit.{files_hint}"))
            patch["transient_retries"] = tr + 1
            _task_patch(task, patch)
            db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:redo"})
            _log(pname, slug, "REDO", f"rebase conflict{files_hint}, rebuild on fresh {base} ({tr+1}/{cap})")
            return "redo"
        _task_patch(task, {"state": "CONFLICT",
                           "note": f"train: still conflicts after {cap} redos - needs manual rebase.{files_hint}"})
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:conflict-exhausted"})
        _attribute_train_outcome(slug, task, "conflict", integrated=False)
        _log(pname, slug, "CONFLICT", f"redo cap {cap} exhausted{files_hint}")
        return "conflict"

    test_cmd = _test_cmd_for(proj, repo)
    candidate_sha = _commit_identity(repo, branch)
    reg_ok, reg_detail = _post_fork_regression(repo, branch, base, _orig_fork)
    if not reg_ok:
        _task_patch(task, {"state": "BLOCKED",
                           "note": ("train: REGRESSION-RISK — clean rebase deletes recently-merged improvements: " + reg_detail)[:480]})
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:REGRESSION-RISK"})
        _log(pname, slug, "BLOCKED", f"regression-risk: {reg_detail[:120]}")
        try:
            import json as _json, time as _time
            db.insert("coordination_tasks", {"task_type": "merge_regression_risk",
                "payload": _json.dumps({"at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                                        "slug": slug, "detail": reg_detail[:800]})[:4000]}, upsert=False)
        except Exception:
            pass
        return "regression-risk"

    # (2c) CONTENT REGRESSION GATE — fail-closed, runs BEFORE tests, BEFORE any build gate,
    # and long BEFORE the base moves (4) or anything is pushed (5). Cheapest real gate we
    # have (AST + pyflakes over changed files only), so it runs first. Green tests are not
    # evidence that nothing was LOST: a merge that replaces _branch_exists_anywhere() with
    # `return False` passes every test suite and silently does the wrong thing forever.
    # Nothing below this line executes for a candidate that would destroy code in base.
    reg_gate_ok, reg_gate_detail = _regression_gate(repo, base, branch, candidate_sha)
    if not reg_gate_ok:
        return _quarantine_regression_failure(repo, card, slug, task, pname, branch, base,
                                              reg_gate_detail, _t0)

    # (2d) DIVERGENT-AUTHORSHIP GATE — fail-closed. Covers the one shape (2c) is structurally
    # blind to: both sides AUTHORED the same file, so there is no base version whose loss a
    # base-vs-result diff could detect. 71cfd4ca6 merged green through every result-based
    # check and still dropped two module constants. Quarantines through the same
    # regressfail path so the existing remediation fleet acts on it unchanged.
    div_ok, div_detail = _divergent_gate(repo, base, branch)
    if not div_ok:
        return _quarantine_regression_failure(repo, card, slug, task, pname, branch, base,
                                              "DIVERGENT AUTHORSHIP — " + div_detail, _t0)

    # (2e) STUB GATE — fail-closed. stub_guard was a periodic sweep only, so a barrel that
    # shadows `export * from './real'` with a local constant-return stub merged freely and
    # was reported hours later, if at all. 206 such instances landed this way; the ones that
    # mattered silently disabled regulatory gates (assertEcpCounterparty stopped throwing)
    # and zeroed financial functions. Now it blocks at merge time.
    stub_ok, stub_detail = _stub_gate(repo, proj, base, branch)
    if not stub_ok:
        return _quarantine_regression_failure(repo, card, slug, task, pname, branch, base,
                                              "SILENT STUB / SHADOWED RE-EXPORT — " + stub_detail,
                                              _t0)

    ok, tail = _verified_or_run(repo, candidate_sha, test_cmd)  # (3) branch-exact and resumable
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
        if _pm:
            try:
                _pm.record(slug, task.get("kind") or "unknown",
                           ok=False, duration_ms=int((time.monotonic() - _t0) * 1000), gate_decision="TESTFAIL",
                           gate_reason=tail[:200])
            except Exception:
                pass
        # NEVER force-merge red work.
        _task_patch(task, {"state": "TESTFAIL", "note": f"train: tests failed on rebased {branch}: {tail[:200]}"})
        db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:TESTFAIL"})
        _attribute_train_outcome(slug, task, "testfail", integrated=False)
        _log(pname, slug, "TESTFAIL", tail[:120])
        return "testfail"

    # (3b) PRODUCTION BUILD GATE — fail-closed, runs AFTER the (2c) regression guard and
    # AFTER tests (cheapest gate first), and BEFORE the base moves.
    # Green tests are not evidence that the app COMPILES: `npm test` on a Next/Nuxt repo
    # never invokes `next build` / `nuxi build`, which is why build-red code merged and
    # pushed for months. Nothing below this line executes for a red candidate — no
    # fast-forward (4), no push (5), no MERGED (6). A failure quarantines this one card
    # and returns, so the train moves on to the next card/project instead of halting.
    build_ok, build_detail = _build_gate(repo, proj, branch, candidate_sha)
    if not build_ok:
        return _quarantine_build_failure(repo, card, slug, task, pname, branch, base,
                                         build_detail, _t0)

    current_candidate_sha = _commit_identity(repo, branch)
    if current_candidate_sha != candidate_sha:
        _task_patch(task, {"state": "DONE", "note": f"train: candidate advanced during QA {candidate_sha[:12]} -> {current_candidate_sha[:12]}; rerun exact new snapshot"})
        _log(pname, slug, "SNAPSHOT-CHANGED", f"{candidate_sha[:12]} -> {current_candidate_sha[:12]}; no ref advance")
        return "snapshot-changed"

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

    # (5b) CONTRACT GUARANTEE: verify origin actually advanced before marking MERGED.
    # Prevents DB/GitHub desync where push returned 0 but origin didn't move
    # (e.g. partial network failure, auth token expiry mid-push).
    verify_err = _verify_push(repo, base)
    if verify_err:
        _task_patch(task, {"state": "DONE",
                           "note": f"train: push returned ok but verify failed ({verify_err})"})
        _attribute_train_outcome(slug, task, "push-verify-failed", integrated=False)
        _log(pname, slug, "PUSH-VERIFY-FAILED", verify_err[:120])
        return "push-pending"

    _task_patch(task, {"state": "MERGED", "note": f"train: MERGED into {base}"})  # (6)
    db.update("approvals", {"id": card["id"]}, {"decided_by": f"{MARK}:MERGED"})
    _attribute_merge_outcome(slug, task)
    _attribute_train_outcome(slug, task, "merged", integrated=True)
    if _pm:
        try:
            _pm.record(slug, task.get("kind") or "unknown",
                       ok=True, duration_ms=int((time.monotonic() - _t0) * 1000), gate_decision="MERGED")
        except Exception:
            pass
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
    """Entry point: run the integration train across all projects (serialized per project).

    Returns a summary dict with keys:
        projects  (int)  — number of projects processed
        merged    (int)  — branches successfully fast-forwarded into base
        redo      (int)  — branches re-queued due to stale-base rebase conflicts
        testfail  (int)  — branches whose tests failed after rebase
        buildfail (int)  — branches whose PRODUCTION BUILD was red (quarantined, never merged)
        conflict  (int)  — branches with unresolvable merge conflicts
        skipped   (int)  — branches skipped (cap reached or repo locked)
        risk      (dict) — counts by risk tier: low / standard / sensitive
        pressure  (dict) — per-project queue pressure snapshot
        paused    (bool) — present and True when the train is paused via fleet_config
    """
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
               "redo": 0, "testfail": 0, "regressfail": 0, "buildfail": 0, "conflict": 0,
               "skipped": 0, "project_errors": 0,
               "risk": {"low": 0, "standard": 0, "sensitive": 0},
               "pressure": pressure}
    caps = {"low": LOW_RISK_BATCH, "standard": STANDARD_BATCH, "sensitive": SENSITIVE_BATCH}
    # 'regressfail' is a real attempt: the candidate was built, rebased and inspected, and it
    # would have destroyed code in base. It consumes the cap exactly like testfail.
    # 'buildfail' likewise — a red production build is the most expensive attempt we make, so
    # it must consume the cap or one perpetually build-red project burns the whole cycle.
    ATTEMPT_OUTCOMES = ("merged", "testfail", "regressfail", "buildfail", "conflict")
    scan_cap = int(os.environ.get("MERGE_TRAIN_SCAN_PER_PROJECT", "200"))
    # FIX 2026-07-29 (re-applied — first attempt was wiped by the fleet's own stash/reset before
    # it could be committed): this block was a half-landed refactor — a bare `for` loop holding
    # per-project logic that referenced an undefined `result` and returned mid-loop, while
    # process_project_isolated() below called a process_project() that did not exist. Restored the
    # intended shape: a per-project worker returning its own result dict, run by the executor below.
    def process_project(item):
        pid, group = item
        proj = projects.get(pid, {})
        result = {"projects": 1, "merged": 0, "already_integrated": 0,
                  "redo": 0, "testfail": 0, "regressfail": 0, "buildfail": 0, "conflict": 0,
                  "skipped": 0, "project_errors": 0,
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
        # FIX 2026-07-28: repo_lock.hold() takes (repo, timeout) only — the stray priority=True
        # kwarg was a second latent crash behind the missing import.
        with repo_lock.hold(repo_path, timeout=300) as got_lock:
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
                        elif outcome == "regressfail":
                            result["regressfail"] += 1
                        elif outcome == "buildfail":
                            result["buildfail"] += 1
                        elif outcome == "conflict":
                            result["conflict"] += 1
                        else:
                            result["skipped"] += 1
            except integration_runtime.IntegrationRuntimeError as exc:
                result["skipped"] += len(group)
                print(f"merge_train: {proj.get('name') or pid} isolation blocked: {exc}")
            except FileNotFoundError as exc:
                # A concurrent/killed pass removed a worktree dir mid-flight.
                # Transient by construction — the entry-time `worktree prune`
                # heals it next pass. Skip, don't error (2026-07-31 class).
                result["skipped"] += len(group)
                print(f"merge_train: {proj.get('name') or pid} worktree vanished mid-pass "
                      f"(transient, will heal next pass): {exc}")
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
            # 2026-07-31: a swallowed per-project exception hid the NameError
            # that froze ALL releases for 3 days. Project errors now file a
            # coordination alert carrying the actual exception text — silent
            # only ever means healthy.
            try:
                import json as _json, time as _time
                db.insert("coordination_tasks", {
                    "task_type": "merge_train_project_error",
                    "payload": _json.dumps({
                        "at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                        "project": pname, "error": f"{type(exc).__name__}: {str(exc)[:800]}",
                        "cards_skipped": len(group)})[:8000]}, upsert=False)
            except Exception:
                pass
            return {"projects": 1, "merged": 0, "already_integrated": 0,
                    "redo": 0, "testfail": 0, "regressfail": 0, "buildfail": 0, "conflict": 0,
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
                        "testfail", "regressfail", "buildfail", "conflict", "skipped",
                        "project_errors"):
                summary[key] += result.get(key, 0)
            for risk, count in result["risk"].items():
                summary["risk"][risk] += count
    # AUTO-CONFLICT RESOLVER: second pass on branches that conflicted
    auto_resolved = 0
    if summary.get("conflict", 0) > 0:
        try:
            import auto_conflict_resolver
            for pid, group in by_project.items():
                proj = projects.get(pid, {})
                repo = proj.get("repo_path")
                base = proj.get("base_branch") or proj.get("default_base") or "main"
                if repo and os.path.isdir(repo):
                    acr_result = auto_conflict_resolver.resolve_repo(repo, base)
                    auto_resolved += acr_result.get("auto_resolved", 0)
                    summary["merged"] += acr_result.get("total_merged", 0)
        except Exception as e:
            print(f"merge_train: auto-conflict-resolver error: {e}")
    summary["auto_resolved"] = auto_resolved

    print(f"merge_train: {summary['merged']} merged, {summary['already_integrated']} already, "
          f"{summary['redo']} redo, "
          f"{summary['testfail']} testfail, {summary['regressfail']} regressfail, "
          f"{summary['buildfail']} buildfail, {summary['conflict']} conflict, "
          f"{summary['skipped']} skipped, {summary['project_errors']} project errors "
          f"across {summary['projects']} project(s)"
          f"{f', {auto_resolved} auto-resolved' if auto_resolved else ''}")
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


def _startup_static_gate():
    """Refuse to run a pass whose own code would silently no-op (NameError class)."""
    try:
        import static_sanity
        static_sanity.assert_critical("merge_train")
    except RuntimeError:
        raise
    except Exception:
        pass  # gate tooling itself must never wedge the train


if __name__ == "__main__":
    _startup_static_gate()
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
