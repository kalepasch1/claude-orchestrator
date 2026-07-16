"""Tests for backlog_recovery — automated legacy branch triage."""
import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import backlog_recovery as br


def _default_branch(repo):
    r = subprocess.run(["git", "-C", repo, "branch", "--show-current"],
                       capture_output=True, text=True)
    return r.stdout.strip() or "main"


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with some agent branches."""
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    subprocess.run(["git", "init", repo], capture_output=True, check=True)
    subprocess.run(["git", "-C", repo, "commit", "--allow-empty", "-m", "init"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", repo, "branch", "agent/legacy-task-1"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", repo, "branch", "agent/legacy-task-2"],
                   capture_output=True, check=True)
    return repo


class TestBranchAssessment:
    def test_dataclass_defaults(self):
        a = br.BranchAssessment(branch="agent/foo", slug="foo", status="mergeable")
        assert a.commits_ahead == 0
        assert a.has_conflicts is False
        assert a.priority == 0


class TestRecoveryPlan:
    def test_empty_plan(self):
        plan = br.RecoveryPlan()
        assert plan.total_branches == 0
        s = plan.summary()
        assert s["total"] == 0

    def test_summary_counts(self):
        plan = br.RecoveryPlan(total_branches=4, mergeable_count=2,
                               obsolete_count=1, already_merged_count=1)
        s = plan.summary()
        assert s["mergeable"] == 2
        assert s["obsolete"] == 1


class TestAssessBranch:
    def test_already_merged(self, git_repo):
        """Branch with no commits ahead is already_merged."""
        base = _default_branch(git_repo)
        a = br.assess_branch(git_repo, "agent/legacy-task-1", base)
        assert a.status == "already_merged"
        assert a.commits_ahead == 0

    def test_nonexistent_branch(self, git_repo):
        base = _default_branch(git_repo)
        a = br.assess_branch(git_repo, "agent/does-not-exist", base)
        assert a.status == "error"

    def test_branch_with_commits(self, git_repo):
        """Branch with commits ahead should be mergeable or conflicting."""
        base = _default_branch(git_repo)
        subprocess.run(["git", "-C", git_repo, "checkout", "agent/legacy-task-1"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", git_repo, "commit", "--allow-empty", "-m", "work"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", git_repo, "checkout", base],
                       capture_output=True, check=True)
        a = br.assess_branch(git_repo, "agent/legacy-task-1", base)
        assert a.commits_ahead == 1
        assert a.status in ("mergeable", "conflicting")


class TestBuildRecoveryPlan:
    def test_build_plan(self, git_repo):
        base = _default_branch(git_repo)
        plan = br.build_recovery_plan(
            git_repo,
            ["agent/legacy-task-1", "agent/legacy-task-2"],
            base=base,
        )
        assert plan.total_branches == 2
        assert plan.already_merged_count == 2

    def test_empty_branches(self, git_repo):
        base = _default_branch(git_repo)
        plan = br.build_recovery_plan(git_repo, [], base=base)
        assert plan.total_branches == 0


class TestFormatPlan:
    def test_format_output(self):
        plan = br.RecoveryPlan(
            total_branches=1, mergeable_count=1,
            assessments=[br.BranchAssessment(
                branch="agent/test", slug="test", status="mergeable",
                commits_ahead=3, files_changed=5, reason="clean merge"
            )]
        )
        output = br.format_plan(plan)
        assert "Backlog Recovery Plan" in output
        assert "MERGEABLE" in output
        assert "clean merge" in output
