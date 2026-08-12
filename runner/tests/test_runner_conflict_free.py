#!/usr/bin/env python3
"""The live runner is, and stays, conflict-marker free.

This is the named proof obligation of improve-queue-prevent-live-runner-merge-conflicts:
"a synthetic bad resolution leaves the live checkout and running commit unchanged".

It is deliberately split in two, because the two halves fail for different reasons and
a single combined test would hide which one broke:

  STANDING INVARIANT — the real checkout this file lives in has no conflict markers in
  any tracked source. This is the assertion that would have fired during the incident
  that motivated the module: `runner/*.py` containing `<<<<<<< HEAD`, imported by the
  next runner tick, crash-looping the live runner.

  MECHANISM — a merge whose resolution is invalid cannot write into the live checkout
  at all. Not "is rolled back afterwards": never written. The live working tree and the
  running commit must be byte-identical before and after, because a rollback still
  leaves a window in which a concurrent reader sees a broken tree.
"""
import os
import subprocess
import sys
import shutil
import tempfile

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(RUNNER)
sys.path.insert(0, RUNNER)

import isolated_merge_promotion as imp  # noqa: E402


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60)


def _write(repo, rel, text):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(text)


def _commit(repo, msg):
    _run(["git", "add", "-A"], repo)
    _run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg], repo)


def _head(repo, ref="HEAD"):
    return _run(["git", "rev-parse", ref], repo).stdout.strip()


def _worktree_fingerprint(path):
    """Content hash of the tracked working tree — catches edits a SHA compare misses."""
    out = _run(["git", "status", "--porcelain=v1", "--untracked-files=no"], path).stdout
    tree = _run(["git", "stash", "create"], path).stdout.strip()
    return (out, tree)


# ── standing invariant on the real checkout ─────────────────────────────────

def test_the_live_runner_checkout_has_no_conflict_markers():
    """The tree this test is running from must be clean. No fixture, the real thing."""
    found = imp.scan_conflict_markers(REPO)
    runner_hits = [f for f in found if f[0].startswith("runner/")]
    assert runner_hits == [], (
        "conflict markers present in the live runner sources — the next runner tick "
        f"would import them: {runner_hits[:10]}"
    )


def test_no_conflict_markers_anywhere_in_tracked_source():
    """Wider than runner/: a marker in any tracked text file is a failed resolution."""
    found = imp.scan_conflict_markers(REPO)
    assert found == [], f"conflict markers in tracked source: {found[:10]}"


# ── the mechanism: a bad resolution cannot reach the live checkout ───────────

@pytest.fixture
def live_repo():
    """A repo standing in for the live runner checkout, with a conflicting branch."""
    path = tempfile.mkdtemp(prefix="conflict-free-")
    _run(["git", "init", "-q", "-b", "master", "."], path)
    _run(["git", "config", "user.name", "t"], path)
    _run(["git", "config", "user.email", "t@t"], path)
    _write(path, "runner/mod.py", "VALUE = 1\n")
    _commit(path, "base")

    _run(["git", "checkout", "-q", "-b", "feature"], path)
    _write(path, "runner/mod.py", "VALUE = 3\n")
    _commit(path, "feature edit")
    _run(["git", "checkout", "-q", "master"], path)
    _write(path, "runner/mod.py", "VALUE = 2\n")
    _commit(path, "master edit")
    yield path
    shutil.rmtree(path, ignore_errors=True)


def test_failed_promotion_leaves_the_live_checkout_byte_identical(live_repo):
    before_head = _head(live_repo)
    before_print = _worktree_fingerprint(live_repo)
    before_source = open(os.path.join(live_repo, "runner/mod.py")).read()

    # A resolution that cannot validate: the branch introduces a syntax error, so the
    # merged tree fails compile smoke no matter how the textual conflict is resolved.
    _run(["git", "checkout", "-q", "feature"], live_repo)
    _write(live_repo, "runner/mod.py", "VALUE = (\n")
    _commit(live_repo, "broken feature edit")
    _run(["git", "checkout", "-q", "master"], live_repo)

    res = imp.promote_merge(live_repo, "feature", "master", run_tests=False)

    assert res["promoted"] is False, "an invalid resolution must not be promoted"
    assert _head(live_repo) == before_head, "the running commit moved"
    assert _worktree_fingerprint(live_repo) == before_print, "the live working tree changed"
    assert open(os.path.join(live_repo, "runner/mod.py")).read() == before_source
    assert imp.scan_conflict_markers(live_repo) == [], "markers landed in the live checkout"


def test_failed_promotion_preserves_both_refs(live_repo):
    """Quarantine, not discard: neither side may be lost when promotion fails."""
    feature_before = _head(live_repo, "feature")
    master_before = _head(live_repo, "master")

    _run(["git", "checkout", "-q", "feature"], live_repo)
    _write(live_repo, "runner/mod.py", "def broken(:\n")
    _commit(live_repo, "broken")
    feature_after_edit = _head(live_repo, "feature")
    _run(["git", "checkout", "-q", "master"], live_repo)

    res = imp.promote_merge(live_repo, "feature", "master", run_tests=False)

    assert res["promoted"] is False
    assert _head(live_repo, "master") == master_before, "base advanced on a failed merge"
    assert _head(live_repo, "feature") == feature_after_edit, "agent branch was rewritten"
    assert feature_before != feature_after_edit  # sanity: the fixture actually diverged


def test_marker_producing_resolution_is_caught_before_promotion(live_repo):
    """Markers in a file git considers RESOLVED still block promotion."""
    _run(["git", "checkout", "-q", "feature"], live_repo)
    _write(live_repo, "runner/mod.py",
           "VALUE = 1\n<<<<<<< HEAD\nVALUE = 2\n=======\nVALUE = 3\n>>>>>>> feature\n")
    _commit(live_repo, "committed markers")
    _run(["git", "checkout", "-q", "master"], live_repo)
    before_head = _head(live_repo)

    res = imp.promote_merge(live_repo, "feature", "master", run_tests=False)

    assert res["promoted"] is False
    assert _head(live_repo) == before_head
    assert imp.scan_conflict_markers(live_repo) == []


# The "gate is not a brick" direction — a valid resolution DOES promote — is already
# proven by test_isolated_merge_promotion.py::test_valid_resolution_promotes_atomically,
# which stubs the anti-loss guard for a bare fixture repo. Asserting it a second time
# here would be duplicate coverage of one behaviour, so this file stays focused on the
# invariant that file does not cover: the LIVE checkout is never written to.
