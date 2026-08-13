#!/usr/bin/env python3
"""Block direct production pushes unless the exact committed tree is green — BUILD AND TESTS.

A green build proves the tree compiles. It says nothing about whether the code is correct, and
this guard used to stop there. On 2026-08-13 that gap was measured: master was serving
production with 14 failing tests across 8 files, some red for over a day, and every push had
been waved through because each one built cleanly. Among what was hiding behind them — a
production 404 on the first card of /licenses, a pricing module that threw
`TypeError: portfolio is not iterable` on every non-empty portfolio, and CEPL reading a
calibration field its own writer had renamed.

So the gate now requires both. See verify_tests().
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RUNNER_DIR)

import build_gate
import proof_graph

PRODUCTION_REFS = {"refs/heads/main", "refs/heads/master"}
ZERO_SHA = "0" * 40


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def guarded_updates(lines):
    updates = []
    for line in lines:
        fields = line.strip().split()
        if len(fields) != 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = fields
        if remote_ref in PRODUCTION_REFS and local_sha != ZERO_SHA:
            updates.append((local_ref, local_sha, remote_ref, remote_sha))
    return updates


def changes_affect_build(repo, old_commit, new_commit):
    """Skip nested deploy packages when a push changes only files outside their Vercel root."""
    if not old_commit or old_commit == ZERO_SHA:
        return True
    try:
        roots = build_gate.dependency_prewarm.package_roots(repo)
    except (AttributeError, TypeError):
        return True  # fail-open: if build_gate doesn't have this, assume changes matter
    if not roots:
        return True
    package_root = next((root for root in roots if os.path.isfile(os.path.join(root, "vercel.json"))), roots[0])
    rel = os.path.relpath(package_root, repo)
    if rel == ".":
        return True
    changed = _git(repo, "diff", "--name-only", old_commit, new_commit).splitlines()
    prefix = rel.rstrip("/") + "/"
    return any(path == rel or path.startswith(prefix) for path in changed)


def verify(repo, commit):
    try:
        command = build_gate.detect_build_cmd(repo)
    except (AttributeError, TypeError) as err:
        # Was `return True, "not available; allowing push"`. A guard that allows
        # the push when its own machinery is missing is not a guard — it reports
        # GREEN loudest exactly when it verified nothing.
        return False, f"build_gate.detect_build_cmd unavailable ({err}); refusing to certify an unverified tree."
    if not command:
        return False, "No production build command could be detected."
    try:
        for kind in ("build", "vercel-build"):
            cached = proof_graph.reusable_verification(repo, commit, command, kind)
            if cached:
                return True, f"reused green {kind} proof for {commit[:12]}"
    except (AttributeError, TypeError) as err:
        return False, f"proof_graph.reusable_verification unavailable ({err}); refusing to certify an unverified tree."
    if os.environ.get("ORCH_ALLOW_UNVERIFIED_PROD_PUSH", "").lower() in {"1", "true", "yes", "on"}:
        return True, "BREAK-GLASS override: ORCH_ALLOW_UNVERIFIED_PROD_PUSH is set"
    return False, (
        f"No green release-train proof exists for exact commit {commit[:12]} using `{command}`.\n"
        "Push the change to orchestrator/dev and let release_train verify/promote it.\n"
        "Emergency only: set ORCH_ALLOW_UNVERIFIED_PROD_PUSH=1 after independently verifying the committed tree."
    )


# ── TEST GATE ────────────────────────────────────────────────────────────────

TEST_SCRIPT_PREFERENCE = ("test:ci", "test:run", "test")


def _runner_for(package_root):
    """Pick the package manager the repo is ACTUALLY installed with.

    Not build_gate._package_runner. apparently carries BOTH package-lock.json and a
    stale pnpm-lock.yaml, and that helper answers "pnpm". Measured on 2026-08-13:
    `pnpm test` in that repo spends 100 seconds in pnpm's dependency-status check
    and then dies inside pnpm itself, having run zero tests. A gate wired to that
    would block every production push for a reason that has nothing to do with the
    code — which is the mirror image of the fail-open defect, and just as useless.

    The lockfile the deploy uses wins: vercel.json installs with `npm ci`.
    """
    has = lambda n: os.path.isfile(os.path.join(package_root, n))
    if has("package-lock.json"):
        return "npm"
    if has("pnpm-lock.yaml"):
        return "pnpm"
    if has("yarn.lock"):
        return "yarn"
    return "npm"


def detect_test_cmd(repo):
    """The repo's own full-suite command, from the deployable package's package.json.

    Deliberately mirrors build_gate.detect_build_cmd rather than importing it: the
    build gate is on the release train's hot path and this must not change its
    behaviour. Returns "" when the repo has no test script, which is not the same
    as a repo whose tests fail — see verify_tests.
    """
    try:
        roots = build_gate.dependency_prewarm.package_roots(repo)
    except (AttributeError, TypeError):
        return ""
    for root in roots or []:
        try:
            scripts = build_gate._load_scripts(root)
        except (AttributeError, TypeError):
            continue
        for name in TEST_SCRIPT_PREFERENCE:
            if name not in scripts:
                continue
            mgr = _runner_for(root)
            rel = os.path.relpath(root, repo)
            run = f"{mgr} run {name}" if mgr == "npm" else f"{mgr} {name}"
            return run if rel == "." else f"cd {shlex.quote(rel)} && {run}"
    return ""


def _tree_is_exactly(repo, commit):
    """True when the working tree is clean AND checked out at `commit`.

    A suite run only attests the tree it ran against. Running it while HEAD is
    elsewhere, or while files are modified, produces a result about a tree that
    is not the one being pushed — which is the whole class of defect this guard
    exists to stop.
    """
    try:
        head = _git(repo, "rev-parse", "HEAD")
        dirty = _git(repo, "status", "--porcelain")
    except subprocess.CalledProcessError:
        return False
    return head == commit and dirty == ""


def verify_tests(repo, commit):
    """Require a green full suite for this exact commit. Reuse a proof, or earn one."""
    command = detect_test_cmd(repo)
    if not command:
        return True, "no test script in package.json; nothing to gate on"

    try:
        if proof_graph.reusable_verification(repo, commit, command, "test"):
            return True, f"reused green test proof for {commit[:12]}"
    except (AttributeError, TypeError) as err:
        return False, f"proof_graph.reusable_verification unavailable ({err}); refusing to certify untested code."

    if not _tree_is_exactly(repo, commit):
        return False, (
            f"No green test proof exists for {commit[:12]}, and the working tree is not clean at that "
            "commit, so this guard cannot earn one — a suite run here would describe a different tree.\n"
            "Check out the exact commit with a clean tree, or push through orchestrator/dev."
        )

    print(f"production_push_guard: no test proof for {commit[:12]} — running `{command}`", file=sys.stderr)
    proc = subprocess.run(command, cwd=repo, shell=True, capture_output=True, text=True,
                          timeout=int(os.environ.get("ORCH_TEST_GATE_TIMEOUT", "1800")))
    passed = proc.returncode == 0
    try:
        proof_graph.record_verification(repo, commit, command, "test", passed)
    except (AttributeError, TypeError):
        pass  # recording is an optimisation; the verdict below is what gates.

    if passed:
        return True, f"full suite green for {commit[:12]}"
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-40:]
    return False, (
        f"FULL SUITE RED for {commit[:12]} using `{command}`.\n"
        "A green build only proves the tree compiles. These tests say it does not work.\n\n"
        + "\n".join(tail)
    )


def main(stdin=None):
    repo = _git(os.getcwd(), "rev-parse", "--show-toplevel")
    updates = guarded_updates(stdin if stdin is not None else sys.stdin)
    for _local_ref, commit, remote_ref, remote_commit in updates:
        if not changes_affect_build(repo, remote_commit, commit):
            print(f"production_push_guard: SKIPPED — no deploy-root changes for {remote_ref}", file=sys.stderr)
            continue
        print(f"production_push_guard: verifying {commit[:12]} for {remote_ref} in Vercel context", file=sys.stderr)
        ok, log = verify(repo, commit)
        if not ok:
            print("production_push_guard: BLOCKED red production push", file=sys.stderr)
            print(log[-6000:], file=sys.stderr)
            return 1
        print(f"production_push_guard: BUILD GREEN — {log.splitlines()[0] if log else commit[:12]}", file=sys.stderr)

        tests_ok, test_log = verify_tests(repo, commit)
        if not tests_ok:
            if os.environ.get("ORCH_ALLOW_UNVERIFIED_PROD_PUSH", "").lower() in {"1", "true", "yes", "on"}:
                print("production_push_guard: TESTS NOT VERIFIED — BREAK-GLASS override in effect", file=sys.stderr)
                print(test_log[-6000:], file=sys.stderr)
            else:
                print("production_push_guard: BLOCKED — production push without a green suite", file=sys.stderr)
                print(test_log[-6000:], file=sys.stderr)
                return 1
        else:
            print(f"production_push_guard: TESTS GREEN — {test_log.splitlines()[0]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
