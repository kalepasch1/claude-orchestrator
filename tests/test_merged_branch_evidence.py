"""integration_sweeper: a merged branch that still EXISTS must close, not re-queue.

The auto-creator churn this guards against: the sweeper only asked "did this land?" on
the branch-MISSING path. A branch that still existed counted as `passed_waiting` and was
left open forever — including branches whose tip was already an ancestor of master. The
task stayed QUEUED, got re-claimed, and fresh `recover-missing-branch-*` rows were filed
to rebuild work that was already in production.

Asserted against REAL git repositories rather than mocks: the property under test is
reachability in the commit graph, and a stubbed `git` would only prove the stub agrees
with itself. The unsoundness modes documented on `_integration_evidence` — sibling slices
sharing a slug prefix, and a recovery commit that merely NAMES the slug — are asserted
explicitly, because reachability is precisely the predicate that is immune to them and a
regression back to message-grepping would pass a weaker test.
"""
import os
import subprocess
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
sys.modules.setdefault("db", types.ModuleType("db"))

import integration_sweeper as sweeper  # noqa: E402


def _git(repo, *args, env=None):
    e = dict(os.environ)
    e.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    if env:
        e.update(env)
    return subprocess.run(["git"] + list(args), cwd=repo, env=e,
                          capture_output=True, text=True, check=True)


def _commit(repo, name, text):
    (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"add {name}")


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A repo with origin/master, so the sweeper's target refs resolve."""
    # Pin the upstream candidates to master only; the default list leads with
    # orchestrator/dev, which does not exist in the fixture.
    monkeypatch.setenv("ORCH_STAGING_BRANCH", "master")
    monkeypatch.setenv("ORCH_CODE_MERGE_TARGET", "master")

    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "--initial-branch=master", ".")

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "--initial-branch=master", ".")
    _git(work, "remote", "add", "origin", str(origin))
    _commit(work, "base.txt", "base\n")
    _git(work, "push", "-u", "origin", "master")
    _git(work, "fetch", "origin")
    return work


def test_unmerged_branch_is_not_evidence(repo):
    _git(repo, "checkout", "-b", "agent/feature-x")
    _commit(repo, "x.txt", "work\n")
    _git(repo, "checkout", "master")

    assert sweeper._merged_branch_evidence(str(repo), "agent/feature-x") is None


def test_merged_branch_returns_tip_sha_and_ref(repo):
    _git(repo, "checkout", "-b", "agent/feature-x")
    _commit(repo, "x.txt", "work\n")
    tip = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "master")
    _git(repo, "merge", "--no-ff", "-m", "Merge agent/feature-x", "agent/feature-x")
    _git(repo, "push", "origin", "master")
    _git(repo, "fetch", "origin")

    result = sweeper._merged_branch_evidence(str(repo), "agent/feature-x")
    assert result is not None
    sha, ref = result
    # The sha must be the branch tip — the module invariant is that a MERGED row
    # carries the commit that proves it, not an arbitrary upstream sha.
    assert sha == tip
    assert ref.endswith("master")


def test_fast_forward_merge_is_also_detected(repo):
    """No merge commit exists in this shape, so message-based proof finds nothing."""
    _git(repo, "checkout", "-b", "agent/feature-ff")
    _commit(repo, "ff.txt", "work\n")
    tip = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "master")
    _git(repo, "merge", "--ff-only", "agent/feature-ff")
    _git(repo, "push", "origin", "master")
    _git(repo, "fetch", "origin")

    sha, _ref = sweeper._merged_branch_evidence(str(repo), "agent/feature-ff")
    assert sha == tip


def test_sibling_slice_sharing_a_prefix_is_not_certified(repo):
    """slice-1 landing must not certify slice-2 — the prefix-match unsoundness."""
    for name in ("agent/backlog-slice-1", "agent/backlog-slice-2"):
        _git(repo, "checkout", "master")
        _git(repo, "checkout", "-b", name)
        _commit(repo, f"{name.split('/')[-1]}.txt", "work\n")

    _git(repo, "checkout", "master")
    _git(repo, "merge", "--no-ff", "-m", "Merge agent/backlog-slice-1", "agent/backlog-slice-1")
    _git(repo, "push", "origin", "master")
    _git(repo, "fetch", "origin")

    assert sweeper._merged_branch_evidence(str(repo), "agent/backlog-slice-1") is not None
    assert sweeper._merged_branch_evidence(str(repo), "agent/backlog-slice-2") is None


def test_commit_merely_naming_the_slug_is_not_certified(repo):
    """A recovery commit that mentions the slug must not certify the original."""
    _git(repo, "checkout", "-b", "agent/lost-work")
    _commit(repo, "lost.txt", "work\n")
    _git(repo, "checkout", "master")
    # Master gains a commit that TALKS about the branch without containing it.
    (repo / "note.txt").write_text("see agent/lost-work\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "recovery attempt for agent/lost-work")
    _git(repo, "push", "origin", "master")
    _git(repo, "fetch", "origin")

    assert sweeper._merged_branch_evidence(str(repo), "agent/lost-work") is None


def test_resolves_branch_via_origin_when_only_the_remote_ref_exists(repo):
    """The fleet spans two Macs: the branch may exist only as origin/agent/*."""
    _git(repo, "checkout", "-b", "agent/remote-only")
    _commit(repo, "r.txt", "work\n")
    tip = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "push", "origin", "agent/remote-only")
    _git(repo, "checkout", "master")
    _git(repo, "merge", "--no-ff", "-m", "Merge agent/remote-only", "agent/remote-only")
    _git(repo, "push", "origin", "master")
    _git(repo, "branch", "-D", "agent/remote-only")
    _git(repo, "fetch", "origin", "+refs/heads/agent/*:refs/remotes/origin/agent/*")
    _git(repo, "fetch", "origin")

    sha, _ref = sweeper._merged_branch_evidence(str(repo), "agent/remote-only")
    assert sha == tip


def test_missing_repo_and_blank_branch_fail_soft(repo):
    assert sweeper._merged_branch_evidence("", "agent/x") is None
    assert sweeper._merged_branch_evidence("/nonexistent/path", "agent/x") is None
    assert sweeper._merged_branch_evidence(str(repo), "") is None
    assert sweeper._merged_branch_evidence(str(repo), "agent/never-existed") is None
