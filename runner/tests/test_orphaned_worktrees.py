"""Orphaned worktrees — a worktree whose admin dir went while its directory survived.

This is not hypothetical. The reconciliation that added this module was handed
`/Users/kpasch/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric` as evidence:
29 MB of working directory whose `.git` gitlink pointed at
`.../claude-orchestrator/.git/worktrees/orchestrator-session-fabric`, which no longer existed.
Every git command run inside it died with "fatal: not a git repository", `git worktree prune`
reported nothing to do, and `gc_repo` skipped it because `_recently_active` cannot read a broken
gitlink and fails closed. Nothing in the fleet could see it.

These tests pin the two halves that matter: an orphan is FOUND, and nothing healthy is ever
mistaken for one — because the only safe thing to do with a false positive here is nothing.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import worktree_gc  # noqa: E402


def _make_worktree(tmp_path, name, admin_exists=True, relative=False):
    """A directory shaped like a git worktree, with or without its admin dir."""
    wt = tmp_path / name
    wt.mkdir()
    admin = tmp_path / "adm" / name
    if admin_exists:
        admin.mkdir(parents=True)
    target = os.path.relpath(str(admin), str(wt)) if relative else str(admin)
    (wt / ".git").write_text("gitdir: {}\n".format(target))
    return wt, admin


def test_a_worktree_whose_admin_dir_is_gone_is_orphaned(tmp_path):
    wt, _ = _make_worktree(tmp_path, "dead", admin_exists=False)
    assert worktree_gc.is_orphaned_worktree(str(wt)) is True


def test_a_worktree_whose_admin_dir_exists_is_not_orphaned(tmp_path):
    wt, _ = _make_worktree(tmp_path, "alive", admin_exists=True)
    assert worktree_gc.is_orphaned_worktree(str(wt)) is False


def test_an_admin_dir_that_disappears_flips_the_verdict(tmp_path):
    """The transition is the actual failure mode, so assert it rather than the two states."""
    wt, admin = _make_worktree(tmp_path, "doomed", admin_exists=True)
    assert worktree_gc.is_orphaned_worktree(str(wt)) is False
    admin.rmdir()
    assert worktree_gc.is_orphaned_worktree(str(wt)) is True


def test_a_relative_gitdir_is_resolved_against_the_worktree(tmp_path):
    """git writes a relative gitdir in some layouts; resolving it against cwd would lie."""
    wt, admin = _make_worktree(tmp_path, "rel", admin_exists=True, relative=True)
    assert worktree_gc.is_orphaned_worktree(str(wt)) is False
    admin.rmdir()
    assert worktree_gc.is_orphaned_worktree(str(wt)) is True


def test_an_ordinary_repository_is_never_an_orphan(tmp_path):
    """`.git` as a DIRECTORY is a normal checkout, not a worktree slot."""
    repo = tmp_path / "normal"
    (repo / ".git").mkdir(parents=True)
    assert worktree_gc.is_orphaned_worktree(str(repo)) is False


def test_a_directory_with_no_git_at_all_is_not_an_orphan(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert worktree_gc.is_orphaned_worktree(str(plain)) is False


def test_a_missing_path_is_not_an_orphan(tmp_path):
    # A path that is gone is prune's job, not this one — reporting it here would send a
    # caller looking for a directory that does not exist.
    assert worktree_gc.is_orphaned_worktree(str(tmp_path / "nope")) is False


def test_none_and_empty_are_handled(tmp_path):
    assert worktree_gc.is_orphaned_worktree(None) is False
    assert worktree_gc.is_orphaned_worktree("") is False


def test_a_garbage_git_file_is_not_reported_as_an_orphan(tmp_path):
    """Fail closed: unreadable is not the same as orphaned, and only one of them is safe."""
    wt = tmp_path / "garbage"
    wt.mkdir()
    (wt / ".git").write_text("this is not a gitlink\n")
    assert worktree_gc.is_orphaned_worktree(str(wt)) is False


def test_extra_paths_are_scanned_even_when_git_does_not_list_them(tmp_path):
    """Once the main repo's records go too, the directory on disk is the only evidence left."""
    wt, _ = _make_worktree(tmp_path, "unlisted", admin_exists=False)
    found = worktree_gc.orphaned_worktrees(str(tmp_path / "no-such-repo"), extra_paths=[str(wt)])
    assert [o["path"] for o in found] == [os.path.abspath(str(wt))]


def test_healthy_extra_paths_are_not_reported(tmp_path):
    wt, _ = _make_worktree(tmp_path, "fine", admin_exists=True)
    assert worktree_gc.orphaned_worktrees(str(tmp_path), extra_paths=[str(wt)]) == []


def test_duplicates_are_collapsed_and_output_is_sorted(tmp_path):
    a, _ = _make_worktree(tmp_path, "aaa", admin_exists=False)
    b, _ = _make_worktree(tmp_path, "bbb", admin_exists=False)
    found = worktree_gc.orphaned_worktrees(
        str(tmp_path), extra_paths=[str(b), str(a), str(a), str(b)]
    )
    assert [os.path.basename(o["path"]) for o in found] == ["aaa", "bbb"]


def test_the_report_names_the_missing_gitdir(tmp_path):
    wt, admin = _make_worktree(tmp_path, "named", admin_exists=False)
    lines = worktree_gc.report_orphaned_worktrees(str(tmp_path), extra_paths=[str(wt)])
    assert len(lines) == 1
    # Both halves have to be in the line: the directory to look at, and the path that is
    # missing. Without the second, the reader cannot tell this from an ordinary stale slot.
    assert str(wt) in lines[0]
    assert str(admin) in lines[0]
    assert "prune" in lines[0]


def test_a_clean_repo_reports_nothing(tmp_path):
    assert worktree_gc.report_orphaned_worktrees(str(tmp_path)) == []


def test_detection_never_raises_on_a_bad_repo_argument():
    # Detection that can take down its caller just gets wrapped in try/except everywhere.
    assert worktree_gc.orphaned_worktrees(None) == []
    assert worktree_gc.orphaned_worktrees("/definitely/not/a/repo") == []
    assert worktree_gc.report_orphaned_worktrees("") == []
