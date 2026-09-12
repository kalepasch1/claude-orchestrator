#!/usr/bin/env python3
"""The dedup detector must see no-op branches, and its fingerprint must be stable.

TWO DEFECTS
-----------
1. `find_semantic_duplicates` skipped branches whose diff against base was empty:

       stat = _diff_stat(...)
       if stat:            # "" is falsey
           stat_map[stat].append(b)

   A branch with no diff — created and never committed to, or already fully merged —
   returned "" and was dropped. Those are the most duplicated objects in the repo.
   Measured on this checkout: 20 agent branches collapse onto 2 commits, and the
   semantic pass reported ZERO groups. After the fix it reports one group of 64.
   The detector was blind to its single largest category.

2. `hash(stat) & 0xFFFFFFFF` as the reported fingerprint. Python randomizes str
   hashing per process, so the same branches produced a different fingerprint every
   run — impossible to compare two reports, correlate, or store. A fingerprint that
   changes every run is worse than none, because it looks like one.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_dedup as bd  # noqa: E402


def _git(repo, *args):
    subprocess.run(("git", "-C", str(repo)) + args, check=True,
                   capture_output=True, text=True, timeout=30)


@pytest.fixture()
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "master")
    _git(path, "config", "user.email", "kalepasch@gmail.com")
    _git(path, "config", "user.name", "kalepasch1")
    (path / "a.py").write_text("original\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "base")
    return path


def branch(repo, name, content=None):
    """Create agent/<name>. With no content the branch is a no-op against master."""
    _git(repo, "checkout", "-q", "-b", f"agent/{name}", "master")
    if content is not None:
        (repo / "a.py").write_text(content)
        _git(repo, "commit", "-qam", f"edit on {name}")
    _git(repo, "checkout", "-q", "master")


# ── the regression: no-op branches are found ────────────────────────────────

def test_branches_with_no_diff_are_detected(repo):
    for name in ("one", "two", "three"):
        branch(repo, name)
    groups = bd.find_semantic_duplicates(str(repo), "master")
    assert len(groups) == 1
    assert groups[0]["count"] == 3


def test_a_no_op_group_is_flagged_as_empty_diff(repo):
    """'nothing to merge' and 'duplicate work to consolidate' want opposite handling."""
    for name in ("one", "two"):
        branch(repo, name)
    assert bd.find_semantic_duplicates(str(repo), "master")[0]["empty_diff"] is True


def test_a_real_duplicate_group_is_not_flagged_empty(repo):
    branch(repo, "one", "changed\n")
    branch(repo, "two", "changed\n")
    groups = [g for g in bd.find_semantic_duplicates(str(repo), "master")
              if not g["empty_diff"]]
    assert len(groups) == 1
    assert groups[0]["count"] == 2


def test_no_op_and_real_duplicates_are_separate_groups(repo):
    branch(repo, "empty1")
    branch(repo, "empty2")
    branch(repo, "real1", "changed\n")
    branch(repo, "real2", "changed\n")
    groups = bd.find_semantic_duplicates(str(repo), "master")
    assert len(groups) == 2
    assert sorted(g["empty_diff"] for g in groups) == [False, True]


def test_a_lone_branch_is_not_a_duplicate(repo):
    branch(repo, "only")
    assert bd.find_semantic_duplicates(str(repo), "master") == []


def test_branches_touching_different_files_are_not_grouped(repo):
    _git(repo, "checkout", "-q", "-b", "agent/one", "master")
    (repo / "a.py").write_text("changed\n")
    _git(repo, "commit", "-qam", "edit a")
    _git(repo, "checkout", "-q", "-b", "agent/two", "master")
    (repo / "b.py").write_text("new file\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add b")
    _git(repo, "checkout", "-q", "master")
    assert [g for g in bd.find_semantic_duplicates(str(repo), "master")
            if not g["empty_diff"]] == []


def test_same_shape_edits_to_one_file_are_grouped_a_known_limitation(repo):
    """Documented, not asserted-away: grouping is by diffSTAT, not by content.

    `git diff --stat` reports files and line counts, so two branches that each change
    one line of a.py look identical here even when the content differs. That is a
    real false-positive risk in this detector's design and is worth knowing before
    anyone wires it to automatic deletion — hence a test that states it plainly rather
    than a test that quietly avoids the case.
    """
    branch(repo, "one", "alpha\n")
    branch(repo, "two", "beta\n")
    groups = [g for g in bd.find_semantic_duplicates(str(repo), "master")
              if not g["empty_diff"]]
    assert len(groups) == 1 and groups[0]["count"] == 2


# ── the fingerprint is stable ───────────────────────────────────────────────

def test_the_fingerprint_is_deterministic_within_a_process():
    assert bd._diff_fingerprint(" a.py | 2 +-") == bd._diff_fingerprint(" a.py | 2 +-")


def test_the_fingerprint_is_stable_across_processes():
    """The actual defect: hash() is randomized per interpreter."""
    code = ("import sys; sys.path.insert(0, %r); import branch_dedup as bd; "
            "print(bd._diff_fingerprint(' a.py | 2 +-'))"
            % os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    seen = set()
    for seed in ("0", "1", "12345"):
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, timeout=60,
                              env={**os.environ, "PYTHONHASHSEED": seed})
        seen.add(proc.stdout.strip())
    assert len(seen) == 1, f"fingerprint varies by PYTHONHASHSEED: {seen}"


def test_different_diffs_get_different_fingerprints():
    assert bd._diff_fingerprint(" a.py | 1 +") != bd._diff_fingerprint(" b.py | 1 +")


def test_the_fingerprint_is_a_hex_string_not_an_int():
    fp = bd._diff_fingerprint("anything")
    assert isinstance(fp, str) and len(fp) == 16
    int(fp, 16)


def test_the_fingerprint_is_fail_soft_on_empty_and_none():
    assert bd._diff_fingerprint("") == bd._diff_fingerprint(None)


# ── unreadable diffs are still skipped ──────────────────────────────────────

def test_an_unreadable_diff_is_skipped_not_grouped(repo, monkeypatch):
    """None means 'could not read'; it must not be grouped with real empty diffs."""
    for name in ("one", "two"):
        branch(repo, name)
    monkeypatch.setattr(bd, "_diff_stat", lambda *a, **k: None)
    assert bd.find_semantic_duplicates(str(repo), "master") == []


# ── report and kill switch ──────────────────────────────────────────────────

def test_the_report_counts_the_no_op_branches(repo):
    for name in ("one", "two", "three"):
        branch(repo, name)
    report = bd.dedup_report(str(repo), "master")
    assert report["semantic_duplicate_groups"] == 1
    assert report["semantic_duplicate_branches"] == 3


def test_the_kill_switch_disables_detection(repo, monkeypatch):
    for name in ("one", "two"):
        branch(repo, name)
    monkeypatch.setattr(bd, "ENABLED", False)
    assert bd.find_semantic_duplicates(str(repo), "master") == []


def test_a_missing_repo_is_fail_soft():
    assert bd.find_semantic_duplicates("/nonexistent/repo/xyz", "master") == []


def test_exact_duplicate_detection_is_unchanged(repo):
    """The other pass must keep working: same commit, different names."""
    branch(repo, "one")
    branch(repo, "two")
    groups = bd.find_exact_duplicates(str(repo))
    assert groups and groups[0]["count"] >= 2
