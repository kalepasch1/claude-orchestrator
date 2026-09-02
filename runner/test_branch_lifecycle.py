"""Tests for branch_lifecycle module."""
import os
import subprocess
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import branch_lifecycle as bl


# ---------------------------------------------------------------------------
# validate_branch_name
# ---------------------------------------------------------------------------
class TestValidateBranchName:
    def test_valid_agent(self):
        ok, reason = bl.validate_branch_name("agent/my-task-slug")
        assert ok is True and reason == ""

    def test_valid_feature(self):
        ok, _ = bl.validate_branch_name("feature/proj-123")
        assert ok is True

    def test_empty(self):
        ok, reason = bl.validate_branch_name("")
        assert ok is False and "empty" in reason

    def test_none(self):
        ok, _ = bl.validate_branch_name(None)
        assert ok is False

    def test_too_long(self):
        ok, reason = bl.validate_branch_name("a" * 260)
        assert ok is False and "too long" in reason

    def test_double_dot(self):
        ok, reason = bl.validate_branch_name("agent/foo..bar")
        assert ok is False and ".." in reason

    def test_tilde(self):
        ok, reason = bl.validate_branch_name("agent/foo~1")
        assert ok is False

    def test_space(self):
        ok, reason = bl.validate_branch_name("agent/foo bar")
        assert ok is False

    def test_ends_with_lock(self):
        ok, reason = bl.validate_branch_name("agent/foo.lock")
        assert ok is False

    def test_ends_with_slash(self):
        ok, reason = bl.validate_branch_name("agent/foo/")
        assert ok is False

    def test_starts_with_dash(self):
        ok, reason = bl.validate_branch_name("-agent/foo")
        assert ok is False

    def test_consecutive_slashes(self):
        ok, reason = bl.validate_branch_name("agent//foo")
        assert ok is False

    def test_backslash(self):
        ok, reason = bl.validate_branch_name("agent\\foo")
        assert ok is False

    def test_caret(self):
        ok, reason = bl.validate_branch_name("agent/foo^bar")
        assert ok is False

    def test_at_brace(self):
        ok, reason = bl.validate_branch_name("agent/foo@{bar}")
        assert ok is False

    def test_colon(self):
        ok, reason = bl.validate_branch_name("agent/foo:bar")
        assert ok is False

    def test_bracket(self):
        ok, reason = bl.validate_branch_name("agent/foo[1]")
        assert ok is False

    def test_starts_with_dot(self):
        ok, reason = bl.validate_branch_name(".agent/foo")
        assert ok is False

    def test_single_char(self):
        # WAS: `assert isinstance(ok, bool)` with a comment guessing that "our regex requires
        # 2+ chars". That assertion is a tautology — it holds for True and for False — and the
        # guess is wrong: `git check-ref-format --branch a` exits 0, so a one-character branch
        # is legal and validate_branch_name must not reject it.
        ok, reason = bl.validate_branch_name("a")
        assert ok is True and reason == ""

    def test_control_character(self):
        ok, reason = bl.validate_branch_name("agent/foo\tbar")
        assert ok is False

    def test_question_mark_and_star(self):
        # The remaining two characters from git's forbidden set; a name carrying either is a
        # refspec glob, not a branch.
        assert bl.validate_branch_name("agent/foo?bar")[0] is False
        assert bl.validate_branch_name("agent/foo*")[0] is False


# ---------------------------------------------------------------------------
# The agent/<slug> branch convention
#
# SUBSTITUTION: this class used to call bl.is_agent_branch() / bl.is_feature_branch(),
# neither of which has ever existed in branch_lifecycle (nor anywhere else in the repo —
# nothing in production imports them). The intent — "the module knows an agent branch from
# anything else" — is real, but the module expresses it in zero_spend_recovery_eligible,
# which looks for exactly `agent/<slug>` and nowhere else. These tests pin that convention
# against the real API instead of a name that was never implemented.
# ---------------------------------------------------------------------------
def _repo_with_branches(tmp_path, *branches):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), capture_output=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=str(repo), capture_output=True)
    for b in branches:
        subprocess.run(["git", "branch", b], cwd=str(repo), capture_output=True)
    return str(repo)


class TestAgentBranchConvention:
    def test_agent_prefixed_branch_is_the_one_that_counts_as_existing(self, tmp_path):
        repo = _repo_with_branches(tmp_path, "agent/my-task")
        task = {"slug": "my-task", "state": "FAILED", "attempt": 0}
        assert bl.zero_spend_recovery_eligible(task, repo)["strategy"] == "requeue"

    def test_a_bare_slug_branch_is_not_treated_as_the_agent_branch(self, tmp_path):
        # `my-task` exists but `agent/my-task` does not, so there is no prior work to
        # requeue — the task must be rebuilt from base, not adopted.
        repo = _repo_with_branches(tmp_path, "my-task")
        task = {"slug": "my-task", "state": "FAILED", "attempt": 0}
        assert bl.zero_spend_recovery_eligible(task, repo)["strategy"] == "recreate_from_base"

    def test_a_feature_branch_is_not_the_agent_branch(self, tmp_path):
        repo = _repo_with_branches(tmp_path, "feature/my-task")
        task = {"slug": "my-task", "state": "FAILED", "attempt": 0}
        assert bl.zero_spend_recovery_eligible(task, repo)["strategy"] == "recreate_from_base"

    def test_both_prefixes_are_valid_branch_names(self):
        # The convention only works if the names it generates are legal refs.
        assert bl.validate_branch_name("agent/my-task") == (True, "")
        assert bl.validate_branch_name("feature/proj-123") == (True, "")

    def test_an_empty_slug_produces_an_invalid_agent_branch_name(self):
        # `agent/` is what f"agent/{slug}" yields for an empty slug; git refuses it, so
        # validate_branch_name must too rather than let a bad ref reach `git branch`.
        ok, reason = bl.validate_branch_name("agent/")
        assert ok is False and reason


# ---------------------------------------------------------------------------
# branch_exists (with real temp git repo)
# ---------------------------------------------------------------------------
class TestBranchExists:
    @pytest.fixture
    def git_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)
        (repo / "f.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-b", "agent/test-task"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-"], cwd=str(repo), capture_output=True)
        return str(repo)

    def test_exists(self, git_repo):
        assert bl.branch_exists(git_repo, "agent/test-task") is True

    def test_not_exists(self, git_repo):
        assert bl.branch_exists(git_repo, "agent/nonexistent") is False

    def test_bad_repo(self):
        assert bl.branch_exists("/nonexistent/repo", "agent/foo") is None

    def test_none_repo(self):
        assert bl.branch_exists(None, "agent/foo") is None


# ---------------------------------------------------------------------------
# zero_spend_recovery_eligible
# ---------------------------------------------------------------------------
class TestZeroSpendRecovery:
    def test_no_task(self):
        result = bl.zero_spend_recovery_eligible(None, "/tmp")
        assert result["eligible"] is False

    def test_max_retries(self):
        task = {"slug": "foo", "state": "FAILED", "attempt": 99}
        result = bl.zero_spend_recovery_eligible(task, "/tmp")
        assert result["eligible"] is False
        assert "max retries" in result["reason"]

    def test_failed_no_branch(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=str(repo), capture_output=True)

        task = {"slug": "missing-task", "state": "FAILED", "attempt": 0}
        result = bl.zero_spend_recovery_eligible(task, str(repo))
        assert result["eligible"] is True
        assert result["strategy"] == "recreate_from_base"

    def test_failed_with_branch(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-b", "agent/has-work"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-"], cwd=str(repo), capture_output=True)

        task = {"slug": "has-work", "state": "FAILED", "attempt": 1}
        result = bl.zero_spend_recovery_eligible(task, str(repo))
        assert result["eligible"] is True
        assert result["strategy"] == "requeue"

    def test_running_with_branch(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-b", "agent/orphan"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-"], cwd=str(repo), capture_output=True)

        task = {"slug": "orphan", "state": "RUNNING", "attempt": 0}
        result = bl.zero_spend_recovery_eligible(task, str(repo))
        assert result["eligible"] is True
        assert result["strategy"] == "adopt_orphan"

    def test_unreachable_repo(self, tmp_path):
        # WAS: hard-coded "/nonexistent" as the unreachable path. That directory actually
        # exists on some hosts (it does here), so the test asserted the opposite of what it
        # read: git ran, found no branch, and the task came back ELIGIBLE for
        # recreate_from_base. Use a path guaranteed absent under tmp_path instead.
        task = {"slug": "foo", "state": "FAILED", "attempt": 0}
        result = bl.zero_spend_recovery_eligible(task, str(tmp_path / "definitely-absent"))
        assert result["eligible"] is False
        assert result["reason"] == "cannot access repo"

    def test_directory_that_is_not_a_repo_is_unreachable_not_branchless(self, tmp_path):
        # The case the old "/nonexistent" test accidentally exercised, now asserted
        # deliberately: a directory that exists but holds no git repository cannot answer
        # "does agent/foo exist?", so it must not be reported as "no branch, start fresh".
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        assert bl.branch_exists(str(plain), "agent/foo") is None
        task = {"slug": "foo", "state": "FAILED", "attempt": 0}
        result = bl.zero_spend_recovery_eligible(task, str(plain))
        assert result["eligible"] is False
        assert result["reason"] == "cannot access repo"


# ---------------------------------------------------------------------------
# Staleness — the real cleanup signal
#
# SUBSTITUTION: this class used to call bl.list_cleanup_candidates(repo, merged_slugs) and
# assert it returned one entry with reason "merged". That function has never existed in
# branch_lifecycle and nothing in the repo imports it, so there is no product behaviour to
# hold to. What the module actually offers for deciding whether a branch is reclaimable is
# is_stale() / branch_last_commit_epoch(), and nothing covered either. These pin those,
# including the None ("we could not look") answers the cleanup caller has to distinguish
# from False ("the branch is fresh").
# ---------------------------------------------------------------------------
def _commit_at(repo, message, epoch):
    """Commit with author/committer date pinned to EPOCH.

    The offset is explicit. This used to render UTC wall-clock via time.gmtime() and
    hand git a bare "2026-08-14T15:04:54" with no zone -- which git reads as LOCAL
    time. On this machine (UTC-4) every fixture commit therefore landed four hours
    after the epoch the caller asked for, and
    test_last_commit_epoch_matches_the_commit_date failed by exactly 14400 seconds.

    The staleness tests around it never noticed, because 30 days plus four hours is
    still 30 days. Only the test that asserts the EXACT epoch could see it -- which is
    the argument for having one.
    """
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(epoch))
    env = dict(os.environ, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
    subprocess.run(["git", "commit", "--allow-empty", "-m", message],
                   cwd=repo, capture_output=True, env=env)


class TestStaleness:
    def test_bad_repo_is_unknown_not_stale(self, tmp_path):
        assert bl.is_stale(str(tmp_path / "gone"), "agent/foo") is None
        assert bl.branch_last_commit_epoch(str(tmp_path / "gone"), "agent/foo") is None

    def test_missing_branch_is_unknown(self, tmp_path):
        repo = _repo_with_branches(tmp_path)
        assert bl.is_stale(repo, "agent/never-existed") is None

    def test_fresh_branch_is_not_stale(self, tmp_path):
        repo = _repo_with_branches(tmp_path, "agent/fresh")
        assert bl.is_stale(repo, "agent/fresh", stale_days=7) is False

    def test_old_branch_is_stale(self, tmp_path):
        repo = _repo_with_branches(tmp_path)
        subprocess.run(["git", "checkout", "-b", "agent/old"], cwd=repo, capture_output=True)
        _commit_at(repo, "old work", time.time() - 30 * 86400)
        subprocess.run(["git", "checkout", "-"], cwd=repo, capture_output=True)
        assert bl.is_stale(repo, "agent/old", stale_days=7) is True
        assert bl.is_stale(repo, "agent/old", stale_days=60) is False

    def test_last_commit_epoch_matches_the_commit_date(self, tmp_path):
        repo = _repo_with_branches(tmp_path)
        subprocess.run(["git", "checkout", "-b", "agent/dated"], cwd=repo, capture_output=True)
        want = int(time.time()) - 12 * 86400
        _commit_at(repo, "dated work", want)
        subprocess.run(["git", "checkout", "-"], cwd=repo, capture_output=True)
        assert bl.branch_last_commit_epoch(repo, "agent/dated") == want

    def test_default_stale_days_comes_from_module_config(self, tmp_path):
        repo = _repo_with_branches(tmp_path)
        subprocess.run(["git", "checkout", "-b", "agent/edge"], cwd=repo, capture_output=True)
        _commit_at(repo, "edge", time.time() - (bl.STALE_DAYS + 1) * 86400)
        subprocess.run(["git", "checkout", "-"], cwd=repo, capture_output=True)
        assert bl.is_stale(repo, "agent/edge") is True


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
class TestStats:
    def test_stats_returns_dict(self):
        s = bl.stats()
        assert isinstance(s, dict)
        assert "validations" in s

    def test_reset(self):
        bl.reset_stats()
        s = bl.stats()
        assert all(v == 0 for v in s.values())
