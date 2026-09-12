import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import conflict_marker_sentinel as cms

def _git(a, r): return subprocess.run(["git", *a], cwd=r, capture_output=True, text=True)
def _repo(tmp_path, content):
    repo = str(tmp_path / "r"); os.makedirs(repo)
    _git(["init","-q","-b","master"],repo); _git(["config","user.email","t@t"],repo); _git(["config","user.name","t"],repo)
    open(os.path.join(repo,"m.py"),"w").write(content); _git(["add","."],repo); _git(["commit","-qm","c"],repo)
    return repo

CONFLICT = "a=1\n<<<<<<< HEAD\nb=2\n=======\nb=3\n>>>>>>> x\n"

def test_detects_conflict_markers(tmp_path):
    assert cms.scan(_repo(tmp_path, CONFLICT)) == ["m.py"]

def test_clean_file_no_findings(tmp_path):
    assert cms.scan(_repo(tmp_path, "a=1\nb=2\n")) == []

def test_sweep_files_tier1_remediation(tmp_path):
    filed = []
    res = cms.sweep(_repo(tmp_path, CONFLICT), enqueue_fn=lambda rec: filed.append(rec))
    assert res["found"] == ["m.py"] and res["filed"] is True
    assert filed[0]["kind"] == "remediation" and filed[0]["priority"] == 1

def test_sweep_clean_files_nothing(tmp_path):
    filed = []
    res = cms.sweep(_repo(tmp_path, "ok=1\n"), enqueue_fn=lambda rec: filed.append(rec))
    assert res == {"found": [], "worktree": [], "artifacts": [], "filed": False}
    assert filed == []


# --- uncommitted markers: invisible to a HEAD grep, yet they block EVERY merge ---------
# The pre-merge-commit anti-regression guard scans the WORKING TREE. On 2026-08-18 three
# uncommitted darwin-kernel files carried markers while HEAD was clean, so git refused
# every merge commit on the node and the HEAD-only sentinel reported nothing at all.

def _dirty(repo, content):
    """Overwrite the tracked file WITHOUT committing."""
    open(os.path.join(repo, "m.py"), "w").write(content)


def test_scan_worktree_sees_markers_that_head_scan_cannot(tmp_path):
    repo = _repo(tmp_path, "a=1\nb=2\n")
    _dirty(repo, CONFLICT)
    assert cms.scan(repo) == [], "HEAD is clean — this is exactly why the old scan missed it"
    assert cms.scan_worktree(repo) == ["m.py"]


def test_sweep_files_a_distinct_remediation_for_uncommitted_markers(tmp_path):
    repo = _repo(tmp_path, "a=1\nb=2\n")
    _dirty(repo, CONFLICT)
    filed = []
    res = cms.sweep(repo, enqueue_fn=lambda rec: filed.append(rec))
    assert res["found"] == []
    assert res["worktree"] == ["m.py"]
    assert res["filed"] is True
    assert len(filed) == 1
    assert filed[0]["slug"] == "remediation-conflict-markers-in-worktree"
    assert filed[0]["priority"] == 1, "must stay tier-1: never ahead of user-directed work"
    assert "merge commit" in filed[0]["prompt"]


def test_committed_markers_are_not_reported_twice(tmp_path):
    repo = _repo(tmp_path, CONFLICT)
    filed = []
    res = cms.sweep(repo, enqueue_fn=lambda rec: filed.append(rec))
    assert res["found"] == ["m.py"]
    assert res["worktree"] == [], "already covered by the HEAD finding"
    assert len(filed) == 1


def test_both_locations_file_one_task_each(tmp_path):
    repo = _repo(tmp_path, CONFLICT)                      # m.py: markers on HEAD
    open(os.path.join(repo, "other.py"), "w").write("ok=1\n")
    _git(["add", "."], repo); _git(["commit", "-qm", "clean other"], repo)
    open(os.path.join(repo, "other.py"), "w").write(CONFLICT)   # uncommitted markers
    filed = []
    res = cms.sweep(repo, enqueue_fn=lambda rec: filed.append(rec))
    assert res["found"] == ["m.py"]
    assert res["worktree"] == ["other.py"]
    assert sorted(r["slug"] for r in filed) == [
        "remediation-conflict-markers-in-worktree",
        "remediation-conflict-markers-on-master",
    ]


def test_enqueue_failure_is_swallowed(tmp_path):
    repo = _repo(tmp_path, "a=1\n")
    _dirty(repo, CONFLICT)
    def boom(rec): raise RuntimeError("db down")
    res = cms.sweep(repo, enqueue_fn=boom)
    assert res["worktree"] == ["m.py"] and res["filed"] is False
