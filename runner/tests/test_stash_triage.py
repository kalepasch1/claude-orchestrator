#!/usr/bin/env python3
"""Tests for runner/stash_triage.py — read-only stash triage addressed by SHA.

Uses a real throwaway git repo so the classification is exercised against real git,
not mocks. Nothing here touches the orchestrator repo's own stashes.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stash_triage as st  # noqa: E402


def _run(repo, *args, **kw):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True,
                          text=True, check=False, **kw)


@pytest.fixture
def repo(tmp_path):
    r = str(tmp_path / "r")
    os.makedirs(r)
    _run(r, "init", "-q", "-b", "main")
    _run(r, "config", "user.name", "t")
    _run(r, "config", "user.email", "t@example.com")
    (tmp_path / "r" / "a.txt").write_text("one\n")
    _run(r, "add", "-A")
    _run(r, "commit", "-q", "-m", "base")
    return r


def _write(repo, name, text):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(text)


# --- list_stashes -----------------------------------------------------------

def test_list_stashes_empty_repo(repo):
    assert st.list_stashes(repo) == []


def test_list_stashes_missing_repo_is_fail_soft():
    assert st.list_stashes("/nonexistent/path/for/tests") == []
    assert st.list_stashes("") == []
    assert st.list_stashes(None) == []


def test_list_stashes_returns_stable_sha(repo):
    _write(repo, "a.txt", "changed\n")
    _run(repo, "stash", "push", "-q", "-m", "first")
    rows = st.list_stashes(repo)
    assert len(rows) == 1
    assert len(rows[0]["sha"]) == 40
    assert rows[0]["ref"] == "stash@{0}"


def test_sha_is_stable_while_index_shifts(repo):
    """The whole point: stash@{N} moves, the SHA does not."""
    _write(repo, "a.txt", "first\n")
    _run(repo, "stash", "push", "-q", "-m", "first")
    first_sha = st.list_stashes(repo)[0]["sha"]
    assert st.list_stashes(repo)[0]["ref"] == "stash@{0}"

    _write(repo, "a.txt", "second\n")
    _run(repo, "stash", "push", "-q", "-m", "second")
    rows = {r["sha"]: r["ref"] for r in st.list_stashes(repo)}
    # same stash, new index
    assert rows[first_sha] == "stash@{1}"


# --- stash_files / stash_patch ---------------------------------------------

def test_stash_files_lists_touched_paths(repo):
    _write(repo, "a.txt", "changed\n")
    _run(repo, "stash", "push", "-q")
    sha = st.list_stashes(repo)[0]["sha"]
    assert st.stash_files(repo, sha) == ["a.txt"]


def test_stash_patch_non_empty(repo):
    _write(repo, "a.txt", "changed\n")
    _run(repo, "stash", "push", "-q")
    sha = st.list_stashes(repo)[0]["sha"]
    assert "a.txt" in st.stash_patch(repo, sha)


def test_stash_helpers_fail_soft_on_bad_sha(repo):
    assert st.stash_files(repo, "deadbeef" * 5) == []
    assert st.stash_patch(repo, "") == ""
    assert st.stash_files(repo, None) == []


# --- classify ---------------------------------------------------------------

def test_classify_recoverable(repo):
    _write(repo, "a.txt", "changed\n")
    _run(repo, "stash", "push", "-q")
    sha = st.list_stashes(repo)[0]["sha"]
    rec = st.classify(repo, sha)
    assert rec["class"] == st.RECOVERABLE
    assert rec["files"] == ["a.txt"]


def test_classify_already_landed(repo):
    _write(repo, "a.txt", "changed\n")
    _run(repo, "stash", "push", "-q")
    sha = st.list_stashes(repo)[0]["sha"]
    # land the same content on HEAD
    _write(repo, "a.txt", "changed\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "land it")
    assert st.classify(repo, sha)["class"] == st.ALREADY_LANDED


def test_classify_conflicted(repo):
    _write(repo, "a.txt", "stashed\n")
    _run(repo, "stash", "push", "-q")
    sha = st.list_stashes(repo)[0]["sha"]
    # move the file out from under the patch
    _write(repo, "a.txt", "totally different content\nsecond line\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "diverge")
    rec = st.classify(repo, sha)
    assert rec["class"] == st.CONFLICTED
    assert rec["reason"]


def test_classify_never_raises_on_garbage():
    rec = st.classify("/nonexistent/repo", "nope")
    assert rec["class"] in st.CLASSES


# --- priority ---------------------------------------------------------------

def test_is_priority_matches_runner_paths():
    assert st.is_priority(["runner/foo.py"]) is True
    assert st.is_priority(["docs/x.md", "runner/bar.py"]) is True
    assert st.is_priority(["docs/x.md"]) is False
    assert st.is_priority([]) is False
    assert st.is_priority(None) is False


# --- triage / next_conflicted / recoverable_shas ----------------------------

def test_triage_counts(repo):
    _write(repo, "a.txt", "changed\n")
    _run(repo, "stash", "push", "-q")
    report = st.triage(repo)
    assert report["total"] == 1
    assert report["counts"][st.RECOVERABLE] == 1
    assert sum(report["counts"].values()) == report["total"]


def test_triage_empty_repo(repo):
    report = st.triage(repo)
    assert report["total"] == 0
    assert report["records"] == []
    assert st.next_conflicted(report) is None
    assert st.recoverable_shas(report) == []


def test_triage_respects_limit(repo):
    for i in range(3):
        _write(repo, "a.txt", "v%s\n" % i)
        _run(repo, "stash", "push", "-q")
    assert st.triage(repo, limit=2)["total"] == 2
    assert st.triage(repo, limit=0)["total"] == 0


def test_recoverable_shas_are_stable_shas(repo):
    _write(repo, "a.txt", "changed\n")
    _run(repo, "stash", "push", "-q")
    shas = st.recoverable_shas(st.triage(repo))
    assert len(shas) == 1 and len(shas[0]) == 40


def test_next_conflicted_prefers_priority_paths():
    report = {"records": [
        {"class": st.CONFLICTED, "sha": "a", "priority": False, "files": ["docs/x.md", "y.md"]},
        {"class": st.CONFLICTED, "sha": "b", "priority": True, "files": ["runner/x.py"]},
        {"class": st.RECOVERABLE, "sha": "c", "priority": True, "files": ["runner/y.py"]},
    ]}
    assert st.next_conflicted(report)["sha"] == "b"


def test_next_conflicted_returns_one_not_a_batch():
    report = {"records": [
        {"class": st.CONFLICTED, "sha": "a", "priority": True, "files": ["runner/a.py"]},
        {"class": st.CONFLICTED, "sha": "b", "priority": True, "files": ["runner/b.py"]},
    ]}
    out = st.next_conflicted(report)
    assert isinstance(out, dict) and out["sha"] in ("a", "b")


def test_next_conflicted_fail_soft_on_garbage():
    assert st.next_conflicted(None) is None
    assert st.next_conflicted({}) is None
    assert st.recoverable_shas(None) == []


# --- summarize / read-only guarantee ----------------------------------------

def test_summarize_is_one_line(repo):
    line = st.summarize(st.triage(repo))
    assert "\n" not in line and "stashes" in line


def test_summarize_fail_soft():
    assert isinstance(st.summarize(None), str)


def test_triage_never_drops_or_pops_a_stash(repo):
    _write(repo, "a.txt", "changed\n")
    _run(repo, "stash", "push", "-q")
    before = [r["sha"] for r in st.list_stashes(repo)]
    st.triage(repo)
    st.triage(repo)
    assert [r["sha"] for r in st.list_stashes(repo)] == before


def test_triage_leaves_working_tree_clean(repo):
    _write(repo, "a.txt", "changed\n")
    _run(repo, "stash", "push", "-q")
    st.triage(repo)
    assert _run(repo, "status", "--porcelain").stdout.strip() == ""
