"""Half-resolved merges: the artifact class both marker scans call clean.

`scan()` and `scan_worktree()` grep for the OPENING `<<<<<<<` marker. A conflict that
was abandoned mid-hunk still has one, so they catch it. A conflict that was *partly*
resolved does not: the usual human move is to delete the `<<<<<<< HEAD` line plus the
unwanted side and then miss the `>>>>>>> branch` line at the bottom. HEAD keeps a live
merge artifact and every opening-marker grep reports the tree clean.

The `.orig`/`.rej` half of this is the same failure with a different shape: git writes
those files during a partial merge or `git apply`, they are untracked, and an agent
running `git add -A` — which is how the executor commits — ships them.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import conflict_marker_sentinel as cms  # noqa: E402


def _git(a, r):
    return subprocess.run(["git", *a], cwd=r, capture_output=True, text=True)


def _repo(tmp_path, files):
    repo = str(tmp_path / "r")
    os.makedirs(repo)
    _git(["init", "-q", "-b", "master"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    for name, content in files.items():
        path = os.path.join(repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(name) else None
        with open(path, "w") as fh:
            fh.write(content)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "c"], repo)
    return repo


WHOLE_CONFLICT = "a=1\n<<<<<<< HEAD\nb=2\n=======\nb=3\n>>>>>>> x\n"
# Opening marker deleted, closing marker missed — the actual half-resolution.
ORPHAN_TAIL = "a=1\nb=2\n>>>>>>> feature/x\n"
ORPHAN_SEP = "a=1\nb=2\n=======\nb=3\n"
CLEAN = "a=1\nb=2\n"


# --- scan_orphan_markers ---------------------------------------------------

def test_orphan_closing_marker_is_found(tmp_path):
    assert cms.scan_orphan_markers(_repo(tmp_path, {"m.py": ORPHAN_TAIL})) == ["m.py"]


def test_orphan_separator_is_found(tmp_path):
    assert cms.scan_orphan_markers(_repo(tmp_path, {"m.py": ORPHAN_SEP})) == ["m.py"]


def test_opening_marker_grep_misses_what_orphan_scan_catches(tmp_path):
    """The regression this whole module exists for."""
    repo = _repo(tmp_path, {"m.py": ORPHAN_TAIL})
    assert cms.scan(repo) == []
    assert cms.scan_worktree(repo) == []
    assert cms.scan_orphan_markers(repo) == ["m.py"]


def test_clean_file_has_no_orphans(tmp_path):
    assert cms.scan_orphan_markers(_repo(tmp_path, {"m.py": CLEAN})) == []


def test_whole_conflict_is_not_double_reported_as_an_orphan(tmp_path):
    repo = _repo(tmp_path, {"m.py": WHOLE_CONFLICT})
    assert cms.scan_worktree(repo) == ["m.py"]
    assert cms.scan_orphan_markers(repo) == []


def test_a_separator_of_the_wrong_length_is_not_a_marker(tmp_path):
    # Markdown setext underlines and table rules are `===` runs, not exactly seven.
    repo = _repo(tmp_path, {"m.md": "Title\n=====\n\n=========\n"})
    assert cms.scan_orphan_markers(repo) == []


def test_trailing_text_after_separator_is_not_a_marker(tmp_path):
    repo = _repo(tmp_path, {"m.py": "x = '======= not a marker'\n"})
    assert cms.scan_orphan_markers(repo) == []


def test_multiple_orphan_files_are_sorted(tmp_path):
    repo = _repo(tmp_path, {"b.py": ORPHAN_TAIL, "a.py": ORPHAN_SEP})
    assert cms.scan_orphan_markers(repo) == ["a.py", "b.py"]


# --- scan_leftover_files ---------------------------------------------------

def test_tracked_orig_file_is_debris(tmp_path):
    repo = _repo(tmp_path, {"m.py": CLEAN, "m.py.orig": CLEAN})
    assert cms.scan_leftover_files(repo) == ["m.py.orig"]


def test_tracked_rej_file_is_debris(tmp_path):
    repo = _repo(tmp_path, {"m.py": CLEAN, "m.py.rej": "@@ -1 +1 @@\n"})
    assert cms.scan_leftover_files(repo) == ["m.py.rej"]


def test_untracked_orig_file_is_local_mess_not_debris(tmp_path):
    repo = _repo(tmp_path, {"m.py": CLEAN})
    with open(os.path.join(repo, "m.py.orig"), "w") as fh:
        fh.write(CLEAN)
    assert cms.scan_leftover_files(repo) == []


def test_clean_repo_has_no_debris(tmp_path):
    assert cms.scan_leftover_files(_repo(tmp_path, {"m.py": CLEAN})) == []


def test_original_suffix_is_not_orig(tmp_path):
    repo = _repo(tmp_path, {"notes.original": "x\n"})
    assert cms.scan_leftover_files(repo) == []


# --- scan_artifacts --------------------------------------------------------

def test_scan_artifacts_unions_and_dedupes(tmp_path):
    repo = _repo(tmp_path, {"m.py": ORPHAN_TAIL, "m.py.rej": "@@\n"})
    assert cms.scan_artifacts(repo) == ["m.py", "m.py.rej"]


def test_scan_artifacts_clean(tmp_path):
    assert cms.scan_artifacts(_repo(tmp_path, {"m.py": CLEAN})) == []


# --- sweep integration -----------------------------------------------------

def test_sweep_reports_and_files_artifacts(tmp_path):
    filed = []
    res = cms.sweep(
        _repo(tmp_path, {"m.py": ORPHAN_TAIL}), enqueue_fn=lambda rec: filed.append(rec)
    )
    assert res["found"] == [] and res["worktree"] == []
    assert res["artifacts"] == ["m.py"] and res["filed"] is True
    assert filed[0]["slug"] == "remediation-merge-artifacts"
    assert filed[0]["kind"] == "remediation" and filed[0]["priority"] == 1
    assert "m.py" in filed[0]["prompt"]


def test_sweep_lists_stay_disjoint(tmp_path):
    repo = _repo(tmp_path, {"m.py": WHOLE_CONFLICT, "o.py": ORPHAN_TAIL})
    res = cms.sweep(repo)
    assert set(res["found"]) & set(res["worktree"]) == set()
    assert set(res["artifacts"]) & (set(res["found"]) | set(res["worktree"])) == set()
    assert res["artifacts"] == ["o.py"]


def test_sweep_clean_repo_reports_empty_artifacts(tmp_path):
    res = cms.sweep(_repo(tmp_path, {"m.py": CLEAN}))
    assert res == {"found": [], "worktree": [], "artifacts": [], "filed": False}


def test_sweep_without_enqueue_still_reports(tmp_path):
    res = cms.sweep(_repo(tmp_path, {"m.py": ORPHAN_TAIL}))
    assert res["artifacts"] == ["m.py"] and res["filed"] is False


def test_sweep_survives_a_raising_enqueue(tmp_path):
    def boom(_rec):
        raise RuntimeError("db down")

    res = cms.sweep(_repo(tmp_path, {"m.py": ORPHAN_TAIL}), enqueue_fn=boom)
    assert res["artifacts"] == ["m.py"] and res["filed"] is False
