#!/usr/bin/env python3
"""
self_deploy.py - merged code takes effect WITHOUT a human restart. hot_reload.py already
live-swaps leaf modules, but the entrypoint (runner.py) and low-level modules are excluded;
this closes that gap with a cooperative, test-gated restart:

  reconcile_origin(repo)-> absorb origin/master into the local deployable head, so a PR
                           merged on origin actually reaches the running fleet. Fast-forward
                           when purely behind; merge only when `git merge-tree` proves the
                           merge is conflict-free; report (never force-resolve) otherwise.
  check_new_code(repo)  -> {"running_commit","head_commit","stale"}: the commit the runner
                           BOOTED on (env ORCH_BOOT_COMMIT, else <repo>/.runner_boot_commit)
                           vs current git HEAD.
  canary_gate(repo)     -> compile the runner, collect the complete test suite, then run a
                           bounded critical + change-matched test set, all inside an
                           EPHEMERAL CHECKOUT PINNED TO THE CANDIDATE COMMIT — never the
                           live tree, which the fleet keeps committing to while the gate
                           runs. True only when every stage exits 0. This keeps the restart
                           gate passable as the full suite grows while still failing closed
                           on syntax, collection and relevant behavioral regressions.
  request_restart(why)  -> touch runner/.restart_requested (reason + timestamp) AND insert a
                           notifications digest row. The MAIN LOOP (wired separately) checks
                           this file BETWEEN tasks and sys.exit(0)s cleanly; keepalive.sh
                           then restarts into the new code. No hard kills, no forced exits —
                           always cooperative, so in-flight tasks finish first.
  maybe_deploy(repo)    -> full flow: stale? -> canary gate -> request restart. On canary
                           failure it files a kind='self' approvals card instead (unique
                           partial index on (kind,title) may reject dupes — caught+ignored).
                           Never raises; safe to call every loop.
"""
import glob, os, sys, datetime, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_DIR = os.path.dirname(os.path.abspath(__file__))
RESTART_FLAG = os.path.join(_DIR, ".restart_requested")
BOOT_FILE = ".runner_boot_commit"
BLOCK_TITLE = "Self-deploy blocked: bounded release canary failed"
# The old gate ran all 8,599+ tests under one fixed timeout. It first failed during
# collection, then (after collection was repaired) simply timed out after 900 seconds.
# A restart safety check must be bounded independently of total suite size.
CANARY_TIMEOUT = int(os.environ.get("ORCH_CANARY_TIMEOUT", "300"))
CANARY_COLLECTION_TIMEOUT = int(os.environ.get("ORCH_CANARY_COLLECTION_TIMEOUT", "180"))
CANARY_MAX_CHANGED_TESTS = int(os.environ.get("ORCH_CANARY_MAX_CHANGED_TESTS", "60"))
# The gate used to run in the LIVE tree — the one the fleet is committing to while the
# gate runs. A four-minute canary was therefore verifying a moving target: files changed
# mid-run, uncommitted cruft (conflict markers, half-applied merges) was read as if it
# were the candidate, and load from the same tree's workers pushed per-test timeouts over.
# Pinning to a clean detached checkout of the exact candidate SHA makes the gate verify
# the thing it is about to deploy, and nothing else.
CANARY_PINNED = (os.environ.get("ORCH_CANARY_PINNED", "1").strip().lower()
                 not in ("0", "false", "no", "off"))
CANARY_WORKTREE_DIR = os.environ.get("ORCH_CANARY_WORKTREE_DIR", "")
CANARY_WORKTREE_TIMEOUT = int(os.environ.get("ORCH_CANARY_WORKTREE_TIMEOUT", "300"))
# Enough of both ends that canary_triage can classify the failure. The old tail-only
# 2000 chars routinely captured nothing but a daemon thread's stack from a timeout dump.
GATE_LOG_HEAD = int(os.environ.get("ORCH_CANARY_LOG_HEAD", "3000"))
GATE_LOG_TAIL = int(os.environ.get("ORCH_CANARY_LOG_TAIL", "6000"))

# These protect the exact path that turns merged code into running code, plus the release
# truth/terminal-state fixes that prevent "merged" from being mistaken for "visible".
CRITICAL_CANARY_TESTS = (
    "runner/tests/test_self_deploy.py",
    "runner/tests/test_self_deploy_canary.py",
    "runner/tests/test_self_deploy_boot_marker.py",
    "runner/tests/test_all_modules_importable.py",
    "runner/tests/test_runner_core.py",
    "runner/tests/test_integration_sweeper.py",
    "runner/tests/test_merge_truth.py",
    "runner/tests/test_phantom_recovery.py",
    "runner/tests/test_production_push_guard.py",
    "runner/tests/test_release_manifest_binding.py",
    "runner/tests/test_release_push_fast_forward.py",
)


# --- origin tracking -------------------------------------------------------
# self_deploy compares the RUNNING commit to the LOCAL HEAD. Nothing in that loop ever
# consulted the remote, so a PR merged on origin was invisible to the running fleet: the
# node's master kept advancing on its own direct-to-master commits, self_deploy reported
# "up-to-date" against that local head, and every merged PR sat on origin without ever
# executing. reconcile_origin() closes that gap before staleness is evaluated.
ORIGIN_REMOTE = os.environ.get("ORCH_ORIGIN_REMOTE", "origin")
ORIGIN_BRANCH = os.environ.get("ORCH_ORIGIN_BRANCH", "master")
TRACK_ORIGIN = (os.environ.get("ORCH_SELF_DEPLOY_TRACK_ORIGIN", "1").strip().lower()
                not in ("0", "false", "no", "off"))
ORIGIN_FETCH_TIMEOUT = int(os.environ.get("ORCH_ORIGIN_FETCH_TIMEOUT", "120"))
ORIGIN_GIT_TIMEOUT = int(os.environ.get("ORCH_ORIGIN_GIT_TIMEOUT", "60"))
DIVERGENCE_TITLE = "Self-deploy blocked: local master conflicts with origin"


def _git(repo, args, timeout=None):
    """Run a git command in repo. CompletedProcess, or None when it could not run."""
    try:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              text=True, timeout=timeout or ORIGIN_GIT_TIMEOUT)
    except Exception:
        return None


def _git_ok(repo, args, timeout=None):
    r = _git(repo, args, timeout)
    return bool(r) and r.returncode == 0


def _is_ancestor(repo, a, b):
    """True when commit a is already contained in commit b."""
    return _git_ok(repo, ["merge-base", "--is-ancestor", a, b])


def _resolve(repo, rev):
    """Full SHA for rev, or '' — a pin must never guess which commit it is verifying."""
    r = _git(repo, ["rev-parse", rev or "HEAD"])
    return r.stdout.strip() if r and r.returncode == 0 else ""


def _remote_head(repo):
    """SHA of the freshly fetched remote branch. Empty string when unresolvable."""
    for ref in (f"{ORIGIN_REMOTE}/{ORIGIN_BRANCH}", "FETCH_HEAD"):
        r = _git(repo, ["rev-parse", ref])
        if r and r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return ""


def _file_divergence_card(behind, remote_sha):
    try:
        db.insert("approvals", {
            "project": "ORCHESTRATOR", "kind": "self", "title": DIVERGENCE_TITLE,
            "why": f"{behind} commit(s) merged on {ORIGIN_REMOTE}/{ORIGIN_BRANCH} "
                   f"({remote_sha[:8]}) cannot be merged into this node's master without "
                   f"conflicts, so already-merged work is not running here.",
            "value": "Resolve the divergence once and every merged PR goes live.",
            "risk": "None — nothing was force-resolved; the running code keeps serving.",
            "command": f"git merge {ORIGIN_REMOTE}/{ORIGIN_BRANCH}"})
    except Exception:
        pass  # unique partial index on (kind,title) rejects duplicates — fine


def reconcile_origin(repo):
    """Make the deployable HEAD contain everything already merged on origin.

    Non-destructive by construction — this runs against the live tree the fleet is
    executing, so it may never discard local work:
      * fast-forward when this node is purely behind;
      * otherwise merge ONLY after `git merge-tree` proves in memory that the merge is
        conflict-free, so the working tree is never left holding conflict markers (that
        exact failure mode stalled the whole fleet — see auto_conflict_resolver);
      * a conflicting divergence is REPORTED, never force-resolved, never reset --hard.

    Never raises. Returns a dict describing what happened.
    """
    if not TRACK_ORIGIN:
        return {"tracked": False, "ok": True, "action": "disabled"}
    if not _git_ok(repo, ["fetch", ORIGIN_REMOTE, ORIGIN_BRANCH], ORIGIN_FETCH_TIMEOUT):
        return {"tracked": True, "ok": False, "action": "fetch_failed"}
    remote, head = _remote_head(repo), current_commit(repo)
    if not remote or not head:
        return {"tracked": True, "ok": False, "action": "no_refs"}
    if _is_ancestor(repo, remote, head):
        return {"tracked": True, "ok": True, "action": "already_current",
                "remote": remote, "behind": 0}
    r = _git(repo, ["rev-list", "--count", f"{head}..{remote}"])
    out = (r.stdout.strip() if r and r.returncode == 0 else "")
    behind = int(out) if out.isdigit() else 0
    if _is_ancestor(repo, head, remote):
        if _git_ok(repo, ["merge", "--ff-only", remote]):
            print(f"self_deploy: fast-forwarded to {ORIGIN_REMOTE}/{ORIGIN_BRANCH} "
                  f"{remote[:8]} (+{behind})")
            return {"tracked": True, "ok": True, "action": "fast_forward",
                    "remote": remote, "behind": behind}
        return {"tracked": True, "ok": False, "action": "fast_forward_failed",
                "remote": remote, "behind": behind}
    mt = _git(repo, ["merge-tree", "--write-tree", head, remote])
    if mt is None or mt.returncode not in (0, 1):
        # Unsupported/erroring merge-tree must not be misread as "conflicted": say so and
        # leave the tree alone rather than merging blind.
        return {"tracked": True, "ok": False, "action": "merge_check_unavailable",
                "remote": remote, "behind": behind}
    if mt.returncode == 1:
        print(f"self_deploy: local {ORIGIN_BRANCH} conflicts with {ORIGIN_REMOTE}/"
              f"{ORIGIN_BRANCH} {remote[:8]} (+{behind}) — reporting, not force-resolving")
        _file_divergence_card(behind, remote)
        return {"tracked": True, "ok": False, "action": "conflicted",
                "remote": remote, "behind": behind}
    if not _git_ok(repo, ["merge", "--no-edit", remote]):
        _git(repo, ["merge", "--abort"])
        print(f"self_deploy: merge of {ORIGIN_REMOTE}/{ORIGIN_BRANCH} {remote[:8]} could "
              f"not be applied to the working tree — aborted, nothing changed")
        return {"tracked": True, "ok": False, "action": "merge_failed",
                "remote": remote, "behind": behind}
    print(f"self_deploy: absorbed {behind} commit(s) from {ORIGIN_REMOTE}/"
          f"{ORIGIN_BRANCH} {remote[:8]}")
    return {"tracked": True, "ok": True, "action": "merged", "remote": remote,
            "behind": behind}


def current_commit(repo):
    """git HEAD of repo (read-only). Empty string if git fails."""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def running_commit(repo):
    """Commit the current process booted on: env ORCH_BOOT_COMMIT, else boot file."""
    c = (os.environ.get("ORCH_BOOT_COMMIT") or "").strip()
    if c:
        return c
    try:
        with open(os.path.join(repo, BOOT_FILE)) as f:
            return f.read().strip()
    except OSError:
        return ""


def record_boot(repo, commit=None):
    """Stamp the commit this runner booted on. Call ONCE at process start.

    Without this the marker never exists, running_commit() returns "", and
    check_new_code()["stale"] is always False — so self-deploy can never fire and
    merged code never reaches the running fleet until a human restarts it. That is
    the "sentinel: stale-code-unknown" state observed continuously since 2026-07-16.

    Deliberately NOT called from a monitor or sentinel: writing the marker after boot
    would stamp the CURRENT head onto an OLD process and permanently hide staleness,
    which is worse than not knowing. Only the launcher may write it.
    """
    c = (commit or current_commit(repo) or "").strip()
    if not c:
        return ""
    try:
        with open(os.path.join(repo, BOOT_FILE), "w") as f:
            f.write(c + "\n")
    except OSError:
        return ""
    return c


def check_new_code(repo):
    run_c, head = running_commit(repo), current_commit(repo)
    return {"running_commit": run_c, "head_commit": head,
            "stale": bool(run_c and head and run_c != head),
            # Distinguishable from stale=False-because-current: a missing marker means
            # we CANNOT TELL, which must not be reported as healthy.
            "unknown": not bool(run_c)}


def _pytest_timeout_available():
    try:
        r = subprocess.run(["python3", "-c", "import pytest_timeout"],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _changed_files(repo, base_commit, head_commit="HEAD"):
    """Return paths changed across the boot-to-head boundary, or None on git failure."""
    if not base_commit:
        return None
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMRT", base_commit, head_commit],
            cwd=repo, capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return [line.strip() for line in (r.stdout or "").splitlines() if line.strip()]


def _selected_tests(repo, changed_files):
    """Critical smoke tests plus tests directly changed by, or named for, changed modules."""
    selected = {p for p in CRITICAL_CANARY_TESTS if os.path.isfile(os.path.join(repo, p))}
    for rel in changed_files or ():
        if not rel.startswith("runner/") or not rel.endswith(".py"):
            continue
        base = os.path.basename(rel)
        if base.startswith("test_") and os.path.isfile(os.path.join(repo, rel)):
            selected.add(rel)
        if base.startswith("test_"):
            continue
        stem = os.path.splitext(base)[0]
        patterns = (f"runner/tests/test_{stem}*.py", f"runner/test_{stem}*.py")
        for pattern in patterns:
            for path in glob.glob(os.path.join(repo, pattern)):
                selected.add(os.path.relpath(path, repo))
    # A huge batch must not turn the bounded gate back into the full-suite gate. The critical
    # set is always retained; directly relevant additions are deterministic and capped.
    critical = [p for p in CRITICAL_CANARY_TESTS if p in selected]
    relevant = sorted(selected.difference(critical))[:max(0, CANARY_MAX_CHANGED_TESTS)]
    return critical + relevant


def _excerpt(text):
    """Head AND tail of gate output.

    Tail-only truncation kept losing the failure itself: a pytest-timeout dump ends with
    an idle daemon thread's stack, so the log carried that and nothing about the test that
    actually hung — and canary_triage classifies from this text.
    """
    t = (text or "").strip()
    if len(t) <= GATE_LOG_HEAD + GATE_LOG_TAIL:
        return t
    dropped = len(t) - GATE_LOG_HEAD - GATE_LOG_TAIL
    return (t[:GATE_LOG_HEAD] + f"\n... [{dropped} chars omitted] ...\n" + t[-GATE_LOG_TAIL:])


def _run_gate_stage(label, cmd, workdir, timeout):
    try:
        r = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"self_deploy: {label} timed out after {timeout}s")
        return False
    except Exception as e:
        print(f"self_deploy: {label} failed to run ({e})")
        return False
    if r.returncode != 0:
        detail = _excerpt((r.stdout or "") + (r.stderr or ""))
        print(f"self_deploy: {label} red (rc={r.returncode})" +
              (f"\n{detail}" if detail else ""))
        return False
    return True


def _canary_worktree_path(repo):
    return CANARY_WORKTREE_DIR or os.path.join(repo, ".runtime", "canary-pin")


def pin_checkout(repo, commit):
    """Clean detached checkout of `commit`, or None when one cannot be made.

    None is not a failure of the gate — the caller falls back to the live tree. A canary
    that refused to run because a worktree could not be created would be a new way to
    stall the fleet, and stalling the fleet is the thing being fixed.
    """
    if not CANARY_PINNED or not commit:
        return None
    path = _canary_worktree_path(repo)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        return None
    unpin(repo, path)  # a leftover from a killed run must not be reused
    r = _git(repo, ["worktree", "add", "--detach", "--force", path, commit],
             CANARY_WORKTREE_TIMEOUT)
    if r is None or r.returncode != 0:
        print("self_deploy: could not pin a clean checkout "
              f"({(r.stderr or '').strip()[:200] if r else 'git failed'}) — "
              "falling back to the live tree")
        return None
    return path


def unpin(repo, path):
    """Remove the pinned checkout. Best effort; never raises."""
    if not path:
        return
    _git(repo, ["worktree", "remove", "--force", path], CANARY_WORKTREE_TIMEOUT)
    if os.path.exists(path):
        try:
            import shutil
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass
    _git(repo, ["worktree", "prune"])


def canary_gate(repo, base_commit=None, head_commit="HEAD"):
    """Bounded, fail-closed restart gate independent of total test-suite duration.

    The full suite is still collected, so syntax/import/collection failures anywhere stop
    deployment. Runtime assertions are exercised for the self-deploy/release critical path
    and for tests matched to every changed runner module. Unlike the former failure-count
    baseline, a red selected test can never be accepted merely because it was already red.
    """
    base = (base_commit or running_commit(repo) or "").strip()
    changed = _changed_files(repo, base, head_commit)
    if changed is None:
        print("self_deploy: cannot establish boot-to-head diff — failing closed")
        return False

    # Verify the candidate itself, in isolation from the tree the fleet is still writing to.
    candidate = _resolve(repo, head_commit)
    pinned = pin_checkout(repo, candidate)
    workdir = pinned or repo
    if pinned:
        print(f"self_deploy: canary pinned to a clean checkout of {candidate[:8]}")
    try:
        if not _run_gate_stage(
                "compile gate", ["python3", "-m", "compileall", "-q", "runner"],
                workdir, min(CANARY_TIMEOUT, 120)):
            return False

        collect = ["python3", "-m", "pytest", "runner/tests", "--collect-only", "-q"]
        if not _run_gate_stage("collection gate", collect, workdir,
                               CANARY_COLLECTION_TIMEOUT):
            return False

        tests = _selected_tests(workdir, changed)
        if not tests:
            print("self_deploy: no critical canary tests found — failing closed")
            return False
        cmd = ["python3", "-m", "pytest", *tests, "-q", "-x"]
        if _pytest_timeout_available():
            cmd.append("--timeout=120")
        return _run_gate_stage("bounded behavior gate", cmd, workdir, CANARY_TIMEOUT)
    finally:
        unpin(repo, pinned)


def request_restart(reason):
    """Cooperative restart signal: flag file + digest notification. Never kills anything."""
    ts = datetime.datetime.utcnow().isoformat()
    with open(RESTART_FLAG, "w") as f:
        f.write(f"{ts} {reason}\n")
    try:
        db.insert("notifications", {
            "channel": "digest",
            "audience": os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com"),
            "kind": "self_deploy",
            "title": f"[self-deploy] restart requested: {reason}",
            "body": "Runner will exit cleanly between tasks; keepalive.sh restarts it "
                    "into the new code. No work is interrupted.",
            "sent": False})
    except Exception:
        pass
    return RESTART_FLAG


def _file_blocked_card():
    try:
        db.insert("approvals", {
            "project": "ORCHESTRATOR", "kind": "self", "title": BLOCK_TITLE,
            "why": "New commits are on master but the bounded compile/collection/behavior "
                   "release canary is red; "
                   "self-deploy is holding the running (green) version.",
            "value": "Fix the failing tests (or revert) and the next cycle deploys itself.",
            "risk": "None — the currently-running code keeps serving.", "command": ""})
    except Exception:
        pass  # unique partial index on (kind,title) rejects duplicates — fine


def maybe_deploy(repo=None):
    """Full self-deploy flow. Logs, never raises."""
    origin = {}
    try:
        repo = repo or os.path.dirname(_DIR)
        # Merged-on-origin has to become running-here. Absorb origin FIRST, so staleness
        # is judged against a head that actually contains the merged PRs.
        origin = reconcile_origin(repo)
        st = check_new_code(repo)
        if not st["stale"]:
            print(f"self_deploy: up-to-date "
                  f"(running={st['running_commit'][:8] or '?'})")
            return {"deployed": False, "reason": "up-to-date", "origin": origin, **st}
        print(f"self_deploy: new code {st['head_commit'][:8]} "
              f"(running {st['running_commit'][:8]}) — running canary gate")
        if not canary_gate(repo, st["running_commit"], st["head_commit"]):
            print("self_deploy: BLOCKED — tests failing; filing approvals card")
            _file_blocked_card()
            return {"deployed": False, "reason": "canary_failed", "origin": origin, **st}
        request_restart(f"new code {st['head_commit'][:8]} passed canary gate")
        print(f"self_deploy: restart requested into {st['head_commit'][:8]}")
        return {"deployed": True, "reason": "restart_requested", "origin": origin, **st}
    except Exception as e:
        print(f"self_deploy: skipped ({e})")
        return {"deployed": False, "reason": f"error: {e}", "origin": origin}


if __name__ == "__main__":
    import json
    print(json.dumps(maybe_deploy(), indent=2))
