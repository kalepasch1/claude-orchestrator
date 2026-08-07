"""Tests for runner/intent_classifier.py.

These build real git repositories in a tmpdir rather than mocking subprocess. The whole
point of the classifier is that it reads git correctly; a mocked git would test the mock.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intent_classifier import (  # noqa: E402
    ALREADY_SATISFIED,
    CONTEXT_MOVED,
    SUPERSEDED_OR_UNSAFE,
    UNCHANGED_CONTEXT,
    UNCLASSIFIABLE,
    classify,
    is_source_path,
    would_revert_newer_work,
)


def git(repo, *args):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout.strip()


def write(repo, path, content):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(content)


def commit(repo, message):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message,
        "--no-verify")


@pytest.fixture
def repo(tmp_path):
    """A repo on master with one file, plus a branch cut from it."""
    r = str(tmp_path / "repo")
    os.makedirs(r)
    git(r, "init", "-q", "-b", "master")
    write(r, "src/app.py", "def f():\n    return 1\n")
    write(r, "src/other.py", "OTHER = 1\n")
    commit(r, "base")
    return r


def cut_branch(repo, name, path="src/app.py", content="def f():\n    return 2\n"):
    git(repo, "checkout", "-q", "-b", name)
    write(repo, path, content)
    commit(repo, f"work on {name}")
    git(repo, "checkout", "-q", "master")
    return name


# ── ALREADY_SATISFIED ────────────────────────────────────────────────────────

def test_already_satisfied_when_branch_is_ancestor_of_prod(repo):
    """Intent present in prod -> closed with evidence, nothing to re-apply."""
    cut_branch(repo, "agent/landed")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge", "agent/landed")

    c = classify(repo, "agent/landed", "master")

    assert c.verdict == ALREADY_SATISFIED
    assert c.should_reapply is False
    assert c.evidence["check"] == "merge-base --is-ancestor"
    assert c.evidence["branch_sha"]


def test_already_satisfied_when_branch_touches_only_generated_files(repo):
    """A branch whose whole diff is lockfiles/vendor has nothing to recover."""
    git(repo, "checkout", "-q", "-b", "agent/noise")
    write(repo, "package-lock.json", '{"lockfileVersion": 3}\n')
    write(repo, "node_modules/x/index.js", "module.exports = 1\n")
    commit(repo, "noise only")
    git(repo, "checkout", "-q", "master")

    c = classify(repo, "agent/noise", "master")

    assert c.verdict == ALREADY_SATISFIED
    assert c.evidence["filter"] == "is_source_path"
    assert c.should_reapply is False


# ── UNCHANGED_CONTEXT ────────────────────────────────────────────────────────

def test_unchanged_context_when_prod_has_not_moved(repo):
    cut_branch(repo, "agent/clean")

    c = classify(repo, "agent/clean", "master")

    assert c.verdict == UNCHANGED_CONTEXT
    assert c.should_reapply is True
    assert c.touched_files == ["src/app.py"]
    assert c.moved_files == []


def test_unchanged_context_when_prod_moved_in_a_different_file(repo):
    """Prod advancing elsewhere must not be mistaken for the context moving."""
    cut_branch(repo, "agent/clean")
    write(repo, "src/other.py", "OTHER = 2\n")
    commit(repo, "unrelated prod work")

    c = classify(repo, "agent/clean", "master")

    assert c.verdict == UNCHANGED_CONTEXT
    assert c.moved_files == []


# ── CONTEXT_MOVED ────────────────────────────────────────────────────────────

def test_context_moved_when_touched_file_rewritten_on_prod(repo):
    """Touched symbol rewritten -> re-implementation path, stale diff NOT applied."""
    cut_branch(repo, "agent/stale")
    write(repo, "src/app.py", "def f(x):\n    return x * 10\n")
    commit(repo, "prod rewrote f")

    c = classify(repo, "agent/stale", "master")

    assert c.verdict == CONTEXT_MOVED
    assert c.should_reapply is False, "a stale diff must never be auto-ported"
    assert c.moved_files == ["src/app.py"]
    assert "re-implement" in c.reason


def test_context_moved_rejects_change_that_would_revert_newer_work(repo):
    """The auto-resolve lesson, enforced: overlap with newer prod edits is flagged."""
    cut_branch(repo, "agent/stale")
    write(repo, "src/app.py", "def f(x):\n    return x * 10\n")
    commit(repo, "prod rewrote f")

    c = classify(repo, "agent/stale", "master")
    assert c.evidence["would_revert_newer_work"] is True

    reverts, overlap, err = would_revert_newer_work(repo, "agent/stale", "master")
    assert err is None
    assert reverts is True
    assert overlap == ["src/app.py"]


def test_would_revert_newer_work_false_when_no_overlap(repo):
    cut_branch(repo, "agent/clean")
    write(repo, "src/other.py", "OTHER = 2\n")
    commit(repo, "unrelated prod work")

    reverts, overlap, err = would_revert_newer_work(repo, "agent/clean", "master")

    assert err is None
    assert reverts is False
    assert overlap == []


# ── SUPERSEDED_OR_UNSAFE ─────────────────────────────────────────────────────

@pytest.mark.parametrize("state", ["QUARANTINED", "SUPERSEDED", "quarantined", "ABANDONED"])
def test_decided_states_never_silently_reversed(repo, state):
    """A prior decision outranks any git heuristic, and routes to the operator."""
    cut_branch(repo, "agent/clean")

    c = classify(repo, "agent/clean", "master", task_state=state)

    assert c.verdict == SUPERSEDED_OR_UNSAFE
    assert c.needs_operator is True
    assert c.should_reapply is False
    assert c.evidence["task_state"] == state


def test_decided_state_checked_before_git(tmp_path):
    """Even with an unusable repo, a decided state still classifies — order matters."""
    c = classify(str(tmp_path / "nope"), "agent/x", "master", task_state="SUPERSEDED")
    assert c.verdict == SUPERSEDED_OR_UNSAFE


# ── UNCLASSIFIABLE ───────────────────────────────────────────────────────────

def test_missing_repo_is_unclassifiable_not_a_guess(tmp_path):
    c = classify(str(tmp_path / "absent"), "agent/x", "master")

    assert c.verdict == UNCLASSIFIABLE
    assert c.needs_operator is True
    assert c.should_reapply is False


def test_missing_branch_is_unclassifiable(repo):
    c = classify(repo, "agent/never-existed", "master")

    assert c.verdict == UNCLASSIFIABLE
    assert "does not resolve" in c.reason


def test_missing_prod_branch_is_unclassifiable(repo):
    cut_branch(repo, "agent/clean")

    c = classify(repo, "agent/clean", "no-such-prod-branch")

    assert c.verdict == UNCLASSIFIABLE
    assert c.needs_operator is True


# ── Invariants ───────────────────────────────────────────────────────────────

def test_every_verdict_carries_evidence_and_a_reason(repo, tmp_path):
    cut_branch(repo, "agent/clean")
    cut_branch(repo, "agent/stale", content="def f():\n    return 3\n")
    write(repo, "src/app.py", "def f(x):\n    return x\n")
    commit(repo, "prod moved")

    results = [
        classify(repo, "agent/stale", "master"),
        classify(repo, "agent/clean", "master", task_state="QUARANTINED"),
        classify(str(tmp_path / "absent"), "agent/x", "master"),
    ]

    for c in results:
        assert c.reason, f"{c.verdict} produced no reason"
        assert c.evidence, f"{c.verdict} produced no evidence"
        assert c.to_dict()["verdict"] == c.verdict


def test_classify_is_read_only(repo):
    """The classifier must not move HEAD, create refs, or dirty the tree."""
    cut_branch(repo, "agent/clean")
    head_before = git(repo, "rev-parse", "HEAD")
    refs_before = git(repo, "for-each-ref", "--format=%(refname)")

    classify(repo, "agent/clean", "master")

    assert git(repo, "rev-parse", "HEAD") == head_before
    assert git(repo, "for-each-ref", "--format=%(refname)") == refs_before
    assert git(repo, "status", "--porcelain") == ""


def test_classification_is_deterministic(repo):
    cut_branch(repo, "agent/clean")
    a = classify(repo, "agent/clean", "master")
    b = classify(repo, "agent/clean", "master")
    assert a.to_dict() == b.to_dict()


@pytest.mark.parametrize("path,expected", [
    ("src/app.py", True),
    ("server/utils/x.ts", True),
    ("package-lock.json", False),
    ("node_modules/x/index.js", False),
    ("dist/bundle.js", False),
    ("app.min.js", False),
    ("coverage/lcov.info", False),
    ("logo.png", False),
    ("vendor/lib.go", False),
    ("", False),
])
def test_source_path_filter(path, expected):
    """The filter that keeps published line counts defensible."""
    assert is_source_path(path) is expected
