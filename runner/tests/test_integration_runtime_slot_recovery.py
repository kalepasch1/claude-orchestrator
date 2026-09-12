"""Slot recovery: the two branch-attached paths that stalled the train.

A single branch-attached integration slot used to be a hard error with no
recovery, so one bad slot blocked every merge for its project indefinitely —
the 581-skipped/0-merged stall. The fix draws a line through the middle of
"branch-attached":

* attached but CLEAN   -> re-detach the slot in place and keep using it
* attached and DIRTY   -> preserve the slot as evidence, run in a temp slot

`test_dirty_persistent_slot_is_preserved_and_bypassed` already covers the
dirty half. These cover the clean half — the branch that actually restores
throughput — plus the accounting that says which branch was taken, so a
regression shows up as a named reason rather than as a slot count.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import integration_runtime


#: Bound every git call; the suite warns on unbounded subprocesses in tests.
GIT_TIMEOUT = 30


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
        timeout=GIT_TIMEOUT,
    )


def head_is_detached(path) -> bool:
    return subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"], cwd=path, capture_output=True,
        timeout=GIT_TIMEOUT,
    ).returncode != 0


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "canonical"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    (root / "tracked.txt").write_text("one\n")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "initial")
    return root


def test_branch_attached_clean_slot_self_detaches(repo, tmp_path, monkeypatch):
    """The throughput fix: a clean attached slot is reused, not condemned."""
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))

    with integration_runtime.isolated_repo(str(repo), "first") as persistent:
        pass

    # Leave the persistent slot attached to a branch but otherwise pristine —
    # the state that used to raise and block every subsequent merge.
    git(persistent, "checkout", "-b", "stuck-on-a-branch")
    assert not head_is_detached(persistent)

    with integration_runtime.isolated_repo(str(repo), "second") as reused:
        # Same slot: it recovered in place rather than falling back to a temp.
        assert os.path.realpath(reused) == os.path.realpath(persistent)
        # And it detached itself.
        assert head_is_detached(reused)


def test_branch_attached_clean_slot_does_not_leak_a_temp_slot(repo, tmp_path, monkeypatch):
    """Self-detaching must not also create the temporary it was avoiding."""
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))

    with integration_runtime.isolated_repo(str(repo), "first") as persistent:
        pass
    git(persistent, "checkout", "-b", "stuck-on-a-branch")

    with integration_runtime.isolated_repo(str(repo), "second"):
        pass

    siblings = list(Path(persistent).parent.glob("*-run-*"))
    assert siblings == [], f"a temporary slot was created unnecessarily: {siblings}"


def test_branch_attached_dirty_slot_falls_back_to_temp(repo, tmp_path, monkeypatch):
    """The other half of the line: real work is preserved, never reset."""
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))

    with integration_runtime.isolated_repo(str(repo), "first") as persistent:
        pass

    git(persistent, "checkout", "-b", "stuck-on-a-branch")
    (Path(persistent) / "tracked.txt").write_text("real work in progress\n")
    git(persistent, "add", "tracked.txt")

    with integration_runtime.isolated_repo(str(repo), "second") as replacement:
        assert os.path.realpath(replacement) != os.path.realpath(persistent)
        assert head_is_detached(replacement)
        assert subprocess.run(
            ["git", "status", "--porcelain=v1"], cwd=replacement,
            capture_output=True, text=True, check=True, timeout=GIT_TIMEOUT,
        ).stdout == ""

    # The evidence survives untouched.
    assert (Path(persistent) / "tracked.txt").read_text() == "real work in progress\n"


# --- skip-reason accounting ----------------------------------------------
#
# The stall was invisible for days because every pass logged the same line and
# nothing counted WHY a slot was bypassed. These pin the reason each branch
# reports, so "581 skipped" can be attributed instead of merely observed.

def _reasons(capsys) -> str:
    return capsys.readouterr().out


def test_clean_attached_slot_reports_no_bypass(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    with integration_runtime.isolated_repo(str(repo), "first") as persistent:
        pass
    git(persistent, "checkout", "-b", "stuck-on-a-branch")
    capsys.readouterr()

    with integration_runtime.isolated_repo(str(repo), "second"):
        pass

    out = _reasons(capsys)
    assert "preserving" not in out, f"a reusable slot was reported as bypassed: {out}"


def test_dirty_attached_slot_reports_why_it_was_bypassed(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    with integration_runtime.isolated_repo(str(repo), "first") as persistent:
        pass
    git(persistent, "checkout", "-b", "stuck-on-a-branch")
    (Path(persistent) / "tracked.txt").write_text("real work\n")
    git(persistent, "add", "tracked.txt")
    capsys.readouterr()

    with integration_runtime.isolated_repo(str(repo), "second"):
        pass

    out = _reasons(capsys)
    assert "preserving" in out
    assert "temp slot" in out or "temporary" in out


def test_regenerable_dirt_is_reclaimed_rather_than_counted_as_a_skip(
    repo, tmp_path, monkeypatch, capsys
):
    """Machine output must not condemn a slot — that was 3 of 21 stuck slots."""
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    with integration_runtime.isolated_repo(str(repo), "first") as persistent:
        pass

    cache = Path(persistent) / "__pycache__"
    cache.mkdir(exist_ok=True)
    (cache / "stale.pyc").write_bytes(b"\x00")
    capsys.readouterr()

    with integration_runtime.isolated_repo(str(repo), "second") as reused:
        assert os.path.realpath(reused) == os.path.realpath(persistent)
