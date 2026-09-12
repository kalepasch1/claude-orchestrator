"""One repo, one lock — whatever path spelling the caller happens to have.

`_lock_path` hashed the RAW STRING, so two spellings of the same directory produced
two different lock files and did not exclude each other at all. Verified on the live
machine 2026-09-03, where ~/claude-orchestrator is a symlink to its real path:

    /Users/kpasch/claude-orchestrator                      -> repo-96d7193fa0854cac
    /Users/kpasch/Documents/beethoven/claude-orchestrator  -> repo-2b7b112e1dbf0ca3
    same repo on disk: True        mutually exclusive: False

A caller reaching a repo through the symlink takes a lock that protects nothing while
another process mutates the same working copy under the other key — precisely the
failure this module exists to prevent, and the same shape as the build-proof identity
bug fixed the same day: an identity derived from a path spelling rather than from the
thing itself.

It also explains the litter: 1,239 repo-*.lock files for a fleet of sixteen repos,
only 44 touched in the previous six hours.
"""
import os

import pytest

import repo_lock


@pytest.fixture(autouse=True)
def lock_dir(monkeypatch, tmp_path):
    d = tmp_path / "locks"
    d.mkdir()
    monkeypatch.setattr(repo_lock, "LOCK_DIR", str(d))
    return d


@pytest.fixture
def repo_and_symlink(tmp_path):
    real = tmp_path / "real-repo"
    real.mkdir()
    link = tmp_path / "link-to-repo"
    link.symlink_to(real, target_is_directory=True)
    return str(real), str(link)


# ── the bug ───────────────────────────────────────────────────────────────────

def test_a_symlink_and_its_target_share_one_lock(repo_and_symlink):
    real, link = repo_and_symlink
    assert os.path.realpath(real) == os.path.realpath(link)
    assert repo_lock._lock_path(real) == repo_lock._lock_path(link)


def test_the_same_repo_cannot_be_locked_twice_through_two_spellings(repo_and_symlink):
    """The property the whole module exists for, stated directly."""
    real, link = repo_and_symlink
    with repo_lock.hold(real, timeout=1) as got_real:
        assert got_real is True
        with repo_lock.hold(link, timeout=1) as got_link:
            assert got_link is False, \
                "the same working copy was locked twice through two path spellings"


def test_a_trailing_slash_is_the_same_repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    assert repo_lock._lock_path(str(d)) == repo_lock._lock_path(str(d) + "/")


def test_a_dot_dot_path_is_the_same_repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    (tmp_path / "sibling").mkdir()
    indirect = str(tmp_path / "sibling" / ".." / "repo")
    assert repo_lock._lock_path(str(d)) == repo_lock._lock_path(indirect)


# ── what must NOT change ──────────────────────────────────────────────────────

def test_two_genuinely_different_repos_still_get_different_locks(tmp_path):
    """The dangerous direction. Collapsing two real repos would serialise the fleet
    on work that has no reason to contend."""
    a = tmp_path / "repo-a"
    b = tmp_path / "repo-b"
    a.mkdir()
    b.mkdir()
    assert repo_lock._lock_path(str(a)) != repo_lock._lock_path(str(b))
    with repo_lock.hold(str(a), timeout=1) as got_a:
        with repo_lock.hold(str(b), timeout=1) as got_b:
            assert got_a is True and got_b is True, \
                "two different repos must still be lockable at the same time"


def test_a_path_that_cannot_be_resolved_still_yields_a_stable_key():
    """Falling back to the raw string still serialises callers that share it —
    strictly better than raising inside a lock helper."""
    key1 = repo_lock._lock_path("/definitely/not/on/this/disk")
    key2 = repo_lock._lock_path("/definitely/not/on/this/disk")
    assert key1 == key2
    assert key1.endswith(".lock")


def test_empty_and_none_do_not_raise():
    for value in (None, "", "   "):
        assert repo_lock._lock_path(value).endswith(".lock")


def test_canonical_never_raises(monkeypatch):
    def boom(path):
        raise OSError("resolution exploded")

    monkeypatch.setattr(repo_lock.os.path, "realpath", boom)
    assert repo_lock._canonical("/some/repo") == "/some/repo"


def test_the_lock_is_still_released_on_exit(repo_and_symlink):
    real, _ = repo_and_symlink
    with repo_lock.hold(real, timeout=1) as got:
        assert got is True
    with repo_lock.hold(real, timeout=1) as again:
        assert again is True, "the lock was not released"
