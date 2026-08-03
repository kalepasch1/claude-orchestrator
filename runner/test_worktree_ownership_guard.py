"""Regression tests for worktree_ownership_guard.

The incident: in-flight work was destroyed three separate times on 2026-08-02. No single
command was at fault — it was the combination every bot uses:

    git add -A          sweeps up another agent's half-finished edits
    git commit --no-verify   skips the hooks that would have objected
    git reset --hard / auto-resolution   discards the working tree

Because the work was never committed there was no reflog entry and no dangling object, so
it was unrecoverable. These tests assert both halves of the fix: a destructive operation on
a dirty worktree the caller does not own is REFUSED, and the uncommitted state is pinned
into a rescue ref regardless — so even a caller that ignores the refusal cannot destroy it.

The clean controls matter as much: the guard must not obstruct an agent working in its own
worktree, or any operation on a clean tree.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault("db", type(sys)("db"))
import worktree_ownership_guard as wog  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=str(repo), capture_output=True,
                          text=True, timeout=60)


def _repo(tmp_path, name="r"):
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.email", "t@t.t")
    git(repo, "config", "user.name", "t")
    (repo / "tracked.py").write_text("def real():\n    return 42\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo


def _dirty(repo):
    """Simulate an agent with work in progress: an edit plus a brand-new file."""
    (repo / "tracked.py").write_text("def real():\n    return 42\n\n\ndef in_progress():\n    pass\n")
    (repo / "new_module.py").write_text("# half-finished work\n")


# ----------------------------------------------------------------------- refusal

def test_refuses_destructive_op_on_dirty_worktree_owned_by_another_actor(tmp_path):
    repo = _repo(tmp_path)
    wog.claim(str(repo), "agent-alpha")
    _dirty(repo)
    ok, log = wog.guard_destructive(str(repo), actor="agent-beta", op="git reset --hard")
    assert ok is False
    assert "REFUSED" in log
    assert "agent-alpha" in log and "agent-beta" in log
    assert "2026-08-02" in log, "the refusal should cite the incident it prevents"


def test_refuses_when_owner_is_unknown_and_tree_is_dirty(tmp_path):
    """Fail-closed. 'I don't know who owns this' is the state the fleet kept guessing in."""
    repo = _repo(tmp_path)
    _dirty(repo)
    ok, log = wog.guard_destructive(str(repo), actor="agent-beta", op="git clean -fd")
    assert ok is False
    assert "owner UNKNOWN" in log


def test_refusal_lists_the_work_at_risk(tmp_path):
    repo = _repo(tmp_path)
    _dirty(repo)
    ok, log = wog.guard_destructive(str(repo), actor="bot", op="git add -A")
    assert ok is False
    assert "new_module.py" in log, "untracked in-progress files must be named"
    assert "tracked.py" in log


# ----------------------------------------------------------------------- rescue

def test_work_is_rescued_into_a_ref_before_refusal(tmp_path):
    """Even a caller that ignores the refusal cannot make the work unrecoverable."""
    repo = _repo(tmp_path)
    _dirty(repo)
    ok, log = wog.guard_destructive(str(repo), actor="bot", op="git reset --hard")
    assert ok is False
    assert "RESCUED to refs/orch-rescue/" in log

    refs = git(repo, "for-each-ref", "--format=%(refname)", "refs/orch-rescue").stdout.split()
    assert refs, "a rescue ref must exist"

    # The rescued commit really contains the in-progress edit.
    blob = git(repo, "show", refs[0] + ":tracked.py").stdout
    assert "in_progress" in blob, "the rescue ref must pin the uncommitted content"


def test_rescue_does_not_disturb_the_working_tree(tmp_path):
    """`git stash create` must not move the agent's files out from under it."""
    repo = _repo(tmp_path)
    _dirty(repo)
    before = (repo / "tracked.py").read_text()
    wog.rescue(str(repo), "test")
    assert (repo / "tracked.py").read_text() == before
    assert (repo / "new_module.py").exists()
    assert git(repo, "stash", "list").stdout.strip() == "", "the stash list must be untouched"


def test_rescue_on_clean_tree_is_a_noop(tmp_path):
    repo = _repo(tmp_path)
    assert wog.rescue(str(repo), "test") is None


def test_periodic_rescue_is_recoverable(tmp_path):
    """End-to-end: destroy the work, then recover it from the rescue ref."""
    repo = _repo(tmp_path)
    _dirty(repo)
    saved = wog.rescue(str(repo), "periodic sweep")
    assert saved

    git(repo, "reset", "--hard")
    git(repo, "clean", "-fdq")
    assert "in_progress" not in (repo / "tracked.py").read_text()

    git(repo, "checkout", saved["ref"], "--", ".")
    assert "in_progress" in (repo / "tracked.py").read_text(), "work must be recoverable"


# ----------------------------------------------------------------- clean controls

def test_owner_may_operate_on_its_own_dirty_worktree(tmp_path):
    """The guard must not obstruct an agent working in the worktree it created."""
    repo = _repo(tmp_path)
    wog.claim(str(repo), "agent-alpha")
    _dirty(repo)
    ok, log = wog.guard_destructive(str(repo), actor="agent-alpha", op="git reset --hard")
    assert ok is True, log
    assert "owns this worktree" in log


def test_clean_worktree_allows_any_operation(tmp_path):
    repo = _repo(tmp_path)
    ok, log = wog.guard_destructive(str(repo), actor="anyone", op="git reset --hard")
    assert ok is True
    assert "clean" in log


def test_non_directory_is_skipped(tmp_path):
    ok, _ = wog.guard_destructive(str(tmp_path / "nope"), actor="bot")
    assert ok is True


def test_claim_and_owner_of_roundtrip(tmp_path):
    repo = _repo(tmp_path)
    assert wog.owner_of(str(repo)) is None
    wog.claim(str(repo), "agent-alpha")
    assert wog.owner_of(str(repo)) == "agent-alpha"


def test_is_dirty_detects_untracked_only(tmp_path):
    repo = _repo(tmp_path)
    assert wog.is_dirty(str(repo))[0] is False
    (repo / "brand_new.py").write_text("x = 1\n")
    dirty, entries = wog.is_dirty(str(repo))
    assert dirty is True and entries


def test_unreadable_repo_is_treated_as_dirty(tmp_path):
    """Fail-closed: if git status cannot answer, assume there is work to protect."""
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    assert wog.is_dirty(str(plain))[0] is True


def test_break_glass_allows_but_still_rescues(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _dirty(repo)
    monkeypatch.setattr(wog, "BREAK_GLASS", True)
    ok, log = wog.guard_destructive(str(repo), actor="bot", op="git reset --hard")
    assert ok is True
    assert "BREAK-GLASS" in log
    refs = git(repo, "for-each-ref", "--format=%(refname)", "refs/orch-rescue").stdout.split()
    assert refs, "break-glass must still preserve the work"


def test_disabled_guard_allows(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _dirty(repo)
    monkeypatch.setattr(wog, "ENABLED", False)
    ok, _ = wog.guard_destructive(str(repo), actor="bot")
    assert ok is True
