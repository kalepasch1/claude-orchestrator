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
import datetime, json, os, re, sys, subprocess, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
# RESTORED 2026-07-31 (overwrite-class recovery; static_sanity gate)
_RELFIX_PREFIXES = ("relfix-", "qafix-", "deployfix-", "buildfix-", "copyfix-")
try:
    import verify as _verify_mod
except Exception:
    _verify_mod = None

import events
import delivery_lease
import shadow_mode
import approval_merge   # reuse _slug_from + _free_branch (the worktree-unlock fix)
import integration_runtime
import paused_host_guard
import agentic_repair
import repo_lock        # FIX 2026-07-28: was used at the per-repo serialization site but never
                        # imported -> every train_run() crashed with NameError before integrating
                        # anything (the silent integration-stall root cause).
import concurrent.futures   # FIX 2026-07-28: used by the multi-project ThreadPoolExecutor path, never imported
import stderr_digest       # keep the CAUSE of a git failure, not its last 160 bytes
import repo_hygiene         # FIX 2026-07-28: used pre-test-run (stray .js cleanup), never imported (fail-soft masked it)
import semantic_merge       # FIX 2026-07-28: used by the auto-merge path, never imported
try:
    import pipeline_metrics as _pm
except Exception:
    _pm = None

def emit(kind, **fields):
    """Public fail-soft event adapter used by integrations and diagnostics.

    THE OTHER HALF OF A MIGRATION (added 2026-08-25). `import events` above has
    been here without a single use, and runner/tests/test_event_stream.py's
    TestMigratedEmitters expects merge_train.emit alongside sentinel.emit and
    resource_governor.emit — both of which are exactly this two-line adapter.
    The import landed and the adapter did not, so the train was the one migrated
    emitter that could not emit, and anything reaching for merge_train.emit got
    AttributeError.
    """
    return events.emit(kind, **fields)


MARK = "train"                                   # decided_by prefix => handled by the train
# Non-code policy decisions are terminal approval artifacts, not merge work.  If
# they are re-read here, the no-slug fallback needlessly churns the queue and can
# make legacy policy cards look like active integrations.
SKIP_PREFIXES = ("merge-handler", "train", "auto-policy")
MERGE_KINDS = ("verify", "material", "integrate")
TEST_CMD = os.environ.get("TEST_CMD", "npm test")
HEALTH_LOOKBACK_MINUTES = 60


def _test_pipeline_health(metrics, lookback_minutes=HEALTH_LOOKBACK_MINUTES):
    """Pass-rate / gate-decision block for the run summary, or None if unavailable.

    None keeps the key out of the summary entirely, which is what the previous
    fail-soft did — a partially-populated health block would be read as real.
    """
    try:
        return metrics.get_health(lookback_minutes=lookback_minutes)
    except Exception:
        return None


#: Seconds a gated suite gets. The old default was 300, shorter than the suite of
#: the largest repo this train gates (~2330s), so every candidate for that repo was
#: rejected on the clock and the rejection read as "tests failed".
TEST_TIMEOUT_DEFAULT = 3600


def _test_timeout():
    """Read at call time so fleet_config changes take effect without restart.

    Fail-soft on a bad value: absent, empty or unparseable means "nobody set this",
    and a non-positive number would reject every candidate instantly, so both fall
    back to the default rather than being taken literally.
    """
    # str(CONSTANT), not "", so scripts/gen_env_example.py can resolve and document
    # the real default; the fail-soft parse below still covers a SET but bad value.
    raw = str(os.environ.get("MERGE_TRAIN_TEST_TIMEOUT",
                             str(TEST_TIMEOUT_DEFAULT))).strip()
    try:
        seconds = int(raw)
    except ValueError:
        return TEST_TIMEOUT_DEFAULT
    return seconds if seconds > 0 else TEST_TIMEOUT_DEFAULT


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

class _NoRepo:
    """Stand-in for a git result when there is no repo to run in."""
    returncode = 128
    stdout = ""
    stderr = "no repo path"


def _git(repo, *args, timeout=60):
    # 2026-09-01: an empty cwd raised FileNotFoundError('') out of subprocess and killed the
    # ENTIRE train pass before a single merge was attempted -- the direct cause of
    # "0 merged ... across 0 project(s)" on every cycle. A missing repo is a per-project
    # condition and must degrade to a failed git call, never take down the pass.
    if not repo or not os.path.isdir(repo):
        return _NoRepo()
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


_REMOTE_AGENT_REFS = {}          # repo -> (expires_at, {branch names}) ; None set == "unknown"
_REMOTE_AGENT_LOCK = threading.Lock()
REMOTE_REF_TTL_S = float(os.environ.get("MERGE_TRAIN_REMOTE_REF_TTL_S", "120"))


def _remote_agent_branch_maybe(repo, branch):
    """True if origin might hold `branch`; False only when we positively know it does not.

    Returns True on any uncertainty (listing failed, cache cold and refresh errored) so the
    caller falls back to its own fetch. Never returns False for a branch origin actually has,
    which is what keeps this an optimisation rather than a merge-skipping filter.
    """
    now = time.monotonic()
    with _REMOTE_AGENT_LOCK:
        entry = _REMOTE_AGENT_REFS.get(repo)
        if entry and entry[0] > now:
            names = entry[1]
            return True if names is None else (branch in names)
    names = None
    try:
        r = _git(repo, "ls-remote", "--heads", "origin", "refs/heads/agent/*", timeout=90)
        if r.returncode == 0:
            names = {line.split("\trefs/heads/", 1)[1].strip()
                     for line in (r.stdout or "").splitlines()
                     if "\trefs/heads/" in line}
    except Exception:
        names = None
    with _REMOTE_AGENT_LOCK:
        _REMOTE_AGENT_REFS[repo] = (time.monotonic() + REMOTE_REF_TTL_S, names)
    return True if names is None else (branch in names)


#: Parsed `git worktree list` per repo: {repo: (expires_monotonic, {branch: sha})}.
#: One listing answers the question for every card in a pass, the same way
#: _REMOTE_AGENT_REFS does for origin. A worktree created mid-pass is picked up on
#: the next pass, which can defer a recovery by one cycle and never skips one.
_WORKTREE_BRANCHES = {}
_WORKTREE_LOCK = threading.Lock()
WORKTREE_LIST_TTL_S = int(os.environ.get("ORCH_MERGE_WORKTREE_TTL_S", "30"))


def _worktree_branch_map(repo):
    """{branch: commit} for every branch a worktree of `repo` has checked out.

    Parses `git worktree list --porcelain`, whose records are

        worktree /path/to/wt
        HEAD <sha>
        branch refs/heads/<name>

    so the HEAD line has to be remembered until the branch line identifies the
    record. Fail-soft: any error yields {}, i.e. "no worktree holds anything",
    which sends the caller on to the remote path it would have taken anyway.
    """
    now = time.monotonic()
    with _WORKTREE_LOCK:
        entry = _WORKTREE_BRANCHES.get(repo)
        if entry and entry[0] > now:
            return entry[1]
    found = {}
    try:
        out = _git(repo, "worktree", "list", "--porcelain", timeout=30)
        if out.returncode == 0:
            head = ""
            for line in (out.stdout or "").splitlines():
                line = line.strip()
                if line.startswith("HEAD "):
                    head = line[len("HEAD "):].strip()
                elif line.startswith("branch refs/heads/"):
                    name = line[len("branch refs/heads/"):].strip()
                    if head:
                        found[name] = head
                    head = ""
                elif not line:
                    head = ""
    except Exception:
        # Cache the empty answer as well: a repo whose worktree listing errors
        # would otherwise re-run the subprocess for every card in the pass.
        with _WORKTREE_LOCK:
            _WORKTREE_BRANCHES[repo] = (time.monotonic() + WORKTREE_LIST_TTL_S, {})
        return {}
    with _WORKTREE_LOCK:
        _WORKTREE_BRANCHES[repo] = (time.monotonic() + WORKTREE_LIST_TTL_S, found)
    return found


def _worktree_commit_for(repo, branch):
    """The commit a worktree has checked out for `branch`, or "" if none does."""
    return _worktree_branch_map(repo).get(branch, "")


def _recover_branch_from_worktree(repo, branch):
    """Re-create a missing local ref from a worktree that still holds the commit.

    STEP 2 WAS DOCUMENTED AND MISSING (restored 2026-08-25). The docstring below
    has always listed worktree recovery as the middle step of the resolution
    order, and runner/tests/test_materialize_branch_worktree.py has always
    asserted it. There was no such code: the function went straight from the
    local-ref check to the remote path.

    That is not a cosmetic gap. The remote path begins with the agent/* ls-remote
    short-circuit, which returns False for any branch origin does not have — and
    a branch that lives only in a local worktree is exactly such a branch. So a
    commit sitting on this machine, reachable with no network at all, produced
    `return False` and the card waited forever for a push that had already been
    superseded by the work being local.
    """
    commit = _worktree_commit_for(repo, branch)
    if not commit:
        return False
    try:
        _git(repo, "branch", branch, commit, timeout=30)
    except Exception:
        return False
    return _branch_exists(repo, branch)


def _recover_branch_from_artifact_commit(repo, branch, task):
    """Recreate a lost agent branch from the commit the task recorded at completion.

    2026-09-01: across the three live projects, 101 tasks sit in DONE and only 10 still
    have an artifact_branch. 79 have NO branch but DO have an artifact_commit -- and a
    sample of 28 found every single one of those commits still present in its repository.
    The work was never lost; only the ref was. _materialize_branch resolved by branch NAME
    alone, so the train saw "branch missing", filed a rebuild task, and eventually gave up
    on finished, reachable work. Checking the recorded commit is a local cat-file, cheaper
    than the remote paths below it, so it runs first.

    Set ORCH_RECOVER_BRANCH_FROM_COMMIT=false to disable.
    """
    if os.environ.get("ORCH_RECOVER_BRANCH_FROM_COMMIT", "true").strip().lower() not in (
            "1", "true", "yes", "on"):
        return False
    sha = str((task or {}).get("artifact_commit") or "").strip()
    if not sha or not repo or not os.path.isdir(repo):
        return False
    if _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        return False          # recorded, but genuinely not in this repo
    if _git(repo, "branch", branch, sha).returncode == 0 or _branch_exists(repo, branch):
        print(f"[branch-recovery] recreated {branch} from recorded artifact_commit "
              f"{sha[:12]} in {repo} — the work was reachable all along", flush=True)
        return True
    return False


def _materialize_branch(repo, branch, task=None):
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
    # Step 2, and it must run BEFORE the agent/* remote short-circuit below:
    # a worktree-held branch that was never pushed is precisely what that
    # short-circuit rejects, and it costs no network to check.
    if _recover_branch_from_worktree(repo, branch):
        return True
    # Cheapest remaining recovery, and the one that unlocks the DONE backlog: the task
    # already told us the commit. Local only — runs before any network path below.
    if _recover_branch_from_artifact_commit(repo, branch, task):
        return True
    # THE TRAIN'S REAL WALL-CLOCK SINK (measured 2026-08-06).
    #
    # Cards get filed by ensure_integration_card as soon as work is approved, which is often
    # BEFORE the agent branch exists — the task is still QUEUED. Every such card reached this
    # line and paid a full `git fetch origin <branch>` (timeout 120s) to discover a ref that
    # was never pushed. In the last 20,000 train lines: 2,096 WAIT outcomes against 1 MERGED,
    # the same slugs re-fetched 60-195 times each. With ORCH_MERGE_TRAIN_MAX_RUNTIME_S=900 the
    # pass was being killed on the not-yet-created cards before it ever reached the mergeable
    # ones. The queue was not stalled on conflicts; it was starved of clock.
    #
    # One `git ls-remote --heads origin refs/heads/agent/*` answers the same question for every
    # card in the pass. Absent from that listing => there is nothing to fetch, so skip straight
    # to WAIT. Fail-soft: if ls-remote errors or times out we fall through to the old per-branch
    # fetch, so the worst case is today's behaviour rather than a missed merge. The cache is
    # per-repo with a short TTL, so a branch pushed mid-pass is simply picked up on the next
    # pass — this can defer a merge by one cycle, never skip or overwrite one.
    if branch.startswith("agent/") and not _remote_agent_branch_maybe(repo, branch):
        return False
    try:
        _git(repo, "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", timeout=120)
        if _git(repo, "rev-parse", "--verify", f"refs/remotes/origin/{branch}").returncode != 0:
            return False
        return _git(repo, "branch", branch, f"refs/remotes/origin/{branch}").returncode == 0 \
            or _branch_exists(repo, branch)
    except Exception:
        return False


def _task_patch(task, patch, repo=None, prod_branch=None):
    """Single write point for task state in the train — so the MERGED gate cannot be bypassed.

    Every MERGED written here must first be proven reachable from the project's integration
    branch (merge_truth). Production reachability is deliberately checked later by the
    release/deployment terminal. A patch that is not MERGED passes straight through. On an
    infrastructure error the gate returns None and we write nothing, leaving the row for the
    next cycle rather than downgrading a real merge because a fetch timed out.
    """
    import merge_truth
    final = merge_truth.gate_merged_patch(task, patch, repo=repo, prod_branch=prod_branch)
    if final is None:
        return None
    db.update("tasks", {"id": task["id"]}, final)
    return final


def _freeze_integration_identity(repo, branch, task, slug):
    """Freeze the post-rebase candidate before any QA or base mutation."""
    import task_refs
    rebased_result = _git(repo, "rev-parse", branch)
    if rebased_result.returncode:
        raise RuntimeError(stderr_digest.digest(rebased_result.stderr, 160)
                           or "rebased commit missing")
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


def _orphan_import_gate(repo, base, branch):
    """Refuse a candidate that adds an import no tracked file can satisfy. (ok, detail)

    apparently's production build was red for five hours on
    `Could not resolve "./kv" from "server/utils/governance.ts"`. governance.ts was committed;
    kv.ts was not — it existed only as untracked dirt on the machine that wrote it. The build
    gate ran in a checkout that HAD the file, so the change was green right up to shipping. The
    defect was not in the diff; it was missing from it.

    Scoped to the files the candidate touches, and only to "./" / "../" specifiers. Every repo
    here carries pre-existing dangling imports in paths no build entry point reaches (17 in
    apparently, 15 in tomorrow, both green), so judging the whole tree would fail every merge on
    inherited noise. Alias forms ("~/", "@/") are excluded because resolving them means guessing
    at srcDir and tsconfig paths — that guess produced 281 findings across four green repos.

    Cheap by design: git plus a regex, no build, no network. Runs before the test and build
    gates rather than after.

    FAIL-OPEN, unlike the regression and stub gates. Those protect against destroying existing
    code, where the cost of a false negative is unrecoverable. This one protects against
    shipping a broken build, which the build gate downstream will also catch — so a crash here
    must not block the queue. Opt out with ORCH_MERGE_ORPHAN_IMPORT_GATE=false.
    """
    if os.environ.get("ORCH_MERGE_ORPHAN_IMPORT_GATE", "true").strip().lower() in (
            "0", "false", "no", "off"):
        return True, "orphan-import gate disabled by ORCH_MERGE_ORPHAN_IMPORT_GATE"
    try:
        import orphan_imports
        changed = _git(repo, "diff", "--name-only", f"{base}...{branch}")
        if changed.returncode:
            return True, "could not diff candidate (gate skipped)"
        touched = {p.strip() for p in (changed.stdout or "").splitlines() if p.strip()}
        if not touched:
            return True, "no files changed"
        found = orphan_imports.dangling_imports(repo, only_files=touched)
        if found:
            return False, orphan_imports.describe(found)
        # Case-colliding paths are the same shape of defect from the other direction: additive,
        # so no deletion- or stub-based guard sees them, and permanently fatal on a
        # case-insensitive filesystem. An auto-resolved merge left racefeed tracking both
        # OPPORTUNITIES.json and opportunities.json; macOS can hold one of them, so git reported
        # the other as modified in every checkout and that integration slot was condemned from
        # the moment the merge landed.
        clashes = orphan_imports.case_collisions(repo, only_files=touched)
        if clashes:
            names = "; ".join(" vs ".join(paths) for _, paths in clashes[:4])
            return False, (f"{len(clashes)} case-colliding path(s) — unusable on a "
                           f"case-insensitive filesystem: {names}")
        return True, "no dangling imports or case collisions in the changed files"
    except Exception as exc:
        return True, f"orphan-import gate unavailable (fail-open): {type(exc).__name__}: {exc}"


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
    _retire_card(card.get("id"), "REGRESSFAIL")
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

        # Capture the branch tip BEFORE anything resets it. This is the conceptual
        # "branch parent" of the resolution and the rollback target; after the
        # `git reset --hard base` below, the branch ref no longer points at the work.
        tip = _git(repo, "rev-parse", "--verify", f"{branch}^{{commit}}")
        if tip.returncode != 0 or not tip.stdout.strip():
            return False
        branch_tip = tip.stdout.strip()

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

            # SILENT-DISCARD GATE (2026-08-06). This is the second producer of
            # "(auto-resolved)" commits, and the semantic merge can legitimately resolve a
            # file to exactly mainline's bytes. When it does, and the branch side carried
            # commits that exist nowhere else, that is not a resolution — it is a deletion
            # wearing a merge's clothes, and nothing downstream can see it (the result IS
            # the mainline blob, so every base-vs-result diff is empty).
            #
            # Note the parents deliberately: the worktree was reset to `base` and the
            # merged content overlaid, so the new commit's git parent is base. The
            # CONCEPTUAL branch parent is branch_tip, captured before the reset — passing
            # the post-reset ref would compare the branch against itself and always pass.
            try:
                import automerge_discard_guard
                ok, detail = automerge_discard_guard.gate(
                    repo, base, branch_tip, result_ref="HEAD", branch=branch)
            except Exception as exc:
                ok, detail = False, (f"automerge discard guard error (fail-closed): "
                                     f"{type(exc).__name__}: {exc}")
            if not ok:
                # Roll the branch back to where it was and let the caller fall through to
                # the existing redo/manual path. The branch is the only copy of the work.
                subprocess.run(["git", "reset", "--hard", branch_tip], cwd=wt,
                               capture_output=True, timeout=30)
                print(f"[train] semantic merge of {branch} REFUSED: {detail}")
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
    # The docstring above says this default is 900s; the code said 180s. 180 is far
    # under a Nuxt `npm ci`, so every install started here timed out and returned
    # with node_modules still absent — silently, because TimeoutExpired just
    # `continue`s. Match the documented contract.
    total_budget = float(os.environ.get("MERGE_TRAIN_NPM_TOTAL_TIMEOUT", "900"))
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


def _primary_checkout_of(repo):
    """The main working tree of `repo`'s git repository, or None.

    An integration worktree is a linked worktree: its `--git-common-dir` is the
    primary checkout's .git. That primary checkout is where a human works, so it
    is the one place in the fleet whose node_modules is reliably warm.
    """
    try:
        result = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--path-format=absolute",
             "--git-common-dir"],
            capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    common = (result.stdout or "").strip()
    if not common.endswith(".git"):
        return None
    primary = os.path.dirname(common)
    return primary if os.path.isdir(primary) and primary != repo else None


def _warm_shared_runtime(repo, candidate):
    """Warm one dependency snapshot and link it in. True when that path worked."""
    try:
        import dependency_prewarm
        dependency_prewarm.ensure_all(repo, reason="merge_train:qa-overlay")
        dependency_prewarm.link_shared_runtime(repo, candidate)
        return True
    except Exception as exc:
        print(f"merge_train: dependency_prewarm unavailable for overlay ({exc}); "
              "falling back to a direct symlink", flush=True)
        return False


def _share_deps_into_overlay(repo, candidate, test_cmd=""):
    """Give the branch-exact QA overlay a usable node_modules. Never raises.

    THE BUG THIS FIXES (2026-08-30)
    -------------------------------
    This used to be a bare `os.symlink(repo/node_modules, candidate/node_modules)`
    guarded by `if os.path.exists(src)`. Integration worktrees are fresh checkouts
    and have NO node_modules, so the guard was false, no link was made, and the
    overlay ran its suite against nothing:

        vitest.config.ts (1:325) [UNRESOLVED_IMPORT] Could not resolve 'vitest/config'

    Every branch reported TESTFAIL. On the first unblocked merge_train pass, 17 of
    25 tomorrow cards "failed tests" — every one of them with that identical line.
    Not one test had run. A gate that cannot start reports the same verdict as a
    gate that ran and found a real defect, which is how three weeks of stranded
    work looked like three weeks of bad work.

    `_ensure_node_deps` did not save it either: the recursive call reaches it with
    the OVERLAY as `repo`, so it tried a fresh `npm ci` per overlay under a 180s
    cumulative budget — far under a Nuxt install — timed out, and moved on.

    dependency_prewarm already solves this properly, and build_gate already uses
    it: warm ONE immutable snapshot per manifest and link it into each ephemeral
    worktree. Use that, and keep the old symlink as the fallback.
    """
    _warm_shared_runtime(repo, candidate)

    # Fallback: link a warm node_modules from the first donor that has one.
    #
    # `repo` is an integration worktree and is normally cold, so the original
    # code (which only ever looked at `repo`) linked nothing. The repo's PRIMARY
    # checkout is the same git repository at a different commit — the one a human
    # works in, kept warm — so its node_modules is exactly what this overlay needs
    # and costs a symlink instead of a several-minute `npm ci` per card.
    for donor in (repo, _primary_checkout_of(repo)):
        if not donor:
            continue
        src, dst = os.path.join(donor, "node_modules"), os.path.join(candidate, "node_modules")
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                os.symlink(src, dst)
                break
            except OSError:
                pass

    if os.path.isfile(os.path.join(candidate, "package.json")) \
            and not os.path.exists(os.path.join(candidate, "node_modules")):
        # Last resort: install in place. Loud, because reaching here means the
        # snapshot path failed and the next run will pay this cost again.
        print(f"merge_train: overlay {candidate} still has no node_modules after "
              "prewarm+symlink; installing in place", flush=True)
        _ensure_node_deps(candidate, test_cmd)


def _run_tests(repo, test_cmd, ref=None):
    """Step 3: run the gate. Returns (ok, tail-of-output)."""
    if not test_cmd:
        return True, "no test_cmd configured"
    if ref:
        try:
            import commit_overlay
            with commit_overlay.checkout(repo, ref, prefix="merge-qa-overlay-") as overlay:
                candidate = overlay["path"]
                _share_deps_into_overlay(repo, candidate, test_cmd)
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
        # 2026-08-29: a bulk token conversion across 59 .vue files left several
        # components with a duplicated attribute -- each a hard compile error.
        # TypeScript-only lints do not read templates, so these passed every
        # gate and surfaced inside the production build minutes into a deploy.
        # Compile them here, where the message names the file and line, rather
        # than reading it out of a build log. See repo_hygiene.check_vue_templates.
        # No guard needed: check_vue_templates never raises (see its docstring).
        vue_ok, vue_detail = repo_hygiene.check_vue_templates(repo)
        if not vue_ok:
            return False, ("a Vue component does not compile — the tests were not run, "
                           "because this breaks the build and the dev server too:\n"
                           f"{vue_detail[:4000]}")
    try:
        r = subprocess.run(["bash", "-lc", test_cmd], cwd=repo, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, (f"tests did not finish within {timeout}s — NO verdict on this "
                       "candidate, which is not the same as a red suite. Raise "
                       "MERGE_TRAIN_TEST_TIMEOUT above the suite's real runtime, or find "
                       "what is hanging.")
    if r.returncode != 0:
        tail = ((r.stdout or "")[-6000:] + (r.stderr or "")[-6000:]).strip()
        # One retry after a forced install if the failure looks like missing deps (env, not code).
        # Node says "cannot find module"; vite/rollup — which is what actually runs
        # a vitest suite — says "[UNRESOLVED_IMPORT] Could not resolve 'vitest/config'".
        # None of the original four strings matched that, so the one self-heal that
        # would have caught the missing-node_modules outage never fired on any of
        # the 17 branches it hit on 2026-08-30.
        if any(s in tail.lower() for s in ("cannot find module", "module not found",
                                           "eresolve", "command not found",
                                           "unresolved_import", "could not resolve",
                                           "failed to resolve import",
                                           "cannot find package")):
            _ensure_node_deps(repo)
            try:
                r2 = subprocess.run(["bash", "-lc", test_cmd], cwd=repo, capture_output=True,
                                    text=True, timeout=timeout)
                if r2.returncode == 0:
                    return True, "green (after dep install)"
                return False, ((r2.stdout or "")[-6000:] + (r2.stderr or "")[-6000:]).strip()
            except subprocess.TimeoutExpired:
                return False, (f"tests did not finish within {timeout}s — NO verdict on this "
                       "candidate, which is not the same as a red suite. Raise "
                       "MERGE_TRAIN_TEST_TIMEOUT above the suite's real runtime, or find "
                       "what is hanging.")
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
    _retire_card(card.get("id"), "BUILDFAIL")
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


def _push_base(repo, base, project=None):
    """Step 5: push only when explicitly enabled. Returns '' or an error tail.

    On a non-fast-forward rejection (origin moved while we merged — e.g. the other Mac pushed),
    reconcile once in an ISOLATED worktree: fetch origin/base, rebase local base's extra commits
    onto it, retry the push. Still failing -> return the error; the CALLER must NOT mark the task
    MERGED (a failed push previously counted as a merge and desynced the DB from GitHub)."""
    # SHADOW MODE — checked FIRST, before any other early return.
    #
    # Two things went wrong on the first attempt at this and both are worth writing down.
    #
    # It was placed after the ORCH_PUSH_ON_MERGE guard below, which returns "" and is false in
    # this fleet — so the shadow check was unreachable and recorded nothing at all. A safety
    # feature that never runs is worse than none, because you believe you have it.
    #
    # And it returned "". _push_base returns "" for SUCCESS, so a refusal would have told the
    # caller the push worked and let the task go MERGED with nothing sent to origin — a DB that
    # says shipped while GitHub never moved. That is the exact desync the push-verification gate
    # below exists to stop (observed 2026-07-09), and I nearly reintroduced it through the front
    # door while adding a guard against it.
    #
    # Shadow mode DEFERS, it does not complete. A non-empty return takes the PUSH-PENDING path:
    # the task stays unmerged, its card stays undecided, and the next pass after the window
    # lifts retries it. Rebase, tests and fast-forward are all idempotent by then.
    if shadow_mode.refuse("push-integration-branch", project=project or "",
                          subject=base, detail=f"{repo} -> origin/{base}"):
        return "shadow mode: push withheld, nothing was sent to origin"
    # THE INTEGRATION BRANCH HAS NEVER BEEN PUSHED (found 2026-08-15).
    #
    # This gated on ORCH_PUSH_ON_MERGE, which is false in this fleet and is the flag for pushing
    # a PRODUCTION base. The integration branch is orchestrator/dev, whose flag is
    # ORCH_PUSH_ON_DEV_MERGE, and that is true. _push_enabled_for_base() encodes exactly that
    # distinction — and had ZERO call sites. It was written and never wired.
    #
    # So every train pass merged into the LOCAL integration branch, returned "" here as though
    # it had pushed, and the sha-verification twenty lines below then found origin had not
    # moved. That is the PUSH-VERIFY-FAILED count, and it is why local orchestrator/dev was
    # found running one to four days ahead of origin in every app repo: the work was merged, it
    # simply never left the machine.
    #
    # Shipping this while shadow mode is on is deliberate — the fix is inert until the canary
    # window, so the first real push happens under observation rather than as a surprise.
    if not _push_enabled_for_base(base):
        return ""
    # Ensure auth before push — the PAT may not have been injected yet if
    # task_refs.publish() hasn't run for this repo in this process.
    # Root cause of "Not logged in · Please run /login" failures.
    try:
        import task_refs
        task_refs._ensure_auth(repo)
    except Exception:
        pass  # best-effort; push will fail with a clear error if auth is missing
    # FENCE CHECK (2026-08-13): this is the integration branch update that the 54
    # PUSH-VERIFY-FAILED sha mismatches came from. integration_owner.decide() ran once,
    # at the top of the pass, potentially many cards and minutes ago; re-verify the
    # fence against the store here, immediately before origin moves.
    delivery_lease.require(delivery_lease.held(project or "", delivery_lease.ROLE_INTEGRATOR),
                           f"push integration branch {base}")
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


def _is_ancestor(repo, ancestor_sha, descendant_sha):
    """True when `ancestor_sha` is reachable from `descendant_sha`.

    Fail CLOSED: any git error returns False, so an unanswerable question is treated
    as divergence and the caller refuses. Being wrong in this direction costs a retry;
    being wrong in the other direction certifies a push that never landed.
    """
    if not ancestor_sha or not descendant_sha:
        return False
    try:
        r = _git(repo, "merge-base", "--is-ancestor", ancestor_sha, descendant_sha, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def _verify_push(repo, base):
    """Contract guarantee: our commit is really on origin/{base} after the push.

    Returns '' on success, error string otherwise. This prevents the DB/GitHub desync
    observed 2026-07-09 where a task was marked MERGED but the push silently failed to
    advance origin.

    EXACT-MATCH WAS TOO STRICT (2026-08-07). The check required local == remote, so a
    benign interleave — our push lands, then another train or auto-sync commits on top
    before our read-back — reported VERIFY:sha-mismatch even though our work was safely
    on the remote. Nothing was ever overwritten (the guard did its job), but every event
    burned a full retry cycle, and the rate was climbing with fleet concurrency:
    64 -> 72 -> 81 mismatches over 2026-08-07 alone.

    So the question is no longer "does the remote tip equal my sha" but "is my commit
    ON the remote branch". Those differ only when someone built on top of us, which is
    precisely the benign case. The dangerous cases still fail, because for each of them
    our commit is NOT an ancestor of the remote tip:

      * the push never landed          -> local is AHEAD of remote, not an ancestor;
      * the ref was force-reset/rewound -> our commit is unreachable;
      * a divergent history was pushed  -> our commit is on an abandoned line.
    """
    try:
        local = _git(repo, "rev-parse", base)
        if local.returncode != 0:
            return "VERIFY:rev-parse-failed"
        local_sha = (local.stdout or "").strip()

        # ALWAYS refresh before judging, and refresh with an explicit FORCED refspec.
        #
        # Two separate traps, both found by tests/test_merge_train_push_verify.py:
        #
        # 1. The old code compared against `origin/<base>` FIRST and only fetched if that
        #    disagreed. `origin/<base>` is a local cache, so when it happened to already
        #    equal local the function returned success having never contacted the remote —
        #    it could certify a push that never left the machine. That is the exact
        #    DB/GitHub desync this verifier exists to prevent.
        # 2. A bare `fetch origin <base>` leaves `origin/<base>` UNCHANGED when the remote
        #    was rewound or force-pushed, because that update is not a fast-forward. The
        #    stale ref still contained our commit, so verification passed for a branch our
        #    work had just been force-pushed off.
        #
        # The leading `+` on the refspec is what makes the local remote-tracking ref
        # update non-fast-forward; a `--force` flag would be redundant AND would trip the
        # repo's no-force-push guard (tests/test_release_push_fast_forward.py), which
        # greps for the literal. This only ever rewrites a LOCAL cache ref — it can never
        # touch the remote.
        _git(repo, "fetch", "origin",
             f"+{base}:refs/remotes/origin/{base}", timeout=60)

        remote = _git(repo, "rev-parse", f"origin/{base}")
        if remote.returncode != 0:
            return "VERIFY:rev-parse-failed"
        remote_sha = (remote.stdout or "").strip()
        if not local_sha or not remote_sha:
            return "VERIFY:rev-parse-failed"
        if local_sha == remote_sha:
            return ""
        # Benign advancement: our commit IS on the remote branch, someone just built
        # on top of it between our push and our read-back.
        if _is_ancestor(repo, local_sha, remote_sha):
            return ""
        return f"VERIFY:sha-mismatch local={local_sha[:10]} remote={remote_sha[:10]}"
    except Exception as e:
        return f"VERIFY:exception:{e}"


def _detect_prod_branch(repo, proj):
    for b in (proj.get("prod_branch"), proj.get("default_base"), "main", "master"):
        if b and _git(repo, "rev-parse", "--verify", b).returncode == 0:
            return b
    return proj.get("default_base") or "main"


def _strict_default_base():
    """Prefer projects.default_base over a generic stored base_branch. Default on."""
    return os.environ.get("ORCH_STRICT_DEFAULT_BASE", "true").strip().lower() in (
        "1", "true", "yes", "on")


def _normalize_task_base(repo, proj, requested):
    # 2026-09-01: a *generic* requested base ("main"/"master") must not outrank the
    # project's configured default. db._guard_task_base_branch already applies this rule
    # at insert time, but it is insert-only -- a row written by an unguarded path, or an
    # older row, still carries "main", and checking `requested` first sent that work back
    # to the production branch at execution time. Non-generic values (release/*, hotfix/*)
    # are deliberate and still win. Set ORCH_STRICT_DEFAULT_BASE=false to restore the old
    # requested-first order.
    order = (requested, proj.get("default_base"), proj.get("prod_branch"), "main", "master")
    if _strict_default_base() and (requested or "").strip().lower() in ("", "main", "master"):
        order = (proj.get("default_base"), requested, proj.get("prod_branch"), "main", "master")
    for b in order:
        if _branch_exists(repo, b):
            return b
    return proj.get("default_base") or requested or "main"


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
            if _materialize_branch(repo, f"agent/{slug}", task):
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
            # Explicitly re-writing status="approved" here is what kept 18,518 duplicate
            # cards in the pool: invisible to the train, invisible to dedup, immortal.
            _retire_card(card.get("id"), "dup-card")
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
    def operator_rank(entry):
        _card, slug, task, _risk = entry
        note = str(task.get("note") or "").lower()
        return 0 if (task.get("submitted_by") or str(slug).startswith("dropbox-")
                     or "source:operator-" in note or "source:intent-console" in note) else 1

    # Authenticated/manual requests are attempted before speculative machine work.
    # All normal risk caps and every regression/build/divergence gate still apply.
    annotated.sort(key=lambda e: (operator_rank(e),
                                  {"low": 0, "standard": 1, "sensitive": 2}[e[3]],
                                  -value_scores.get(str(e[2].get("id") or e[2].get("slug") or ""), 0),
                                  str(e[0].get("created_at") or "")))
    return annotated


#: Status a card carries once the train has finished with it. _find_existing_card and
#: _pick_cards both look only at status in (pending, approved), so anything outside that
#: set means "no longer a live card" to every reader.
#:
#: It must be a member of the `approval_status` enum, which is
#: (pending, approved, denied, superseded) — verified against the live schema on
#: 2026-08-24, where 50,340 integrate cards already carry `superseded` against 3,990 still
#: `approved`. An invented value such as "closed" is rejected by Postgres, so every retire
#: would have fallen through to the decided_by-only path, i.e. exactly the behaviour this
#: was written to replace. "denied" would be wrong in the other direction: it means a human
#: refused the change, and this is the train finishing with a card it already acted on.
TERMINAL_STATUS = "superseded"

#: Train outcomes that mean the work behind this slug is finished or unusable, so a card
#: filed for the same slug moments later is a duplicate rather than new work. Everything
#: else the train stamps (TESTFAIL, BUILDFAIL, REGRESSFAIL, redo, conflict-exhausted,
#: branch-missing, no-repo, ...) is a RETRYABLE outcome: the task is re-queued or waiting
#: on a human, and when it produces new work it must be able to file a fresh card.
FINAL_OUTCOMES = ("MERGED", "ALREADY_INTEGRATED", "dup-card", "no-slug", "no-task")


def _card_cooldown_s():
    """Read at call time so fleet_config changes take effect without a restart."""
    try:
        return max(0, int(os.environ.get("MERGE_CARD_REFILE_COOLDOWN_S", "3600")))
    except (TypeError, ValueError):
        return 3600


def _retire_card(card_id, outcome):
    """Record a terminal train outcome AND take the card out of the approved pool.

    Returns True when the card was fully retired, False when nothing could be written.

    THE CARD AMPLIFIER (2026-08-16). Terminal outcomes used to write `decided_by` and
    leave `status='approved'`. _pick_cards() skips decided_by=train:*, so the train never
    looked at the card again — but _find_existing_card() skips train:* too, so the next
    producer could not see it either and filed a REPLACEMENT, forever. Measured on the
    live fleet: 37,012 approved integrate cards over 4,474 slugs, 100% train-authored;
    train:dup-card alone held 18,518 cards across 221 slugs (83.8 copies per slug, worst
    slug 144), growing at ~150-300 cards/hour. A card the train is done with has to leave
    the pool, not just get a note attached to it.

    Fail-soft in two steps because this runs inside the merge path: if the status write is
    rejected (an older approvals table, a CHECK constraint on status) the outcome is still
    recorded with the decided_by stamp alone, which is exactly the pre-fix behaviour, and
    the duplicate loop is still broken by the _recently_finalised cooldown below. Nothing
    here may raise: a bookkeeping failure must never abort an integration.
    """
    if not card_id:
        return False
    stamp = f"{MARK}:{outcome}"
    try:
        db.update("approvals", {"id": card_id},
                  {"decided_by": stamp, "status": TERMINAL_STATUS, "decided_at": "now()"})
        return True
    except Exception as exc:
        print(f"merge_train: could not retire card {card_id} ({exc}); "
              f"recording the outcome only", flush=True)
    try:
        db.update("approvals", {"id": card_id}, {"decided_by": stamp})
    except Exception:
        pass
    return False


def _recently_finalised(slug):
    """The most recent FINAL train outcome for `slug` inside the refile cooldown, else None.

    The second half of the amplifier fix. Retiring cards stops the train from re-reading
    them, but a producer that keeps finishing the same slug would still file a fresh card
    every pass now that the retired one is invisible to dedup. A slug the train merged (or
    resolved as a duplicate / unusable) minutes ago does not need another card; a slug that
    failed its tests does, as soon as the repaired work lands.

    Fail-open by construction: any lookup failure returns None. One duplicate card is a
    nuisance, whereas refusing to file a card strands finished work with no way back into
    the train — the failure mode CARD_FAILED exists to make visible.
    """
    if not slug:
        return None
    try:
        rows = db.select("approvals", {
            "select": "id,slug,kind,status,decided_by,decided_at",
            "slug": f"eq.{slug}", "kind": f"in.({','.join(MERGE_KINDS)})",
            "order": "decided_at.desc", "limit": "5"}) or []
    except Exception as exc:
        print(f"merge_train: refile cooldown lookup failed for {slug} ({exc}); "
              f"allowing the card", flush=True)
        return None
    cooldown = _card_cooldown_s()
    for row in rows:
        decided_by = str((row or {}).get("decided_by") or "")
        if not decided_by.startswith(f"{MARK}:"):
            continue
        if decided_by.split(":", 1)[1] not in FINAL_OUTCOMES:
            continue
        if not row.get("decided_at"):
            continue          # undatable stamp: cannot say it is recent, so do not block
        if _age_seconds(row.get("decided_at")) <= cooldown:
            return row
    return None


CARD_CREATED = "created"
CARD_EXISTED = "existed"
CARD_FAILED = "failed"
#: Outcomes that mean "this slug is now visible to the merge train". Callers MUST
#: treat only these as success. CARD_FAILED means the work is not integrable and the
#: producing task must NOT be marked DONE.
CARD_OK = (CARD_CREATED, CARD_EXISTED)


def _find_existing_card(slug):
    """Targeted, server-side lookup for a live merge card carrying `slug`.

    SCAN-WINDOW ANTI-PATTERN (removed 2026-08-06). This used to pull the newest
    MERGE_CARD_DEDUP_SCAN (default 4,000) approval rows and filter CLIENT-SIDE against a
    table of 238,177 rows. The in-code comment already recorded the consequence — "240 dupes
    of one slug" — and the identical pattern had just caused a starvation outage in
    _pick_cards(). A scan cannot be made correct by making the window bigger: any card older
    than the window is invisible, so dedup silently fails and the caller files a duplicate.

    Two bounded queries replace it. The first matches the `slug` column directly. The second
    covers legacy rows written before the column existed, where the slug lives only in the
    "merge of <slug>" title (see approval_merge._slug_from). Both are LIMIT-1 server-side
    filters, so cost is independent of table size.
    """
    if not slug:
        return None
    kinds = f"in.({','.join(MERGE_KINDS)})"
    common = {"select": "id,slug,title,kind,status,decided_by",
              "kind": kinds, "status": "in.(pending,approved)"}
    # SKIP_PREFIXES pushed into the query so the train's own outcome stamps
    # ("train:MERGED", "merge-handler:...") never masquerade as a live card.
    not_handled = ",".join(f"decided_by.not.like.{p}*" for p in SKIP_PREFIXES)
    for params in (
        dict(common, slug=f"eq.{slug}", limit="1", or_=f"(decided_by.is.null,{not_handled})"),
        dict(common, title=f"ilike.*merge of {slug}*", limit="5"),
    ):
        # `or_` is spelled with a trailing underscore above only to keep it a valid kwarg
        # name; PostgREST expects the bare key "or".
        if "or_" in params:
            params["or"] = params.pop("or_")
        try:
            rows = db.select("approvals", params) or []
        except Exception:
            rows = []
        for c in rows:
            if str(c.get("decided_by") or "").startswith(SKIP_PREFIXES):
                continue
            if approval_merge._slug_from(c) == slug:
                return c
    return None


def ensure_integration_card_result(project, slug, *, kind="integrate", title=None, why=None,
                                   detail=None, status="approved",
                                   decided_by="canonical-train"):
    """Idempotently feed passed code into the single canonical integration train.

    Producers should not merge directly. They create/approve one code-merge card
    and let train_run serialize rebase, tests, fast-forward, and cleanup.

    Returns one of CARD_CREATED / CARD_EXISTED / CARD_FAILED. The tri-state exists because
    the historical bool return conflated "a card already covers this slug" (fine) with
    "nothing was created and nothing exists" (a task that can never be integrated). Callers
    that only check truthiness treated the second case as success and stranded the work.
    """
    if not slug:
        return CARD_FAILED
    title = title or f"merge of {slug}"
    try:
        existing = _find_existing_card(slug)
    except Exception:
        existing = None
    finalised = None if existing else _recently_finalised(slug)
    if finalised:
        # The train finished this slug moments ago and retired its card. Filing another
        # one here is the duplicate loop, not new work — see _recently_finalised. The
        # producer is told CARD_EXISTED because the work IS accounted for.
        return CARD_EXISTED
    if existing:
        patch = {}
        if existing.get("status") != status:
            patch["status"] = status
        if status == "approved" and not existing.get("decided_by"):
            patch["decided_by"] = decided_by
        if patch:
            try:
                db.update("approvals", {"id": existing["id"]}, patch)
            except Exception:
                pass  # the card exists and is live; a failed status nudge is not a strand
        return CARD_EXISTED
    row = {"project": project, "kind": kind, "slug": slug, "title": title,
           "status": status, "why": why or "passed tests; queued for canonical merge train",
           "detail": detail or "", "decided_by": decided_by if status == "approved" else None}
    try:
        db.insert("approvals", row)
        return CARD_CREATED
    except Exception:
        # Some older approval tables may not have a slug column. The title fallback
        # keeps approval_merge._slug_from compatible with those rows.
        row.pop("slug", None)
        try:
            db.insert("approvals", row)
            return CARD_CREATED
        except Exception:
            # Do NOT swallow. The caller decides what to do, but it must be told.
            return CARD_FAILED


def ensure_integration_card(project, slug, **kwargs):
    """Back-compatible wrapper: True only when a NEW card was created.

    Preserved verbatim in meaning for the many existing callers that use the bool.
    New code should call ensure_integration_card_result() and check `in CARD_OK`.
    """
    return ensure_integration_card_result(project, slug, **kwargs) == CARD_CREATED


# ── the train ─────────────────────────────────────────────────────────────────

def _scan_max_rows():
    """Safety cap for the paged approval scan.

    MERGE_TRAIN_SCAN_LIMIT no longer selects a scan WINDOW (there is no window any more);
    a positive value now caps how many rows the paged scan will read before it reports
    truncation, so an operator can still bound one pass. Non-positive means "meant for the
    legacy hosts, not for me" — see the kill-switch note in _pick_cards — and defers to
    db.select_all's own SELECT_ALL_MAX_ROWS.
    """
    try:
        value = int(str(os.environ.get("MERGE_TRAIN_SCAN_LIMIT", "")).strip().strip('"'))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _scan_approvals(params):
    """Every approval row matching `params`, paged to exhaustion.

    Degrades rather than dies. Not every host in this fleet runs this db module — the
    cross-host version skew that keeps showing up in these comments is the same reason
    `select_all` is reached through getattr and its answer is type-checked instead of
    trusted: an older db.py has no paging at all, and a broken one is worse than none.
    Either way the fallback is the bounded dual-order window this scan used to be, so the
    head and the tail of the backlog are still looked at.
    """
    max_rows = _scan_max_rows()
    page_all = getattr(db, "select_all", None)
    if callable(page_all):
        try:
            rows = page_all("approvals", params, order="created_at.asc",
                            **({"max_rows": max_rows} if max_rows else {}))
            if isinstance(rows, list):
                return rows
            reason = f"select_all returned {type(rows).__name__}, not a list"
        except Exception as exc:
            reason = str(exc)
    else:
        reason = "this db module has no select_all"
    print(f"merge_train: paged approval scan unavailable ({reason}); "
          f"degrading to a bounded dual-order window", flush=True)
    page = str(max_rows or getattr(db, "PAGE_SIZE", 1000))
    rows = []
    for order in ("created_at.asc", "created_at.desc"):
        rows.extend(db.select("approvals", {**params, "order": order, "limit": page}) or [])
    return rows


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
    # SCAN-WINDOW STARVATION (fixed 2026-08-06) — the real cause of months of stranded work.
    #
    # This scanned the NEWEST `limit` approved cards and filtered client-side. The approvals
    # table now holds 238,177 rows, and the train stamps decided_by on every card it handles,
    # so the newest 3,000 are almost entirely already-decided outcomes. A card that was created
    # but not merged (branch not ready, project paused, host stale, train crashed mid-pass)
    # ages out of that window within hours and is then INVISIBLE FOREVER — while
    # ensure_integration_card still sees it and refuses to file a replacement, so the task can
    # never be re-queued either. Measured: 90 finished tasks holding valid, undecided cards
    # that the train had not looked at in up to 98 hours, with `undecided cards = 0` reported
    # because every one of them sat outside the scan window.
    #
    # Scanning oldest-first as well as newest-first costs one extra query and bounds the
    # damage permanently: the backlog head is always visible, and fresh work still enters via
    # the desc pass. Dedup by id since the two windows overlap once the backlog is small.
    # SERVER-SIDE UNHANDLED FILTER (2026-08-06, second half of the same bug).
    #
    # Scanning both ends of the table bounded the damage but did not remove it. Measured today:
    # 21,974 approved merge-kind cards exist, of which only 569 are genuinely unhandled — and
    # PostgREST silently caps `limit` at 1,000 rows per request, so MERGE_TRAIN_SCAN_LIMIT=3000
    # really means "the 1,000 oldest plus the 1,000 newest". The other ~20,000 rows in the middle
    # are already-decided outcomes the train re-reads forever, while roughly 466 of the 569 real
    # candidates sit in the middle and are structurally invisible. That is the mechanism behind
    # "the queue never finishes": the work was never lost, it was never *looked at*.
    #
    # Pushing the SKIP_PREFIXES test into the query makes the window hold candidates instead of
    # history, so all 569 fit in one page with room to spare. decided_by IS NULL has to be
    # spelled out because SQL NOT LIKE on NULL is NULL, not true, and freshly-filed cards
    # ("canonical-train:sweeper", an attribution marker, not a verdict) must stay visible.
    #
    # The dual-order scan and the client-side filter below are both KEPT: the first so a backlog
    # larger than one page still shows its head, the second so this stays correct even if the
    # server-side predicate is dropped by the fallback path.
    # MERGE_TRAIN_SCAN_LIMIT=0 in fleet_config is the fleet-wide kill switch for hosts too old
    # to honour integration_owner.decide() — today, Mac 2 on 10d9e408, which cannot pull itself
    # forward (14 dirty tracked files, and that build has no regenerable allowlist or remote
    # escape hatch) and therefore keeps running a second merge train against the same origin.
    # Starving _pick_cards is the only lever that build exposes.
    #
    # It was pinned out of the way on this host via ORCH_CONFIG_ENV_PINS, and that silently did
    # not take: the running runner had inherited the pre-edit pins list from its parent, so
    # os.environ.setdefault never applied the new one and THIS host quietly picked up the kill
    # switch too — one train pass returned an all-zero summary before it was caught. A safety
    # interlock that depends on a restart landing in the right order is not a safety interlock.
    #
    # Current code has integration_owner and does not need this switch to police itself, so it
    # declines to be disabled by it. Operators wanting a genuine local override set a positive
    # MERGE_TRAIN_SCAN_LIMIT; non-positive means "meant for the legacy hosts, not for me".
    # PAGE, DO NOT WIDEN (2026-08-16, third and final half of the same bug). The scan above
    # still asked for `limit=MERGE_TRAIN_SCAN_LIMIT` (3,000) in ONE request, and PostgREST
    # caps a single response at 1,000 rows however large the limit is — so the setting never
    # widened the window, it only hid the truncation, exactly as db.py's scan-window note
    # says (it names this function as one of the four outage-class instances). db.select_all
    # is the prescribed FULL SCAN path: it pages until the server stops returning rows, so
    # the candidate set is bounded by the FILTER instead of by one page.
    base = {"select": "*", "status": "eq.approved",
            "kind": f"in.({','.join(MERGE_KINDS)})"}
    unhandled = "or=(decided_by.is.null,and({}))".format(
        ",".join(f"decided_by.not.like.{p}*" for p in SKIP_PREFIXES))
    _k, _v = unhandled.split("=", 1)
    scans = ({**base, _k: _v}, base)  # narrowed first; unfiltered only as a fallback

    cards, seen = [], set()
    for params in scans:
        try:
            got = _scan_approvals(params)
        except Exception as e:
            # A server that will not accept the predicate must not take the train down with it.
            print(f"merge_train: unhandled-card filter unavailable ({e}); "
                  f"falling back to the unfiltered scan window", flush=True)
            continue
        for c in got:
            cid = c.get("id")
            if cid in seen:
                continue
            seen.add(cid)
            cards.append(c)
        break  # the narrowed scan succeeded; the fallback page is redundant
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
        _retire_card(card.get("id"), "no-repo")
        _log(pname, slug, "SKIP", "repo missing")
        return "no-repo"

    base = _integration_base(repo, proj, task_base)

    # CROSS-HOST OWNERSHIP (2026-08-13): take the integrator lease for THIS repository
    # before touching it. `ensure` is idempotent for this process, so a pass covering
    # many cards in one repo acquires once and keeps it — releasing per card would drop
    # ownership between cards and invite a takeover mid-pass. train_run releases the
    # whole set at the end. Yielding here is not a failure: another host owns this repo
    # and the card stays undecided for its train to pick up.
    if delivery_lease.ensure(pname, delivery_lease.ROLE_INTEGRATOR) is None \
            and delivery_lease.available():
        _log(pname, slug, "SKIP", "another host holds the integrator lease")
        return "not-integrator"

    if not _materialize_branch(repo, branch, task):
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
        _retire_card(card.get("id"), "branch-missing")
        _log(pname, slug, "BLOCKED", "branch missing")
        return "branch-missing"

    _refresh_base(repo, base)                                     # (1)
    if _already_integrated(repo, branch, base):
        # Evidence: branch tip is an ancestor of base, so that tip IS the integrated commit.
        integrated_sha = _commit_identity(repo, branch)
        _task_patch(task, {"state": "MERGED",
                           "artifact_commit": integrated_sha,
                           "note": f"train: already integrated in {base} @ {integrated_sha[:12]}"})
        _retire_card(card.get("id"), "ALREADY_INTEGRATED")
        _attribute_merge_outcome(slug, task)
        _attribute_train_outcome(slug, task, "already-integrated", integrated=True)
        approval_merge._free_branch(repo, branch)
        _log(pname, slug, "ALREADY", f"present in {base}; no ref advance")
        return "already-integrated"
    _task_patch(task, {"state": MERGING_STATE, "note": f"train: integrating {branch} into {base}"})

    _orig_fork = _git(repo, "merge-base", branch, base).stdout.strip()  # pre-rebase fork point
    rebase_ok, conflict_detail = _rebase_onto_base(repo, branch, base)  # (2)
    if not rebase_ok:
        # (2b) MINIMAL EXTRACTION BEFORE PAYING FOR A REBUILD.
        #
        # The branch that failed to rebase is frequently not carrying a real content
        # conflict — it is carrying the agent's leftovers alongside the change. Every
        # extra file in the range is another chance to collide with a base that has
        # moved. minimal_commit.extract() rebuilds the branch from the task's own
        # artifact commit onto the current base, keeping only that task's files, and
        # refuses (leaving the branch untouched) on anything it cannot do safely:
        # more than max_files paths, any generated tree, a patch that will not apply.
        #
        # This runs only on the path that was already going to DELETE the branch and
        # spend an agent rebuild, so the downside of an attempt is a few git commands.
        # Everything downstream is unchanged: post-fork regression, the content
        # regression gate and the test run all still have to pass afterwards. Set
        # ORCH_MINIMAL_COMMIT_ON_CONFLICT=0 to skip it.
        if os.environ.get("ORCH_MINIMAL_COMMIT_ON_CONFLICT", "1").strip().lower() \
                not in ("0", "false", "no", "off"):
            try:
                import minimal_commit
                extracted = minimal_commit.extract(repo, branch, base, task)
            except Exception as exc:  # noqa: BLE001 — never let recovery break integration
                extracted = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
            if extracted.get("ok"):
                rebase_ok, conflict_detail = _rebase_onto_base(repo, branch, base)
                _log(pname, slug, "MINIMAL",
                     "extracted {0} file(s) onto {1} @ {2}; rebase {3}".format(
                         len(extracted.get("files") or []), base,
                         str(extracted.get("commit") or "")[:12],
                         "clean" if rebase_ok else "still conflicts"))
            else:
                _log(pname, slug, "MINIMAL",
                     f"not extracted ({extracted.get('reason')}); falling through to rebuild")

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
            _retire_card(card.get("id"), "redo")
            _log(pname, slug, "REDO", f"rebase conflict{files_hint}, rebuild on fresh {base} ({tr+1}/{cap})")
            return "redo"
        _task_patch(task, {"state": "CONFLICT",
                           "note": f"train: still conflicts after {cap} redos - needs manual rebase.{files_hint}"})
        _retire_card(card.get("id"), "conflict-exhausted")
        _attribute_train_outcome(slug, task, "conflict", integrated=False)
        _log(pname, slug, "CONFLICT", f"redo cap {cap} exhausted{files_hint}")
        return "conflict"

    test_cmd = _test_cmd_for(proj, repo)
    candidate_sha = _commit_identity(repo, branch)
    reg_ok, reg_detail = _post_fork_regression(repo, branch, base, _orig_fork)
    if not reg_ok:
        _task_patch(task, {"state": "BLOCKED",
                           "note": ("train: REGRESSION-RISK — clean rebase deletes recently-merged improvements: " + reg_detail)[:480]})
        _retire_card(card.get("id"), "REGRESSION-RISK")
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

    # (2f) ORPHAN-IMPORT GATE — the cheapest gate we have, so it runs before the expensive ones.
    # Catches a candidate whose import resolves on the author's disk and nowhere in the repo.
    oi_ok, oi_detail = _orphan_import_gate(repo, base, branch)
    if not oi_ok:
        return _quarantine_regression_failure(repo, card, slug, task, pname, branch, base,
                                              "DANGLING IMPORT — " + oi_detail, _t0)

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
        _retire_card(card.get("id"), "TESTFAIL")
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
            _retire_card(card.get("id"), "redo")
            _log(pname, slug, "REDO", f"ff refused ({tr+1}/{cap})")
            return "redo"
        _task_patch(task, {"state": "CONFLICT", "note": f"train: base won't fast-forward after {cap} redos"})
        _retire_card(card.get("id"), "conflict-exhausted")
        _attribute_train_outcome(slug, task, "ff-conflict", integrated=False)
        _log(pname, slug, "CONFLICT", "ff refused, cap exhausted")
        return "conflict"

    push_err = _push_base(repo, base, project=pname)              # (5)
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

    # (6) MERGED with evidence: current_candidate_sha is the exact snapshot that passed QA,
    # was fast-forwarded into base, and whose presence on origin the push-verification gate
    # (5b) just confirmed. Persist it as artifact_commit — the DB evidence gate requires it.
    _task_patch(task, {"state": "MERGED",
                       "artifact_commit": current_candidate_sha,
                       "note": f"train: MERGED into {base} @ {str(current_candidate_sha)[:12]}"})
    _retire_card(card.get("id"), "MERGED")
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


def _train_run_unleased(report=None):
    """Run the integration train across all projects (serialized per project).

    The lease-taking public entry point is `train_run()` at the bottom of this module;
    this is the body it delegates to. Both used to be spelled `def train_run`, with an
    `_train_run_unleased = train_run` alias wedged between them. That worked at runtime
    (the alias captured the first binding before the second shadowed it) but it made the
    real implementation invisible to `inspect.getsource(merge_train.train_run)` — which
    is how test_critical_fixes.py verifies the `repo_lock.hold(repo_path, timeout=...)`
    call, so that guard silently went red. Naming the two functions differently keeps the
    behaviour identical and makes the implementation reachable by name again.

    `report` is a merge_train_report.PassReport recording, per card, why this pass
    ended without merging it. Before it existed, a pass that merged nothing was
    indistinguishable from a pass that never ran (see merge_train_report docstring).
    Created here when the caller does not supply one, so direct callers and the
    existing tests keep working unchanged.

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
    # _owned_report means "this frame created it, so this frame persists it". When the
    # leased wrapper supplies one it owns persistence, so we must not write it twice.
    _owned_report = report is None
    if report is None:
        try:
            import merge_train_report
            report = merge_train_report.PassReport(trigger="train_run")
        except Exception:
            report = None
    _owned_report = _owned_report and report is not None

    def _r(method, *args):
        """Instrumentation must never be able to break the train."""
        if report is None:
            return
        try:
            getattr(report, method)(*args)
        except Exception:
            pass

    if _paused():
        print("merge_train: paused — skipping")
        _r("not_run", "paused")
        if _owned_report:
            _r("persist")
        return {"paused": True}

    cards = _pick_cards()
    projects = {p["id"]: p for p in (db.select("projects") or [])}

    # PER-PROJECT PAUSE (2026-08-06). `_paused()` above only consults the GLOBAL kill switch.
    # Pausing a single project writes controls(scope='project', paused=true), which db.py
    # honours when CLAIMING work -- but nothing here honoured it, so a paused project kept
    # being merged and pushed to its production branch. Observed with illuminati: the operator
    # asked for direct updates to stop because it is being absorbed into apparently/tomorrow/
    # apparently-law/pareto, task claiming stopped correctly, and the train went on merging and
    # deploying it anyway. "Paused" has to mean no writes of any kind, not just no new work.
    # NOTE: paused project ids are collected here but the `projects` MAP IS LEFT INTACT.
    # An earlier version of this filter deleted paused entries from `projects`, which made
    # `projects.get(pid)` return {} further down; repo_path became "" and _record_pressure
    # crashed the whole train with FileNotFoundError on an empty cwd. Paused projects are
    # dropped from the per-project WORK grouping below instead, so lookups stay valid.
    _paused_pids = set()
    try:
        _paused_names = {
            (r.get("project") or "").strip()
            for r in (db.select("controls", {"select": "project,paused,scope",
                                             "scope": "eq.project", "paused": "is.true"}) or [])
            if (r.get("project") or "").strip()
        }
        if _paused_names:
            _paused_pids = {pid for pid, p in projects.items() if p.get("name") in _paused_names}
            if _paused_pids:
                print("merge_train: skipping paused project(s): "
                      + ", ".join(sorted(projects[pid].get("name", "?") for pid in _paused_pids)))
    except Exception as _pp_exc:      # never let a control-plane read stop the whole train
        print(f"merge_train: per-project pause check failed ({_pp_exc}); continuing unpaused")

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
            _retire_card(c.get("id"), "no-slug")
            _r("skipped", f"card:{c.get('id')}", "no-slug: card resolves to no task slug")
            continue
        _r("consider", slug)
        if not t:
            _retire_card(c.get("id"), "no-task")
            _r("skipped", slug, "no-task: no task row for this slug")
            continue
        by_project.setdefault(t.get("project_id"), []).append((c, slug, t))

    # Drop paused projects from the work grouping (see the pause block above). Their cards are
    # left UNDECIDED on purpose: pausing is reversible, and marking them decided here would
    # silently discard the queued work when the project is resumed.
    if _paused_pids:
        for _pid in _paused_pids:
            for _c, _slug, _t in by_project.get(_pid, []):
                _r("skipped", _slug,
                   f"project-paused: {(projects.get(_pid) or {}).get('name') or _pid}")
        by_project = {pid: v for pid, v in by_project.items() if pid not in _paused_pids}

    # ORPHANED project_id (2026-09-01): a card can resolve to a task whose project row no
    # longer exists (renamed/archived/deleted). projects.get(pid) then returns {}, repo_path
    # becomes "" and _record_pressure crashed the whole pass with FileNotFoundError(''). The
    # comment on the paused-project block above documents this exact failure, but the fix
    # there only covered paused ids. Drop unknown/repo-less groups here for the same reason,
    # and say which ones, loudly -- silently skipping real work is how this fleet got here.
    _orphans = [pid for pid in by_project
                if not (projects.get(pid) or {}).get("repo_path")]
    for _pid in _orphans:
        _n = len(by_project.get(_pid, []))
        print(f"merge_train: dropping {_n} card(s) for unknown/repo-less project_id {_pid} — "
              f"no project row or no repo_path; these cannot be merged by any host",
              flush=True)
        for _c, _slug, _t in by_project.get(_pid, []):
            _r("skipped", _slug, f"orphaned-project: {_pid}")
    if _orphans:
        by_project = {pid: v for pid, v in by_project.items() if pid not in _orphans}

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
        lock_timeout = float(os.environ.get("ORCH_MERGE_REPO_LOCK_TIMEOUT_S", "5"))
        with repo_lock.hold(repo_path, timeout=lock_timeout) as got_lock:
            if not got_lock:
                result["skipped"] += len(group)
                for _c, _slug, _t in group:
                    _r("skipped", _slug, "repo-lock: another train holds this project's repo lock")
                print(f"merge_train: {proj.get('name') or pid} busy (another train holds the repo lock) — skipping this cycle")
                return result
            try:
                with integration_runtime.isolated_repo(repo_path, "merge_train") as integration_repo:
                    for card, slug, task, risk in _select_batch(group):
                        if used[risk] >= caps[risk] or scanned >= scan_cap:
                            # FIX 2026-08-24: the PassReport was told about this card but the
                            # summary counter was not, so a pass that deferred every card to
                            # the next bounded pass reported "0 merged, 0 skipped" — the
                            # shape that is indistinguishable from a pass that never ran, and
                            # the exact confusion merge_train_report exists to remove.
                            # _train_run_unleased's own docstring defines skipped as
                            # "branches skipped (cap reached or repo locked)"; the repo-lock
                            # half counted, this half did not.
                            result["skipped"] += 1
                            _r("skipped", slug,
                               f"cap: {risk} batch cap {caps[risk]} reached"
                               if used[risk] >= caps[risk]
                               else f"cap: per-project scan cap {scan_cap} reached")
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
                            _r("merged", slug)
                        elif outcome == "already-integrated":
                            result["already_integrated"] += 1
                            _r("skipped", slug, "already-integrated: base already contains this work")
                        elif outcome == "redo":
                            result["redo"] += 1
                            _r("failed", slug, "redo: stale-base rebase conflict, re-queued")
                        elif outcome == "testfail":
                            result["testfail"] += 1
                            _r("failed", slug, "testfail: tests red after rebase")
                        elif outcome == "regressfail":
                            result["regressfail"] += 1
                            _r("failed", slug, "regressfail: candidate would destroy code in base")
                        elif outcome == "buildfail":
                            result["buildfail"] += 1
                            _r("failed", slug, "buildfail: production build red")
                        elif outcome == "conflict":
                            result["conflict"] += 1
                            _r("failed", slug, "conflict: unresolvable merge conflict")
                        else:
                            result["skipped"] += 1
                            _r("skipped", slug, f"other: _integrate_card returned {outcome!r}")
            except integration_runtime.IntegrationRuntimeError as exc:
                result["skipped"] += len(group)
                for _c, _slug, _t in group:
                    _r("skipped", _slug, f"isolation-blocked: {str(exc)[:200]}")
                print(f"merge_train: {proj.get('name') or pid} isolation blocked: {exc}")
            except FileNotFoundError as exc:
                # A concurrent/killed pass removed a worktree dir mid-flight.
                # Transient by construction — the entry-time `worktree prune`
                # heals it next pass. Skip, don't error (2026-07-31 class).
                result["skipped"] += len(group)
                for _c, _slug, _t in group:
                    _r("skipped", _slug, "worktree-vanished: transient, heals next pass")
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
            for _c, _slug, _t in group:
                _r("skipped", _slug,
                   f"project-error: {type(exc).__name__}: {str(exc)[:150]}")
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

    # TEST-PIPELINE HEALTH. Restored 2026-08-25: added in 85f4aa95 and lost in a
    # later merge, leaving pipeline_metrics.get_health() with no caller anywhere
    # in the repository while _pm.record() kept feeding it. Every pass has been
    # writing the samples and nothing has been reading them, so the pass-rate and
    # gate-decision breakdown this module collects reached no one.
    # runner/tests/test_pipeline_observability.py has been red on the missing
    # summary key since.
    if _pm:
        _health = _test_pipeline_health(_pm)
        if _health is not None:
            summary["test_pipeline"] = _health

    print(f"merge_train: {summary['merged']} merged, {summary['already_integrated']} already, "
          f"{summary['redo']} redo, "
          f"{summary['testfail']} testfail, {summary['regressfail']} regressfail, "
          f"{summary['buildfail']} buildfail, {summary['conflict']} conflict, "
          f"{summary['skipped']} skipped, {summary['project_errors']} project errors "
          f"across {summary['projects']} project(s)"
          f"{f', {auto_resolved} auto-resolved' if auto_resolved else ''}")

    # A pass that merged nothing must say why, per card. Silence here is the bug.
    if report is not None:
        try:
            summary["pass_report"] = report.to_dict()
            summary["no_op_reason"] = report.no_op_reason()
        except Exception:
            pass
        if _owned_report:
            _r("persist")
    return summary


def train_run():
    """Run the whole merge pass under the cross-train single-flight lease.

    CROSS-HOST GUARD (2026-08-06): the lease below is a flock on a file under THIS machine's
    .runtime/, so it serialises processes on one Mac and is blind to the others. With two Macs
    both running trains against the same GitHub origin that produced 54 PUSH-VERIFY-FAILED
    sha-mismatches — real work destroyed by a push race, including the public-landing-hero
    copyfix. integration_owner elects exactly one live host to integrate (and refuses hosts
    running stale code), which is the missing cross-machine half of this lock.
    """
    report = None
    try:
        import merge_train_report
        report = merge_train_report.PassReport(trigger="scheduled")
    except Exception:
        pass

    def _end(reason, summary):
        """Record and persist a pass that ended before looking at any card."""
        if report is not None:
            try:
                report.not_run(reason)
                report.persist()
            except Exception:
                pass
        return summary

    # HOST PAUSE (2026-08-06): a paused host must not START a new pass. Checked before the
    # owner election for the same reason as release_train — winning an election is not
    # permission to run when the operator has stopped this machine. A pass already under
    # way is never interrupted; only starting is refused.
    #
    # Routed through _end so it is a *reported* non-run rather than a silent one. That is
    # the whole point of FAILURE 2: an operator pause and a wedged train produced the same
    # empty result, and the instrumentation is worthless if the earliest exit skips it.
    _ok, _why = paused_host_guard.refuse("merge_train")
    if not _ok:
        return _end(f"host-paused: {_why}", {"skipped": _why})

    try:
        import integration_owner
        may, why = integration_owner.decide()
        if not may:
            print(f"merge_train: not the integration owner — {why}", flush=True)
            return _end(f"not-integration-owner: {why}",
                        {"skipped": f"not integration owner: {why}"})
    except Exception as _io_exc:      # a broken owner check must never stall every host
        print(f"merge_train: integration-owner check failed ({_io_exc}); proceeding", flush=True)

    # FAILURE 1 (2026-08-06): most DONE tasks never reach integrate(), so no card is
    # ever filed and the train cannot see them. Reconcile before the pass so this
    # cycle's scan includes work that finished on a card-less path. Fail-soft: a
    # reconciler outage must degrade to the old behaviour, not stop integration.
    try:
        import done_to_merged
        done_to_merged.reconcile_missing_cards()
    except Exception as _rc_exc:
        print(f"merge_train: card reconciler unavailable ({_rc_exc}); continuing", flush=True)

    timeout = float(os.environ.get("ORCH_INTEGRATION_LEASE_TIMEOUT_S", "0") or 0)
    with integration_runtime.global_lease("merge_train", timeout=timeout) as acquired:
        if not acquired:
            return _end("lease-not-acquired",
                        {"skipped": "another integration or release train owns the global lease"})
        try:
            summary = _train_run_unleased(report=report)
            if report is not None:
                try:
                    report.persist()
                except Exception:
                    pass
            try:
                import done_to_merged
                done_to_merged.publish_health()
            except Exception:
                pass
            return summary
        finally:
            # Hand every repository back at the end of the pass so the next host takes
            # over immediately instead of waiting out each TTL. Failing to release is
            # not an error — the TTL still reclaims it.
            delivery_lease.release_all(delivery_lease.ROLE_INTEGRATOR)


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

    # SELF-ENFORCED DEADLINE (2026-08-06). The runtime cap lived only in runner.py's
    # _reap_stale_periodic, which can only kill pids recorded in that runner's own
    # _PERIODIC_PIDS map. Restart the runner and every train it launched is reparented to
    # init and becomes unkillable by the fleet — while still holding the flock above.
    #
    # Observed today: pid 37459, ppid 1, wedged 24 minutes in pure Python with seven lines of
    # output, holding merge-train.single.lock. No train could start on this machine at all for
    # as long as it lived, and nothing was going to reap it. A supervisor-dependent timeout is
    # not a timeout; the pass has to own its own budget.
    #
    # faulthandler dumps every thread before we go, so the NEXT wedge is diagnosable instead of
    # being another silent kill — the previous one took a root-only profiler to even locate.
    # SIGUSR1 does the same on demand without killing anything.
    import faulthandler, signal, threading as _th
    try:
        faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)
    except Exception:
        pass
    _budget = float(os.environ.get("ORCH_MERGE_TRAIN_MAX_RUNTIME_S", "7200") or 7200)
    if _budget > 0:
        def _deadline():
            time.sleep(_budget)
            sys.stderr.write(f"merge_train: WATCHDOG — pass exceeded {_budget:.0f}s; "
                             f"dumping all threads and exiting so the single-flight lock "
                             f"is released for the next pass\n")
            sys.stderr.flush()
            try:
                faulthandler.dump_traceback(all_threads=True)
            except Exception:
                pass
            sys.stderr.flush()
            os._exit(3)
        _th.Thread(target=_deadline, name="merge-train-watchdog", daemon=True).start()

    print(json.dumps(train_run(), indent=2, default=str))
