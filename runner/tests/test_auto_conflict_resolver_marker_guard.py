import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auto_conflict_resolver as acr

def _run(args, cwd): return subprocess.run(args, cwd=cwd, capture_output=True, text=True)

def _make_conflict_repo(tmp_path):
    repo = str(tmp_path / "r"); os.makedirs(repo)
    _run(["git","init","-q","-b","master"], repo)
    _run(["git","config","user.email","t@t"], repo); _run(["git","config","user.name","t"], repo)
    f = os.path.join(repo,"conflict.txt")
    open(f,"w").write("l1\nBASE\nl3\n"); _run(["git","add","."],repo); _run(["git","commit","-qm","base"],repo)
    open(f,"w").write("l1\nMASTER\nl3\n"); _run(["git","commit","-qam","m"],repo)
    _run(["git","checkout","-qb","feature","HEAD~1"],repo)
    open(f,"w").write("l1\nFEATURE\nl3\n"); _run(["git","commit","-qam","f"],repo)
    _run(["git","checkout","-q","master"],repo)
    return repo

def test_conflict_markers_never_committed(tmp_path, monkeypatch):
    repo=_make_conflict_repo(tmp_path)
    monkeypatch.setattr(acr,"_classify_conflict",lambda f,t:"theirs")
    monkeypatch.setattr(acr,"_verify_merge",lambda *a,**k:"")
    def buggy(repo,filepath,strategy,branch,base):
        _run(["git","add",filepath],repo); return True   # reports success, leaves markers
    monkeypatch.setattr(acr,"_resolve_file",buggy)
    r=acr.resolve_branch(repo,"feature","master")
    assert r["merged"] is False, r
    assert r["strategy"]=="manual", r
    head=_run(["git","show","HEAD:conflict.txt"],repo).stdout
    assert "<<<<<<<" not in head and ">>>>>>>" not in head
    assert _run(["git","rev-parse","--verify","feature"],repo).returncode==0   # branch preserved

def test_clean_resolution_still_commits(tmp_path, monkeypatch):
    repo=_make_conflict_repo(tmp_path)
    monkeypatch.setattr(acr,"_classify_conflict",lambda f,t:"theirs")
    monkeypatch.setattr(acr,"_verify_merge",lambda *a,**k:"")
    def good(repo,filepath,strategy,branch,base):
        open(os.path.join(repo,filepath),"w").write("l1\nRESOLVED\nl3\n")
        _run(["git","add",filepath],repo); return True
    monkeypatch.setattr(acr,"_resolve_file",good)
    r=acr.resolve_branch(repo,"feature","master")
    assert r["merged"] is True, r
    head=_run(["git","show","HEAD:conflict.txt"],repo).stdout
    assert "RESOLVED" in head and "<<<<<<<" not in head
