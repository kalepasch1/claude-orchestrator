"""diagnostic_missing_branch: branch existence must be answered from ORIGIN.

The failure this locks down: `git branch -r` lists remote-TRACKING refs, a
snapshot of the last fetch. In a stale clone a branch that IS on origin reads as
missing, and a wrong "missing" here files a reconstruct-the-patch task — so an
agent rebuilds work that was on origin the whole time. That is how this test's
own task (backlog-batch-beethoven-ccacb00-verify-branch-existence-reconstruct-
minimal-patch) came to exist: agent/backlog-batch-beethoven-ccacb00 is on origin.

Tests build real throwaway git repos rather than mocking subprocess, so they
exercise the actual ls-remote path.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import diagnostic_missing_branch as dmb  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, timeout=30)


@pytest.fixture()
def clone_and_origin(tmp_path):
    """A bare origin with `feature/live` on it, plus a clone that has NOT fetched
    since — the stale-clone shape that produced the wrong answers."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "clone"

    _git(tmp_path, "init", "--bare", "-b", "master", str(origin))
    _git(tmp_path, "init", "-b", "master", str(seed))
    (seed / "f.txt").write_text("hello\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "init")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "origin", "master")
    _git(tmp_path, "clone", str(origin), str(clone))
    # Branch created on origin AFTER the clone: the clone's remote-tracking refs
    # do not know about it.
    _git(seed, "branch", "feature/live")
    _git(seed, "push", "origin", "feature/live")
    return clone, origin


@pytest.fixture(autouse=True)
def _no_cache():
    """branch_availability_check memoises for 120s; tests must not share it."""
    if dmb._bac is not None:
        dmb._bac.invalidate()
    yield
    if dmb._bac is not None:
        dmb._bac.invalidate()


# -- the regression --------------------------------------------------------


def test_branch_on_origin_but_not_in_stale_clone_reads_present(clone_and_origin):
    """THE bug. Local refs say missing; origin says present; present wins."""
    clone, _ = clone_and_origin
    local = _git(clone, "branch", "-r").stdout
    assert "feature/live" not in local, "fixture must be a stale clone"

    verdict, source = dmb.branch_status(str(clone), "feature/live")
    assert verdict == dmb.PRESENT
    assert "origin" in source


def test_branch_absent_everywhere_reads_missing(clone_and_origin):
    clone, _ = clone_and_origin
    verdict, source = dmb.branch_status(str(clone), "feature/never-existed")
    assert verdict == dmb.MISSING
    assert "origin" in source


def test_master_reads_present(clone_and_origin):
    clone, _ = clone_and_origin
    assert dmb.branch_status(str(clone), "master")[0] == dmb.PRESENT


# -- UNKNOWN is not MISSING ------------------------------------------------


def test_unreachable_origin_is_unknown_not_missing(tmp_path):
    """An unanswerable question must never be recorded as 'not there' — that is
    the reading that files a spurious reconstruct-the-patch task."""
    repo = tmp_path / "solo"
    repo.mkdir()
    _git(repo, "init", "-b", "master", ".")
    _git(repo, "remote", "add", "origin", str(tmp_path / "does-not-exist.git"))
    verdict, source = dmb.branch_status(str(repo), "feature/live")
    assert verdict == dmb.UNKNOWN
    assert verdict != dmb.MISSING
    assert "missing" in source.lower() or "unreachable" in source.lower()


def test_no_remote_configured_is_unknown(tmp_path):
    repo = tmp_path / "noremote"
    repo.mkdir()
    _git(repo, "init", "-b", "master", ".")
    assert dmb.branch_status(str(repo), "anything")[0] == dmb.UNKNOWN


@pytest.mark.parametrize("repo", [None, "", 123, "/definitely/not/a/path"])
def test_junk_repo_is_unknown_not_missing(repo):
    verdict, _ = dmb.branch_status(repo, "feature/live")
    assert verdict == dmb.UNKNOWN


@pytest.mark.parametrize("branch", [None, "", 0, []])
def test_junk_branch_is_unknown_not_missing(clone_and_origin, branch):
    clone, _ = clone_and_origin
    assert dmb.branch_status(str(clone), branch)[0] == dmb.UNKNOWN


def test_verdicts_are_three_distinct_values():
    assert len({dmb.PRESENT, dmb.MISSING, dmb.UNKNOWN}) == 3


# -- branch-status.txt, the artifact nothing ever produced -----------------


def test_write_branch_status_present_includes_source_and_sha(clone_and_origin, tmp_path):
    clone, _ = clone_and_origin
    out = tmp_path / "branch-status.txt"
    assert dmb.write_branch_status(str(clone), "feature/live", str(out)) == dmb.PRESENT
    text = out.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "PRESENT"
    assert "branch: feature/live" in text
    assert "origin" in text
    sha = [l for l in text.splitlines() if l.startswith("sha: ")][0][5:]
    assert len(sha) == 40, "verdict must carry a re-verifiable SHA"


def test_write_branch_status_missing(clone_and_origin, tmp_path):
    clone, _ = clone_and_origin
    out = tmp_path / "branch-status.txt"
    assert dmb.write_branch_status(str(clone), "nope/nope", str(out)) == dmb.MISSING
    assert out.read_text(encoding="utf-8").splitlines()[0] == "MISSING"


def test_write_branch_status_unwritable_path_does_not_raise(clone_and_origin):
    clone, _ = clone_and_origin
    verdict = dmb.write_branch_status(
        str(clone), "feature/live", "/definitely/not/writable/branch-status.txt")
    assert verdict == dmb.PRESENT  # verdict still returned; write failure is soft


# -- CLI -------------------------------------------------------------------


def test_cli_exit_zero_when_branch_present(clone_and_origin, tmp_path, monkeypatch):
    clone, _ = clone_and_origin
    monkeypatch.chdir(tmp_path)
    assert dmb.main(["feature/live", str(clone)]) == 0
    assert (tmp_path / "branch-status.txt").read_text(
        encoding="utf-8").startswith("PRESENT")


def test_cli_exit_one_when_branch_genuinely_missing(clone_and_origin, tmp_path, monkeypatch):
    clone, _ = clone_and_origin
    monkeypatch.chdir(tmp_path)
    assert dmb.main(["nope/nope", str(clone)]) == 1


def test_cli_exit_two_when_unanswerable(tmp_path, monkeypatch):
    """Distinct exit code: a caller must be able to tell 'not there' from
    'could not ask' without parsing prose."""
    repo = tmp_path / "noremote"
    repo.mkdir()
    _git(repo, "init", "-b", "master", ".")
    monkeypatch.chdir(tmp_path)
    assert dmb.main(["anything", str(repo)]) == 2


def test_module_exposes_helpers():
    for name in ("branch_status", "write_branch_status", "main",
                 "analyze_missing_branches", "check_branch_consistency"):
        assert callable(getattr(dmb, name)), name
