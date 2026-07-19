#!/usr/bin/env python3
"""Block direct production pushes unless the exact committed tree has a green release proof."""
from __future__ import annotations

import os
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
    roots = build_gate.dependency_prewarm.package_roots(repo)
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
    command = build_gate.detect_build_cmd(repo)
    if not command:
        return False, "No production build command could be detected."
    for kind in ("build", "vercel-build"):
        cached = proof_graph.reusable_verification(repo, commit, command, kind)
        if cached:
            return True, f"reused green {kind} proof for {commit[:12]}"
    if os.environ.get("ORCH_ALLOW_UNVERIFIED_PROD_PUSH", "").lower() in {"1", "true", "yes", "on"}:
        return True, "BREAK-GLASS override: ORCH_ALLOW_UNVERIFIED_PROD_PUSH is set"
    return False, (
        f"No green release-train proof exists for exact commit {commit[:12]} using `{command}`.\n"
        "Push the change to orchestrator/dev and let release_train verify/promote it.\n"
        "Emergency only: set ORCH_ALLOW_UNVERIFIED_PROD_PUSH=1 after independently verifying the committed tree."
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
        print(f"production_push_guard: GREEN — {log.splitlines()[0] if log else commit[:12]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
