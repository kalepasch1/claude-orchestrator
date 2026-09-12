"""The QA overlay must be able to answer git's questions about itself.

`commit_overlay.materialize()` streams `git archive` into a scratch directory.
That gives files and nothing else, so a project whose tests shell out to git
fails there and only there:

    [gate:qa] staging QA failed -- fatal: not a git repository
    Error: Command failed: git ls-files -z

Two fleet projects pass in a clean checkout and are red at the gate for exactly
this reason. That is the gate being wrong ABOUT the project -- the mirror image
of the test_cmd drift, which told us a project was fine when it was not.

The fix attaches an independent gitdir (alternates + detached HEAD + read-tree),
not a registered worktree. These tests pin both halves: git works in the
overlay, and the source repo is untouched by the overlay existing.
"""
import os
import subprocess

import pytest

import commit_overlay


def _run(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=30)


def _git(cwd, *args):
    result = _run(cwd, "git", *args)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    _git(root, "init", "--quiet", "--initial-branch=main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "T")
    (root / "app.js").write_text("export const x = 1\n")
    (root / "tests").mkdir()
    (root / "tests" / "evidence.test.js").write_text("// asks git about the repo\n")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "initial")
    return root


def test_overlay_is_a_git_repository(repo, tmp_path):
    with commit_overlay.checkout(repo, "HEAD") as overlay:
        assert overlay["git_attached"] is True
        # The literal command that was failing at the gate.
        listed = _run(overlay["path"], "git", "ls-files", "-z")
        assert listed.returncode == 0, listed.stderr
        assert "fatal: not a git repository" not in listed.stderr
        assert "tests/evidence.test.js" in listed.stdout


def test_overlay_reports_the_commit_it_was_built_from(repo):
    head = _git(repo, "rev-parse", "HEAD")
    with commit_overlay.checkout(repo, "HEAD") as overlay:
        assert overlay["commit"] == head
        assert _git(overlay["path"], "rev-parse", "HEAD") == head


def test_overlay_of_an_older_commit_reports_that_commit(repo):
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "app.js").write_text("export const x = 2\n")
    _git(repo, "commit", "--quiet", "-am", "second")
    with commit_overlay.checkout(repo, first) as overlay:
        assert _git(overlay["path"], "rev-parse", "HEAD") == first
        assert (os.path.join(overlay["path"], "app.js"))
        with open(os.path.join(overlay["path"], "app.js")) as handle:
            assert handle.read() == "export const x = 1\n"


def test_overlay_tree_is_clean_so_a_suite_does_not_read_it_as_dirty(repo):
    with commit_overlay.checkout(repo, "HEAD") as overlay:
        status = _git(overlay["path"], "status", "--porcelain")
        assert status == ""


def test_overlay_does_not_register_a_worktree_in_the_source_repo(repo):
    with commit_overlay.checkout(repo, "HEAD") as overlay:
        assert overlay["registered_worktree"] is False
        listed = _git(repo, "worktree", "list")
        assert overlay["path"] not in listed
        assert not os.path.isdir(os.path.join(repo, ".git", "worktrees"))
    # And nothing is left behind pointing at a directory that no longer exists.
    assert _git(repo, "worktree", "list").count("\n") == 0


def test_overlay_borrows_objects_rather_than_copying_them(repo):
    with commit_overlay.checkout(repo, "HEAD") as overlay:
        alternates = os.path.join(overlay["path"], ".git", "objects", "info",
                                  "alternates")
        assert os.path.exists(alternates)
        with open(alternates) as handle:
            borrowed = handle.read().strip()
        assert os.path.realpath(borrowed) == os.path.realpath(
            os.path.join(repo, ".git", "objects"))


def test_source_repo_still_works_while_an_overlay_is_open(repo):
    with commit_overlay.checkout(repo, "HEAD"):
        # No index lock, no registry contention: the source repo can still commit.
        (repo / "app.js").write_text("export const x = 3\n")
        _git(repo, "commit", "--quiet", "-am", "while overlay open")
    assert _git(repo, "status", "--porcelain") == ""


def test_teardown_removes_the_whole_overlay_gitdir(repo):
    with commit_overlay.checkout(repo, "HEAD") as overlay:
        path = overlay["path"]
        assert os.path.isdir(os.path.join(path, ".git"))
    assert not os.path.exists(path)


def test_a_failed_attach_leaves_no_half_built_gitdir(repo, monkeypatch):
    """Fail-open, and fail without leaving something worse than nothing.

    A `.git` that exists but has no index answers `git ls-files` with silence
    and returncode 0 -- a suite would read that as an empty repository rather
    than as a broken overlay. So a failed attach removes it entirely, which puts
    the overlay back to exactly today's behaviour: plain files.
    """
    monkeypatch.setattr(commit_overlay, "_build_gitdir",
                        lambda *a, **k: False)
    with commit_overlay.checkout(repo, "HEAD") as overlay:
        assert overlay["git_attached"] is False
        assert not os.path.exists(os.path.join(overlay["path"], ".git"))
        # The files are still there -- the gate can still run a suite.
        assert os.path.exists(os.path.join(overlay["path"], "app.js"))


def test_an_exception_during_attach_is_not_raised_to_the_caller(repo, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("disk said no")

    monkeypatch.setattr(commit_overlay, "_build_gitdir", boom)
    with commit_overlay.checkout(repo, "HEAD") as overlay:
        assert overlay["git_attached"] is False
        assert os.path.exists(os.path.join(overlay["path"], "app.js"))


def test_materialize_still_returns_the_file_list_it_always_did(repo):
    with commit_overlay.checkout(repo, "HEAD") as overlay:
        # .git is not archive content and must not appear as project files.
        assert overlay["files"] == ["app.js", "tests/evidence.test.js"]
        assert not any(name.startswith(".git") for name in overlay["files"])
