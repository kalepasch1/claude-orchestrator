"""Branch-detection scanner: a branch on origin is not a missing branch.

Acceptance for improve-implement-automated-branch-management-impl-slice-5:
`test_detect_missing_branches_real_mrs` identifies all 6 missing branches correctly,
against a real git repository rather than a mock.

The scanner listed LOCAL branches only, which contradicts the fleet's own lifecycle —
CLAUDE.md: the worktree is removed after push while "the agent/{slug} branch persists for
merge-train pickup". A pushed branch whose local ref was pruned read as MISSING, so the
fleet filed recover-missing-branch tasks for work already sitting on origin. Recreating
such a branch forks one change into two and hands the merge train a conflict.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_detection as bd  # noqa: E402


def _run(cwd, *args):
    # Explicit timeout: the suite's guard bounds unbounded subprocesses and warns.
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, timeout=30)


@pytest.fixture()
def repo(tmp_path):
    """A real repo with a real 'origin' remote, so remote refs are real refs."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    origin.mkdir()
    work.mkdir()
    _run(str(origin), "git", "init", "--bare", "-q", ".")
    _run(str(work), "git", "init", "-q", "-b", "master", ".")
    for key, value in (("user.name", "t"), ("user.email", "t@t")):
        _run(str(work), "git", "config", key, value)
    (work / "seed.txt").write_text("seed\n")
    _run(str(work), "git", "add", "-A")
    _run(str(work), "git", "commit", "-qm", "seed")
    _run(str(work), "git", "remote", "add", "origin", str(origin))
    _run(str(work), "git", "push", "-q", "origin", "master")
    return str(work)


def _make_local(repo_path, slug):
    _run(repo_path, "git", "branch", f"agent/{slug}")


def _make_pushed_then_pruned(repo_path, slug):
    """The real fleet lifecycle: branch pushed to origin, local ref removed."""
    _run(repo_path, "git", "branch", f"agent/{slug}")
    _run(repo_path, "git", "push", "-q", "origin", f"agent/{slug}")
    _run(repo_path, "git", "fetch", "-q", "origin")
    _run(repo_path, "git", "branch", "-D", f"agent/{slug}")


def _task(slug, state="QUEUED"):
    return {"slug": slug, "state": state}


def test_detect_missing_branches_real_mrs(repo):
    """All 6 genuinely-missing branches are found, and only those.

    The fixture deliberately mixes every shape the scanner has to tell apart:
    6 with no ref anywhere, 3 with a local ref, 3 pushed-then-pruned (origin only),
    and 2 missing but in terminal states that are not the scanner's business.
    """
    missing_slugs = [f"missing-{i}" for i in range(1, 7)]
    local_slugs = ["local-a", "local-b", "local-c"]
    remote_slugs = ["pushed-a", "pushed-b", "pushed-c"]

    for slug in local_slugs:
        _make_local(repo, slug)
    for slug in remote_slugs:
        _make_pushed_then_pruned(repo, slug)

    tasks = (
        [_task(s) for s in missing_slugs]
        + [_task(s, "RUNNING") for s in local_slugs]
        + [_task(s, "RUNNING") for s in remote_slugs]
        + [_task("done-no-branch", "DONE"), _task("merged-no-branch", "MERGED")]
    )

    found = bd.detect_missing_branches(repo, tasks)
    assert sorted(t["slug"] for t in found) == sorted(missing_slugs)
    assert len(found) == 6


class TestRemoteAwareness:
    def test_a_pushed_then_pruned_branch_is_not_missing(self, repo):
        """The whole bug: this is the fleet's NORMAL end state for finished work."""
        _make_pushed_then_pruned(repo, "shipped")
        assert bd.detect_missing_branches(repo, [_task("shipped", "RUNNING")]) == []

    def test_a_local_only_branch_is_not_missing(self, repo):
        _make_local(repo, "in-progress")
        assert bd.detect_missing_branches(repo, [_task("in-progress")]) == []

    def test_a_branch_that_exists_nowhere_is_missing(self, repo):
        found = bd.detect_missing_branches(repo, [_task("never-created")])
        assert [t["slug"] for t in found] == ["never-created"]

    def test_a_pushed_and_pruned_branch_is_always_counted(self):
        """There is no include_remote flag any more, and that is the fix.

        This used to assert `"shipped" not in _list_agent_branches(repo)` and
        only found it with include_remote=True — pinning a local-only default.
        That default is the blind spot: per the worktree convention an agent
        pushes agent/<slug> and the worktree is then removed, so on every other
        machine the branch exists ONLY as a remote-tracking ref. A local-only
        lookup calls a successfully pushed branch missing, and "missing" is what
        queues a recovery — so it does not merely under-report, it forks one
        piece of work into two branches and hands the merge train a conflict.

        _list_agent_branches counts both namespaces unconditionally now.
        """

    def test_list_counts_a_pushed_then_pruned_branch(self, repo):
        _make_pushed_then_pruned(repo, "shipped")
        assert "shipped" in bd._list_agent_branches(repo)

    def test_a_slug_containing_slashes_survives_the_remote_split(self, repo):
        """<remote>/agent/<slug> must split on the REMOTE only."""
        _make_pushed_then_pruned(repo, "group/one")
        assert "group/one" in bd._list_agent_branches(repo)


class TestStateFiltering:
    @pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "BLOCKED", "IN_PROGRESS"])
    def test_active_states_are_scanned(self, repo, state):
        assert len(bd.detect_missing_branches(repo, [_task("gone", state)])) == 1

    @pytest.mark.parametrize("state", ["DONE", "MERGED", "SUPERSEDED", "QUARANTINED", ""])
    def test_terminal_states_are_not_scanned(self, repo, state):
        assert bd.detect_missing_branches(repo, [_task("gone", state)]) == []

    def test_a_task_without_a_slug_is_skipped(self, repo):
        assert bd.detect_missing_branches(repo, [{"state": "QUEUED"}]) == []


class TestFailSoft:
    def test_a_missing_repo_returns_empty(self, tmp_path):
        assert bd.detect_missing_branches(str(tmp_path / "nope"), [_task("x")]) == []

    @pytest.mark.parametrize("path", [None, ""])
    def test_an_unusable_repo_path_returns_empty(self, path):
        assert bd.detect_missing_branches(path, [_task("x")]) == []

    def test_no_tasks_returns_empty(self, repo):
        assert bd.detect_missing_branches(repo, None) == []

    def test_a_non_git_directory_reports_everything_missing_without_raising(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert len(bd.detect_missing_branches(str(plain), [_task("x")])) == 1


class TestOrphanDetectionUnchanged:
    def test_orphan_detection_still_looks_at_local_branches(self, repo):
        """Left local-only on purpose: this feeds deletion decisions."""
        _make_local(repo, "no-task")
        orphans = bd.detect_orphaned_branches(repo, {"some-other-slug"})
        assert "no-task" in {o if isinstance(o, str) else o.get("branch", "") for o in orphans} \
            or any("no-task" in str(o) for o in orphans)
