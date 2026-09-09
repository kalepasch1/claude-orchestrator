#!/usr/bin/env python3
"""Tests for reconcile_queue_against_git.

The behaviour that matters is the three-way split. Getting it wrong in either
direction is expensive:

  * calling merged work ABSENT is the current production bug -- it is what makes
    executors redo finished tasks forever;
  * calling unmerged work SHIPPED would close a real task and lose the work.

So both directions are pinned, along with the rule that a branch alone never
counts as shipped.
"""
import os
import subprocess
import sys

import pytest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

rq = pytest.importorskip("reconcile_queue_against_git")


class TestClassify:
    def test_merged_slug_is_shipped(self):
        out = rq.classify(["a"], merged={"a"}, branched=set())
        assert out[rq.CLASS_SHIPPED] == ["a"]
        assert out[rq.CLASS_ABSENT] == []

    def test_branch_without_merge_is_branch_only(self):
        out = rq.classify(["a"], merged=set(), branched={"a"})
        assert out[rq.CLASS_BRANCH_ONLY] == ["a"]
        assert out[rq.CLASS_SHIPPED] == [], "a branch is not proof of merge"

    def test_unknown_slug_is_absent(self):
        out = rq.classify(["a"], merged=set(), branched=set())
        assert out[rq.CLASS_ABSENT] == ["a"]

    def test_merged_wins_over_branch(self):
        # Both refs exist, which is the normal post-merge state. It is shipped,
        # and must not be double-counted into BRANCH_ONLY.
        out = rq.classify(["a"], merged={"a"}, branched={"a"})
        assert out[rq.CLASS_SHIPPED] == ["a"]
        assert out[rq.CLASS_BRANCH_ONLY] == []

    def test_buckets_partition_the_input(self):
        slugs = ["a", "b", "c", "d"]
        out = rq.classify(slugs, merged={"a"}, branched={"b", "c"})
        total = sum(len(v) for v in out.values())
        assert total == len(slugs)
        assert set(out[rq.CLASS_ABSENT]) == {"d"}


class TestAgainstARealRepo:
    """Exercise the git readers on a throwaway repo, not a mock.

    The two readers are the part most likely to rot, because they depend on
    real `git log` / `for-each-ref` output shapes.
    """

    @pytest.fixture
    def repo(self, tmp_path):
        r = str(tmp_path / "r")
        os.makedirs(r)
        env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
        def git(*a):
            subprocess.run(("git", "-C", r) + a, check=True,
                           capture_output=True, text=True, env=env, timeout=30)
        git("init", "-q", "-b", "master")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        (tmp_path / "r" / "f.txt").write_text("1\n")
        git("add", "-A")
        git("commit", "-q", "-m", "agent: already-merged-task")
        git("commit", "-q", "--allow-empty", "-m", "chore: unrelated")
        # a branch that was never merged
        git("branch", "agent/branch-only-task")
        return r

    def test_shipped_slugs_reads_merged_history(self, repo):
        found = rq.shipped_slugs(repo, "refs/heads/master")
        assert "already-merged-task" in found

    def test_shipped_slugs_ignores_non_agent_subjects(self, repo):
        found = rq.shipped_slugs(repo, "refs/heads/master")
        assert not any("unrelated" in s for s in found)

    def test_pushed_branches_finds_local_agent_refs(self, repo):
        assert "branch-only-task" in rq.pushed_branches(repo)

    def test_branch_only_task_is_not_reported_shipped(self, repo):
        merged = rq.shipped_slugs(repo, "refs/heads/master")
        branched = rq.pushed_branches(repo)
        out = rq.classify(["branch-only-task"], merged, branched)
        assert out[rq.CLASS_BRANCH_ONLY] == ["branch-only-task"]

    def test_end_to_end_split_on_real_repo(self, repo):
        merged = rq.shipped_slugs(repo, "refs/heads/master")
        branched = rq.pushed_branches(repo)
        out = rq.classify(
            ["already-merged-task", "branch-only-task", "never-seen-task"],
            merged, branched,
        )
        assert out[rq.CLASS_SHIPPED] == ["already-merged-task"]
        assert out[rq.CLASS_BRANCH_ONLY] == ["branch-only-task"]
        assert out[rq.CLASS_ABSENT] == ["never-seen-task"]

    def test_git_helper_survives_a_bad_repo(self, tmp_path):
        rc, _ = rq._git(str(tmp_path), "rev-parse", "--verify", "-q", "refs/heads/nope")
        assert rc != 0, "must report failure rather than raise"

    def test_missing_production_branch_returns_none(self, tmp_path):
        empty = str(tmp_path / "empty")
        os.makedirs(empty)
        subprocess.run(("git", "-C", empty, "init", "-q"), check=True,
                       capture_output=True, timeout=30)
        assert rq.production_branch(empty, {"prod_branch": "nonexistent"}) is None
