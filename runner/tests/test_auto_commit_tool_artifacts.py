"""An agent that commits its own chat transcript has not done the task.

Measured 2026-08-24 on a controlled fleet verification. Ten canary tasks each
asked for exactly one line in one file. agent/canary-fleet-verify-20260824-a1
came back with 378 insertions across 6 files:

    .aider.chat.history.md, .aider.input.history,
    .aider.tags.cache.v4/cache.db (+ -shm, -wal), and a recovery-intent stub

README.md was untouched, and the requested string appeared ONLY inside the aider
chat transcript. The agent was told to do it, discussed it, and committed the
conversation. `git add -A` in a repo with no .gitignore swept it all in.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_commit


def _run(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=30)


@pytest.fixture
def repo(tmp_path):
    _run(tmp_path, "init", "-q", "-b", "master")
    _run(tmp_path, "config", "user.email", "t@t.test")
    _run(tmp_path, "config", "user.name", "t")
    (tmp_path / "README.md").write_text("hello\n")
    _run(tmp_path, "add", "-A")
    _run(tmp_path, "commit", "-qm", "base")
    return tmp_path


def _staged_in_head(repo):
    out = _run(repo, "show", "--name-only", "--format=", "HEAD").stdout
    return {l.strip() for l in out.splitlines() if l.strip()}


def test_real_work_still_commits(repo):
    (repo / "README.md").write_text("hello\nfleet verify A\n")
    r = auto_commit.stage_and_commit(str(repo), slug="s", message="m")
    assert r["committed"] is True
    assert "README.md" in _staged_in_head(repo)


def test_tool_artifacts_are_excluded_from_a_real_commit(repo):
    (repo / "README.md").write_text("hello\nfleet verify A\n")
    (repo / ".aider.chat.history.md").write_text("i will edit the readme\n")
    (repo / ".aider.input.history").write_text("prompt\n")
    r = auto_commit.stage_and_commit(str(repo), slug="s", message="m")
    assert r["committed"] is True
    files = _staged_in_head(repo)
    assert "README.md" in files
    assert not any(f.startswith(".aider") for f in files), files


def test_only_tool_artifacts_means_no_product_change(repo):
    """The exact observed failure: nothing but the transcript changed."""
    (repo / ".aider.chat.history.md").write_text("i will edit the readme\n")
    (repo / ".aider.input.history").write_text("prompt\n")
    r = auto_commit.stage_and_commit(str(repo), slug="s", message="m")
    assert r["committed"] is False
    assert r["status"] == "no_product_change"
    assert any(".aider" in e for e in r["excluded"])


def test_the_sqlite_cache_and_its_wal_are_excluded(repo):
    cache = repo / ".aider.tags.cache.v4"
    cache.mkdir()
    (cache / "cache.db").write_bytes(b"SQLite format 3\x00")
    (cache / "cache.db-shm").write_bytes(b"\x00")
    (cache / "cache.db-wal").write_bytes(b"\x00")
    (repo / "README.md").write_text("hello\nreal change\n")
    r = auto_commit.stage_and_commit(str(repo), slug="s", message="m")
    assert r["committed"] is True
    files = _staged_in_head(repo)
    assert not any("cache.db" in f for f in files), files


def test_pycache_and_ds_store_are_excluded(repo):
    (repo / "README.md").write_text("hello\nreal\n")
    pyc = repo / "pkg" / "__pycache__"
    pyc.mkdir(parents=True)
    (pyc / "m.cpython-39.pyc").write_bytes(b"\x00")
    (repo / ".DS_Store").write_bytes(b"\x00")
    r = auto_commit.stage_and_commit(str(repo), slug="s", message="m")
    assert r["committed"] is True
    files = _staged_in_head(repo)
    assert not any("__pycache__" in f or ".DS_Store" in f for f in files), files


def test_a_clean_tree_is_still_clean_not_no_product_change(repo):
    r = auto_commit.stage_and_commit(str(repo), slug="s", message="m")
    assert r["committed"] is False
    assert r["status"] == "clean"


def test_a_file_merely_named_like_a_tool_artifact_is_kept(repo):
    """`aider_notes.md` is product; `.aider.input.history` is not."""
    (repo / "aider_notes.md").write_text("design notes\n")
    r = auto_commit.stage_and_commit(str(repo), slug="s", message="m")
    assert r["committed"] is True
    assert "aider_notes.md" in _staged_in_head(repo)
