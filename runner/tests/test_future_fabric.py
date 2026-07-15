import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import candidate_rank,hermetic_cas,merge_certificate,sequential_allocator,symbol_context,transformation_market,workflow_comparison

def git(repo,*args):return subprocess.run(["git",*args],cwd=repo,check=True,capture_output=True,text=True).stdout.strip()
def repo(tmp_path):
    r=tmp_path/"repo";r.mkdir();git(r,"init");git(r,"config","user.email","x@y.z");git(r,"config","user.name","x");(r/"a.py").write_text("def old():\n    return 1\n");git(r,"add",".");git(r,"commit","-m","base");return r

def test_symbol_merkle_is_stable_and_selective():
    files={"a.py":"def alpha():\n return 1\n\ndef beta():\n return 2\n","b.ts":"export function gamma(){ return 3 }"}
    one=symbol_context.select("change beta in a.py",files,budget=1000);two=symbol_context.select("change beta in a.py",files,budget=1000)
    assert one["root"]==two["root"] and any("beta" in k for k in one["chunks"])
    assert one["chars"]<sum(map(len,files.values()))

def test_hermetic_cas_exact_key(tmp_path,monkeypatch):
    r=repo(tmp_path);monkeypatch.setenv("ORCH_VERIFICATION_CAS",str(tmp_path/"cas"));commit=git(r,"rev-parse","HEAD")
    assert hermetic_cas.lookup(str(r),commit,"true") is None
    hermetic_cas.store(str(r),commit,"true",True)
    assert hermetic_cas.lookup(str(r),commit,"true")["cache_hit"]
    assert hermetic_cas.lookup(str(r),commit,"false") is None

def test_certificates_only_compose_when_disjoint(tmp_path):
    r=repo(tmp_path);base={"commit":git(r,"rev-parse","HEAD"),"artifact_id":"a","test_cmd":"true"}
    a=merge_certificate.issue(str(r),base,{"a.py"});b=merge_certificate.issue(str(r),base,{"b.py"})
    assert merge_certificate.verify(a) and merge_certificate.composable([a,b])
    assert not merge_certificate.composable([a,a])

def test_transformation_market_round_trip(tmp_path,monkeypatch):
    monkeypatch.setenv("CLAUDE_ORCH_HOME",str(tmp_path));task={"prompt":"add health endpoint handler","slug":"health","project_id":"p"}
    diff="--- a/api.py\n+++ b/api.py\n@@ -0,0 +1,2 @@\n+def health():\n+ return 'ok'\n"
    transformation_market.record(task,diff,{"commit":"c","artifact_id":"a"})
    assert transformation_market.find({"prompt":"health endpoint handler"})

def test_static_candidate_rank_prefers_applicable_patch(tmp_path):
    r=repo(tmp_path);good={"text":"--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n def old():\n-    return 1\n+    return 2\n"};bad={"text":"not a patch"}
    assert candidate_rank.rank(str(r),[bad,good])[0]["candidate_rank"]["applies"]

def test_sequential_allocator_stops_proven_loser(monkeypatch):
    rows=[{"variant":"winner","value":10} for _ in range(30)]+[{"variant":"loser","value":0} for _ in range(30)]
    monkeypatch.setattr(sequential_allocator.db,"select",lambda *a,**k:rows);monkeypatch.setattr(sequential_allocator.db,"insert",lambda *a,**k:None)
    assert sequential_allocator.allocate()["allocation_pct"]["loser"]==0

def test_workflow_comparison_discloses_missing_cowork_quality():
    outcomes=[{"task_id":"n","account":"parallel-swarm","tests_passed":True,"integrated":False}]
    tasks=[{"id":"c","account":"cowork-1","state":"DONE"}]
    report=workflow_comparison.summarize(outcomes,tasks,2)
    assert report["cowork"]["task_completions_per_hour"]==.5
    assert report["coverage"]["comparable_quality"] is False
