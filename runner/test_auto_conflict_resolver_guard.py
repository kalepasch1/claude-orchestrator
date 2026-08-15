"""Contract tests for auto_conflict_resolver's merge safety net.

This module authored every `Merge branch '...' (auto-resolved)` commit in the log and has
now been clobbered twice by its own unverified merge path (most recently dc288ea5, which
deleted _regression_check itself). These tests make the contract executable:

  1. a merge that deletes or stubs code is ROLLED BACK and the branch is PRESERVED
  2. a healthy merge still lands
  3. `union` produces a real union of both sides, never conflict markers
  4. `_resolved_ok` rejects markers and unparseable output
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault("db", type(sys)("db"))   # acr imports db lazily/optionally
import auto_conflict_resolver as acr  # noqa: E402

BASE_LIB = (
    "def branch_exists_anywhere(repo, branch):\n"
    '    """Real implementation."""\n'
    "    if local_exists(repo, branch):\n"
    "        return True\n"
    "    fetch_refs(repo)\n"
    "    return local_exists(repo, 'origin/' + branch)\n"
    "\n"
    "def local_exists(repo, b):\n"
    "    return b in repo\n"
    "\n"
    "def fetch_refs(repo):\n"
    "    return None\n"
)


def git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=repo,
                          capture_output=True, text=True, timeout=60)


@pytest.fixture
def repo(tmp_path):
    r = str(tmp_path / "repo")
    os.makedirs(r)
    git(r, "init", "-q", "-b", "master")
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    git(r, "config", "core.hooksPath", "/dev/null")  # isolate the in-code gate from the hook
    (tmp_path / "repo" / "lib.py").write_text(BASE_LIB)
    (tmp_path / "repo" / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    (tmp_path / "repo" / ".gitignore").write_text("node_modules\n.env\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    return r


def head(r):
    return git(r, "rev-parse", "HEAD").stdout.strip()


def test_stubbing_merge_is_rolled_back_and_branch_preserved(repo, tmp_path):
    base = head(repo)
    git(repo, "checkout", "-q", "-b", "agent/bad", base)
    (tmp_path / "repo" / "lib.py").write_text(
        "def branch_exists_anywhere(repo, branch):\n"
        "    # Placeholder implementation\n"
        "    return False\n"
        "\n"
        "def local_exists(repo, b):\n"
        "    return b in repo\n"
        "\n"
        "def fetch_refs(repo):\n"
        "    return None\n"
        "\n"
        "def brand_new_feature():\n"
        "    return 'shiny'\n")
    git(repo, "rm", "-q", "package-lock.json")
    git(repo, "commit", "-qam", "agent: add brand_new_feature")
    git(repo, "checkout", "-q", "master")

    result = acr.resolve_branch(repo, "agent/bad", "master")

    assert result["merged"] is False
    assert result["strategy"] == "regression-blocked"
    assert "branch_exists_anywhere" in result["error"]
    assert "package-lock.json" in result["error"]
    assert head(repo) == base, "the destructive merge must be reset away"
    assert "agent/bad" in git(repo, "branch").stdout, (
        "the branch is the only remaining copy of that work — never delete it on rejection")
    assert os.path.exists(os.path.join(repo, "package-lock.json"))


def test_healthy_merge_still_lands(repo, tmp_path):
    base = head(repo)
    git(repo, "checkout", "-q", "-b", "agent/good", base)
    (tmp_path / "repo" / "lib.py").write_text(
        BASE_LIB + "\ndef extra_helper():\n    return 42\n")
    git(repo, "commit", "-qam", "agent: add extra_helper")
    git(repo, "checkout", "-q", "master")

    result = acr.resolve_branch(repo, "agent/good", "master")

    assert result["merged"] is True, result["error"]
    assert head(repo) != base
    assert "extra_helper" in (tmp_path / "repo" / "lib.py").read_text()
    assert "def branch_exists_anywhere" in (tmp_path / "repo" / "lib.py").read_text()


def test_union_keeps_both_sides_and_leaves_no_conflict_markers(repo, tmp_path, monkeypatch):
    """The old code ran `merge-file --union path path path` — merging a file with ITSELF —
    then returned True unconditionally, staging the conflict-marked file."""
    monkeypatch.setattr(acr, "MAX_CONFLICT_FILES", 5)
    base = head(repo)
    git(repo, "checkout", "-q", "-b", "agent/u", base)
    (tmp_path / "repo" / ".gitignore").write_text("node_modules\n.env\n.branch-only\n")
    git(repo, "commit", "-qam", "agent: branch ignore entry")
    git(repo, "checkout", "-q", "master")
    (tmp_path / "repo" / ".gitignore").write_text("node_modules\n.env\n.master-only\n")
    git(repo, "commit", "-qam", "master: master ignore entry")

    result = acr.resolve_branch(repo, "agent/u", "master")

    assert result["merged"] is True, result["error"]
    text = (tmp_path / "repo" / ".gitignore").read_text()
    assert ".branch-only" in text and ".master-only" in text, "union dropped a side: " + text
    for marker in acr.CONFLICT_MARKERS:
        assert marker not in text, "conflict markers were committed: " + text


def test_resolved_ok_rejects_markers_and_broken_syntax(tmp_path):
    d = str(tmp_path)
    (tmp_path / "clean.py").write_text("def f():\n    return 1\n")
    (tmp_path / "marked.py").write_text("<<<<<<< HEAD\nx=1\n=======\nx=2\n>>>>>>> other\n")
    (tmp_path / "broken.py").write_text("def f(:\n")
    (tmp_path / "bad.json").write_text('{"a":')
    (tmp_path / "anything.txt").write_text("free text is fine\n")

    assert acr._resolved_ok(d, "clean.py") is True
    assert acr._resolved_ok(d, "marked.py") is False
    assert acr._resolved_ok(d, "broken.py") is False
    assert acr._resolved_ok(d, "bad.json") is False
    assert acr._resolved_ok(d, "anything.txt") is True
    assert acr._resolved_ok(d, "missing.py") is False
