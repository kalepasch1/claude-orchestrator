"""A branch on origin is not a missing branch — the owner path must not "recover" it.

CLAUDE.md documents the lifecycle: the worktree is removed after push while "the
agent/{slug} branch persists for merge-train pickup". So a local ref pruned after a
SUCCESSFUL push looks exactly like a lost branch. The missing-branch owner path acted on
that appearance and re-queued a recovery, which forks one change into two branches and
hands the merge train the conflict the reconciliation contract exists to prevent.

Two such false positives were confirmed by hand in a single executor run
(merged-diff-memory-8-failures and reconcile-evidence-self-feeding were both filed as
missing while intact on origin).
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_remediate as ar  # noqa: E402


def _run(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, timeout=30)


@pytest.fixture()
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    origin.mkdir()
    work.mkdir()
    _run(str(origin), "git", "init", "--bare", "-q", ".")
    _run(str(work), "git", "init", "-q", "-b", "master", ".")
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        _run(str(work), "git", "config", k, v)
    (work / "seed.txt").write_text("seed\n")
    _run(str(work), "git", "add", "-A")
    _run(str(work), "git", "commit", "-qm", "seed")
    _run(str(work), "git", "remote", "add", "origin", str(origin))
    _run(str(work), "git", "push", "-q", "origin", "master")
    return str(work)


def _push_then_prune(repo_path, slug):
    """The fleet's normal end state for finished work."""
    _run(repo_path, "git", "branch", f"agent/{slug}")
    _run(repo_path, "git", "push", "-q", "origin", f"agent/{slug}")
    _run(repo_path, "git", "fetch", "-q", "origin")
    _run(repo_path, "git", "branch", "-D", f"agent/{slug}")


class TestBranchAlreadyShared:
    def test_a_pushed_then_pruned_branch_is_shared(self, repo):
        _push_then_prune(repo, "shipped")
        assert ar.branch_already_shared({"slug": "shipped"}, repo=repo) is True

    def test_a_branch_that_exists_nowhere_is_not_shared(self, repo):
        assert ar.branch_already_shared({"slug": "never-made"}, repo=repo) is False

    def test_a_local_only_branch_is_not_shared(self, repo):
        """A local ref proves nothing about whether the work reached anyone else."""
        _run(repo, "git", "branch", "agent/local-only")
        assert ar.branch_already_shared({"slug": "local-only"}, repo=repo) is False

    def test_a_slug_with_a_slash_is_handled(self, repo):
        _push_then_prune(repo, "group/one")
        assert ar.branch_already_shared({"slug": "group/one"}, repo=repo) is True

    @pytest.mark.parametrize("task", [None, {}, {"slug": ""}, {"slug": "   "}])
    def test_an_unusable_task_is_not_shared(self, task, repo):
        assert ar.branch_already_shared(task, repo=repo) is False

    def test_an_unreadable_repo_is_fail_soft(self, tmp_path):
        """Never suppress a genuine recovery because the check could not be answered."""
        assert ar.branch_already_shared({"slug": "x"}, repo=str(tmp_path / "nope")) is False

    def test_a_non_git_directory_is_fail_soft(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert ar.branch_already_shared({"slug": "x"}, repo=str(plain)) is False


class TestOwnerPathSelectsTheSafeOutcome:
    def test_the_signal_that_triggers_the_owner_path(self):
        """Pin the regex the handler keys on, so the wiring cannot silently detach."""
        assert ar._MISSING_BRANCH.search("agent branch is missing on this host")
        assert ar._MISSING_BRANCH.search("branch no longer exists")

    def test_the_guard_runs_before_the_repair_call_in_the_handler(self):
        """Order is the whole fix: checking after the repair would already have forked."""
        src = open(ar.__file__, encoding="utf-8").read()
        guard = src.index("_MISSING_BRANCH.search(signal) and branch_already_shared(t)")
        repair = src.index('category = "missing-branch" if _MISSING_BRANCH.search(signal)')
        assert guard < repair

    def test_the_guarded_outcome_leaves_the_work_for_the_merge_train(self):
        src = open(ar.__file__, encoding="utf-8").read()
        block = src[src.index("MISSING-BRANCH OWNER PATH"):][:900]
        assert "merge train" in block.lower()
        assert '"state": "BLOCKED"' in block
        # It must NOT re-queue: that is the behaviour being removed.
        assert "repair_patch" not in block

    def test_terminates_deterministically_at_the_repair_threshold(self):
        """Beyond the ceiling the owner path parks rather than re-queueing, every time."""
        exhausted = {"id": "t1", "slug": "s", "attempt": 99,
                     "remediation_count": ar.agentic_repair.GLOBAL_REPAIR_CEILING + 1,
                     "note": "branch missing", "prompt": "x"}
        first = ar.agentic_repair.repair_patch(exhausted, "branch missing",
                                               category="missing-branch")
        second = ar.agentic_repair.repair_patch(exhausted, "branch missing",
                                                category="missing-branch")
        assert first["state"] == "QUARANTINED"
        assert first["state"] == second["state"]
        assert first["note"] == second["note"]
