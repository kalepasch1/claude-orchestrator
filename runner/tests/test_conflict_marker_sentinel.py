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
    assert res == {"found": [], "filed": False} and filed == []
