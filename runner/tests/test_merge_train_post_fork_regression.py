"""The second wipe vector must stay guarded.

_post_fork_regression is the merge train's defence against a CLEAN rebase that
silently deletes improvements which landed on base AFTER the branch forked. It
produces no git conflict, so nothing else catches it — and it had no test at
all, which is how a guard quietly stops guarding.

The scenario each test builds is the real one:
    fork -> base gains an improvement -> the branch, which never saw it,
    rewrites the same file -> rebase is clean -> the improvement is gone.

Every test builds a throwaway git repo under tmp_path. Nothing runs git against
this checkout, and the guard is read-only (two `git diff` calls).
"""
import os
import subprocess
import sys

import pytest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

import merge_train as mt  # noqa: E402


IMPROVEMENT = [
    "def validate_input(payload):",
    "    if not isinstance(payload, dict):",
    "        return False",
    "    return bool(payload.get('id'))",
]


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True, timeout=30)


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message)


@pytest.fixture()
def scenario(tmp_path):
    """Returns (repo, fork_sha). base has the improvement; the branch does not."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "master")
    target = repo / "mod.py"
    target.write_text("def existing():\n    return 1\n")
    _commit(repo, "seed")
    fork = _git(repo, "rev-parse", "HEAD").stdout.strip()

    _git(repo, "checkout", "-b", "agent/work")
    _git(repo, "checkout", "master")
    # base gains the improvement AFTER the fork point
    target.write_text("def existing():\n    return 1\n\n\n" + "\n".join(IMPROVEMENT) + "\n")
    _commit(repo, "improvement lands on base")
    return repo, fork


def _branch_rewrites(repo, body):
    _git(repo, "checkout", "agent/work")
    (repo / "mod.py").write_text(body)
    _commit(repo, "branch rewrite")
    _git(repo, "checkout", "master")


class TestDetectsTheWipe:
    def test_branch_that_drops_the_improvement_is_held(self, scenario):
        repo, fork = scenario
        # The branch never saw the improvement and rewrites the file without it.
        _branch_rewrites(repo, "def existing():\n    return 2\n")
        ok, detail = mt._post_fork_regression(repo, "agent/work", "master", fork)
        assert ok is False
        assert "mod.py" in detail

    def test_detail_reports_how_many_improved_lines_are_lost(self, scenario):
        repo, fork = scenario
        _branch_rewrites(repo, "def existing():\n    return 2\n")
        _, detail = mt._post_fork_regression(repo, "agent/work", "master", fork)
        assert "recently-improved lines" in detail


class TestAllowsLegitimateWork:
    def test_branch_that_keeps_the_improvement_passes(self, scenario):
        repo, fork = scenario
        kept = ("def existing():\n    return 2\n\n\n" + "\n".join(IMPROVEMENT) + "\n")
        _branch_rewrites(repo, kept)
        ok, detail = mt._post_fork_regression(repo, "agent/work", "master", fork)
        assert ok is True
        assert detail == ""

    def test_a_branch_that_only_adds_passes(self, scenario):
        repo, fork = scenario
        added = ("def existing():\n    return 1\n\n\n" + "\n".join(IMPROVEMENT)
                 + "\n\n\ndef brand_new():\n    return 'new work'\n")
        _branch_rewrites(repo, added)
        ok, _ = mt._post_fork_regression(repo, "agent/work", "master", fork)
        assert ok is True

    def test_losing_fewer_lines_than_the_threshold_passes(self, scenario, monkeypatch):
        """The threshold is what separates a real wipe from incidental churn."""
        repo, fork = scenario
        monkeypatch.setenv("MERGE_REGRESSION_LINE_THRESHOLD", "99")
        _branch_rewrites(repo, "def existing():\n    return 2\n")
        ok, _ = mt._post_fork_regression(repo, "agent/work", "master", fork)
        assert ok is True

    def test_threshold_is_configurable_downwards(self, scenario, monkeypatch):
        repo, fork = scenario
        monkeypatch.setenv("MERGE_REGRESSION_LINE_THRESHOLD", "1")
        _branch_rewrites(repo, "def existing():\n    return 2\n")
        ok, _ = mt._post_fork_regression(repo, "agent/work", "master", fork)
        assert ok is False


class TestFailOpen:
    """A guard that blocks the train on its own errors is worse than the wipe."""

    def test_no_fork_point_passes(self, scenario):
        repo, _ = scenario
        assert mt._post_fork_regression(repo, "agent/work", "master", "") == (True, "")

    def test_none_fork_point_passes(self, scenario):
        repo, _ = scenario
        assert mt._post_fork_regression(repo, "agent/work", "master", None) == (True, "")

    def test_broken_git_passes(self, scenario, monkeypatch):
        repo, fork = scenario

        def boom(*a, **k):
            raise OSError("git not found")

        monkeypatch.setattr(mt.subprocess, "run", boom)
        assert mt._post_fork_regression(repo, "agent/work", "master", fork) == (True, "")

    def test_unknown_refs_pass(self, scenario):
        repo, fork = scenario
        ok, _ = mt._post_fork_regression(repo, "agent/nope", "master", fork)
        assert ok is True
