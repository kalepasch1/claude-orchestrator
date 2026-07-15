#!/usr/bin/env python3
"""Zero-test static ranking for warmed speculative patch candidates."""
from __future__ import annotations
import subprocess
import patch_fabric
def score(repo,text):
    diff=patch_fabric.extract_diff(text); files=patch_fabric.affected_files(diff)
    if not diff or not files or "GIT binary patch" in diff or "../" in diff:return (-1e9,{"valid":False})
    try:
        check=subprocess.run(["git","apply","--check","--3way"],cwd=repo,input=diff,text=True,capture_output=True,timeout=30)
        applies=check.returncode==0
    except Exception: applies=False
    additions=sum(1 for x in diff.splitlines() if x.startswith("+") and not x.startswith("+++")); deletions=sum(1 for x in diff.splitlines() if x.startswith("-") and not x.startswith("---"))
    value=(1000 if applies else -1000)-len(files)*8-(additions+deletions)*.05
    return (value,{"valid":True,"applies":applies,"files":sorted(files),"churn":additions+deletions})
def rank(repo,results,limit=2):
    ranked=[]
    for r in results:
        s,meta=score(repo,r.get("text") or "");ranked.append((s,{**r,"candidate_rank":meta,"candidate_score":s}))
    return [r for _s,r in sorted(ranked,key=lambda x:-x[0])[:limit]]
