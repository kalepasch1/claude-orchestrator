"""A conflict redo is only spent when it can plausibly help.

A redo exists for one situation: the branch forked from a stale base, so rebuilding it on
a fresh base clears the conflict. When the SAME files conflict again after a redo, the
conflict is in the work itself and every remaining redo is a full agent rebuild that ends
at the identical "needs manual rebase" verdict — the behaviour seen with
runner/config_consumer.py. These tests pin the detection and, just as importantly, pin
that an UNKNOWN conflict set never triggers an early stop.
"""
import os
import subprocess
import sys
import types

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import approval_merge as am  # noqa: E402

FILES = ["runner/config_consumer.py", "runner/db.py"]


# --- should_stop_redoing --------------------------------------------------------------

def test_identical_conflict_set_stops_early():
    assert am.should_stop_redoing(FILES, FILES) is True


def test_subset_still_stops_early():
    """Partial progress that stalls on the rest is still convergence to a manual rebase."""
    assert am.should_stop_redoing(FILES, ["runner/config_consumer.py"]) is True


def test_new_conflicting_file_keeps_retrying():
    assert am.should_stop_redoing(FILES, FILES + ["runner/new.py"]) is False


def test_different_conflict_set_keeps_retrying():
    assert am.should_stop_redoing(FILES, ["app/other.py"]) is False


def test_unknown_conflict_set_never_stops_early():
    """No evidence must mean "retry as before", never "declare permanent"."""
    assert am.should_stop_redoing([], FILES) is False
    assert am.should_stop_redoing(FILES, []) is False
    assert am.should_stop_redoing(None, None) is False


def test_order_and_duplicates_do_not_matter():
    assert am.should_stop_redoing(
        ["b.py", "a.py", "a.py"], ["a.py", "b.py"]) is True


# --- note round trip ------------------------------------------------------------------

def test_conflict_files_round_trip():
    note = "merge-handler: conflict " + am.encode_conflict_files(FILES)
    assert am.decode_conflict_files(note) == sorted(FILES)


def test_decode_is_fail_soft():
    assert am.decode_conflict_files(None) == []
    assert am.decode_conflict_files("") == []
    assert am.decode_conflict_files("no tag here") == []
    assert am.decode_conflict_files("[conflict-files:unterminated") == []
    assert am.decode_conflict_files("[conflict-files:]") == []


def test_encode_of_nothing_is_empty():
    assert am.encode_conflict_files([]) == ""
    assert am.encode_conflict_files(None) == ""


# --- conflicting_files ----------------------------------------------------------------

def test_conflicting_files_empty_on_clean_merge(monkeypatch):
    monkeypatch.setattr(am.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=0, stdout="abc123\n", stderr=""))
    assert am.conflicting_files("/repo", "master", "agent/x") == []


def test_conflicting_files_drops_the_tree_oid(monkeypatch):
    stdout = "0123456789abcdef0123456789abcdef01234567\nrunner/config_consumer.py\nrunner/db.py\n"
    monkeypatch.setattr(am.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=1, stdout=stdout, stderr=""))
    assert am.conflicting_files("/repo", "master", "agent/x") == sorted(FILES)


def test_conflicting_files_is_fail_soft(monkeypatch):
    def boom(*a, **k):
        raise OSError("git missing")
    monkeypatch.setattr(am.subprocess, "run", boom)
    assert am.conflicting_files("/repo", "master", "agent/x") == []


def test_conflicting_files_does_not_mutate_the_repo(monkeypatch):
    """The check must be read-only: in-memory merge-tree, never a checkout or worktree."""
    seen = {}

    def record(cmd, *a, **k):
        seen["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(am.subprocess, "run", record)
    am.conflicting_files("/repo", "master", "agent/x")
    assert seen["cmd"][:3] == ["git", "merge-tree", "--write-tree"]
    assert not {"checkout", "worktree", "merge", "rebase"} & set(seen["cmd"])


# --- end to end over real git ---------------------------------------------------------

def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


@pytest.fixture
def conflicted_repo(tmp_path):
    repo = str(tmp_path / "r")
    os.makedirs(repo)
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    target = os.path.join(repo, "runner")
    os.makedirs(target)
    path = os.path.join(target, "config_consumer.py")
    open(path, "w").write("VALUE = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "agent/x")
    open(path, "w").write("VALUE = 2\n")
    _git(repo, "commit", "-qam", "branch side")
    _git(repo, "checkout", "-q", "master")
    open(path, "w").write("VALUE = 3\n")
    _git(repo, "commit", "-qam", "master side")
    return repo


def test_real_conflict_is_reported_by_path(conflicted_repo):
    files = am.conflicting_files(conflicted_repo, "master", "agent/x")
    assert files == ["runner/config_consumer.py"]
    assert am.should_stop_redoing(files, files) is True


def test_real_clean_merge_reports_nothing(conflicted_repo):
    _git(conflicted_repo, "checkout", "-qb", "agent/clean", "master")
    open(os.path.join(conflicted_repo, "unrelated.txt"), "w").write("hi\n")
    _git(conflicted_repo, "add", "-A")
    _git(conflicted_repo, "commit", "-qm", "clean")
    assert am.conflicting_files(conflicted_repo, "master", "agent/clean") == []
