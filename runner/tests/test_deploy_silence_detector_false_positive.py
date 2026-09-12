"""Regression tests for the two defects that made deploy_silence_detector cry wolf.

Both were found by chasing task `deploysilence-kalepasch-com`, which had been requeued
four times. Its alert said "commits are landing and production is NOT updating" and told
the operator to check `vercel.json` `ignoreCommand` / `git.deploymentEnabled` first. Both
were already correct — `vercel_config_guard kalepasch-com` returned GREEN — because the
project was never broken. The DETECTOR was.

1. `last_commit_age_days` read the bare local ref. Vercel builds from the REMOTE, so a
   commit that exists only in the local checkout can never trigger a deploy. This fleet's
   merge automation lands agent branches into local `main` without pushing (kalepasch-com
   sat 115 commits ahead of origin), so the detector saw a fresh commit that Vercel could
   not see, and no config change could ever clear the alert.

2. `evaluate` never compared the deploy age to the COMMIT age. kalepasch-com's newest
   commit was 3.0d old and its last production deploy 2.9d old — production had already
   built the newest commit — but `deploy_age (2.9) > silence_days (2.0)` fired anyway. Any
   healthy project whose branch simply goes quiet past the threshold alerts forever.
"""
import os
import subprocess
import sys
import time

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNNER = os.path.dirname(_HERE)
sys.path.insert(0, _RUNNER)

import deploy_silence_detector as dsd  # noqa: E402

DAY = 86400.0


def _git(repo, *args, **env):
    e = dict(os.environ)
    e.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
              "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    e.update(env)
    subprocess.run(["git"] + list(args), cwd=repo, check=True,
                   capture_output=True, text=True, env=e, timeout=30)


def _commit(repo, msg, when_epoch):
    stamp = "%d +0000" % int(when_epoch)
    with open(os.path.join(repo, "f.txt"), "a", encoding="utf-8") as fh:
        fh.write(msg + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg,
         GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)


@pytest.fixture
def repo_with_remote(tmp_path):
    """A clone whose local `main` is 1 day fresh but whose origin/main is 3 days old.

    This is the kalepasch-com shape: the fleet merged into local main and never pushed.
    """
    upstream = tmp_path / "upstream.git"
    upstream.mkdir()
    _git(str(upstream), "init", "--bare", "-b", "main")

    work = tmp_path / "work"
    work.mkdir()
    _git(str(work), "init", "-b", "main")
    _git(str(work), "remote", "add", "origin", str(upstream))
    _commit(str(work), "old", time.time() - 3 * DAY)
    _git(str(work), "push", "-u", "origin", "main")
    # Land a commit locally only -- exactly what the merge automation does.
    _commit(str(work), "unpushed", time.time() - 1 * DAY)
    return str(work)


def test_commit_age_reads_origin_not_local(repo_with_remote):
    """The age must reflect origin/main (3d), not the unpushed local main (1d).

    Reading the local ref reports 1 day, so `commit_age <= silence_days` holds and the
    detector proceeds to alert about a commit Vercel has never been shown.
    """
    age = dsd.last_commit_age_days(repo_with_remote, "main")
    assert age is not None
    assert age == pytest.approx(3.0, abs=0.1), (
        "expected origin/main's 3-day-old commit, got %.2f days -- the local, "
        "unpushed commit is being measured again" % age)


def test_commit_age_falls_back_to_local_ref_when_no_remote(tmp_path):
    """Local-only repos (smoke-test) must still be measurable, not silently skipped."""
    repo = tmp_path / "local_only"
    repo.mkdir()
    _git(str(repo), "init", "-b", "main")
    _commit(str(repo), "only", time.time() - 2 * DAY)
    age = dsd.last_commit_age_days(str(repo), "main")
    assert age is not None and age == pytest.approx(2.0, abs=0.1)


def test_commit_age_none_for_unknown_branch(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    _git(str(repo), "init", "-b", "main")
    _commit(str(repo), "x", time.time())
    assert dsd.last_commit_age_days(str(repo), "no-such-branch") is None


@pytest.fixture
def evaluable(tmp_path, monkeypatch):
    """A project row `evaluate` will accept, with the Vercel lookup stubbed.

    Returns (row, set_ages) where set_ages(commit_age, deploy_age) pins both clocks.
    """
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "vercel.json").write_text('{"git":{"deploymentEnabled":{"main":true}}}',
                                      encoding="utf-8")
    row = {"name": "kalepasch-com", "repo_path": str(repo), "prod_branch": "main"}

    def set_ages(commit_age, deploy_age):
        monkeypatch.setattr(dsd, "last_commit_age_days",
                            lambda _r, _b: commit_age)
        monkeypatch.setattr(dsd, "last_production_deploy",
                            lambda _p: (deploy_age, "READY", "x.vercel.app"))
        fake = type(sys)("deploy_verify")
        fake._vercel_project = lambda _n, _r: "prj_test"
        monkeypatch.setitem(sys.modules, "deploy_verify", fake)

    return row, set_ages


def test_no_alert_when_production_already_built_the_newest_commit(evaluable):
    """The exact kalepasch-com numbers: commit 3.0d, deploy 2.9d, threshold 2.0d.

    The deploy is NEWER than the commit, so production is current and there is nothing to
    ship. This must hold via the deploy-vs-commit comparison, not via a commit-recency
    short-circuit that happens to skip the project for an unrelated reason.
    """
    row, set_ages = evaluable
    set_ages(commit_age=3.0, deploy_age=2.9)
    assert dsd.evaluate(row, silence_days=2.0) is None


def test_no_alert_for_a_branch_that_simply_went_quiet(evaluable):
    """A month-old commit with a month-old deploy is an idle project, not an incident."""
    row, set_ages = evaluable
    set_ages(commit_age=30.0, deploy_age=29.9)
    assert dsd.evaluate(row, silence_days=2.0) is None


def test_old_commit_that_never_shipped_is_still_silence(evaluable):
    """The missed detection the removed short-circuit was causing.

    A commit 5 days old whose last production deploy is 30 days old means the commit landed
    and never shipped. The old `commit_age > silence_days` early return skipped this project
    before the deploy age was ever fetched, so a month of dead production was invisible.
    """
    row, set_ages = evaluable
    set_ages(commit_age=5.0, deploy_age=30.0)
    finding = dsd.evaluate(row, silence_days=2.0)
    assert finding is not None, (
        "a 5-day-old commit sitting behind a 30-day-old deploy is silence; the "
        "commit-recency short-circuit must not hide it again")
    assert finding["deploy_age_days"] == 30.0


def test_real_silence_still_alerts(evaluable):
    """The guard must not swallow the incident this module exists for.

    Commit 0.5d old, last production deploy 9d old: a commit landed and production did not
    move. That is the illuminati failure and it must still fire.
    """
    row, set_ages = evaluable
    set_ages(commit_age=0.5, deploy_age=9.0)
    finding = dsd.evaluate(row, silence_days=2.0)
    assert finding is not None
    assert finding["project"] == "kalepasch-com"
    assert finding["deploy_age_days"] == 9.0
    assert "NOT updating" in finding["reason"]


def test_clock_skew_within_tolerance_is_not_an_alert(evaluable):
    """A deploy timestamped fractionally BEFORE its own commit is skew, not silence."""
    row, set_ages = evaluable
    set_ages(commit_age=5.0, deploy_age=5.0 + dsd.DEPLOY_LAG_TOLERANCE_DAYS / 2)
    assert dsd.evaluate(row, silence_days=2.0) is None


def test_commit_newer_than_deploy_beyond_tolerance_alerts(evaluable):
    """One clear day of drift past tolerance is genuine silence and must alert."""
    row, set_ages = evaluable
    set_ages(commit_age=1.0, deploy_age=4.0)
    assert dsd.evaluate(row, silence_days=2.0) is not None
