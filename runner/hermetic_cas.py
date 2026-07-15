#!/usr/bin/env python3
"""Content-addressed verification cache with optional shared filesystem backing."""
from __future__ import annotations
import hashlib, json, os, platform, threading, time
import proof_graph

_lock=threading.Lock()
def root():
    return os.environ.get("ORCH_VERIFICATION_CAS", os.path.join(os.environ.get("CLAUDE_ORCH_HOME", os.path.join(os.path.dirname(__file__),"..",".runtime")),"verification-cas"))
def key(repo, commit, test_cmd):
    payload="\0".join([str(commit),proof_graph.dependency_fingerprint(repo),str(test_cmd),platform.system(),platform.machine()])
    return hashlib.sha256(payload.encode()).hexdigest()
def lookup(repo, commit, test_cmd):
    digest=key(repo,commit,test_cmd); path=os.path.join(root(),digest[:2],digest+".json")
    try:
        with open(path) as f: row=json.load(f)
        if row.get("success") and row.get("key")==digest:
            return {**row,"cache_hit":True,"path":path}
    except Exception: pass
    return None
def store(repo, commit, test_cmd, success, **detail):
    digest=key(repo,commit,test_cmd); path=os.path.join(root(),digest[:2],digest+".json")
    row={"key":digest,"commit":commit,"test_cmd":test_cmd,"success":bool(success),"dependency_fingerprint":proof_graph.dependency_fingerprint(repo),"at":time.time(),**detail}
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with _lock:
        tmp=path+f".{os.getpid()}.tmp"
        with open(tmp,"w") as f:json.dump(row,f,separators=(",",":"),default=str)
        os.replace(tmp,path)
    return {**row,"path":path}
def stats():
    n=0;size=0
    for base,_dirs,files in os.walk(root()):
        for name in files:
            if name.endswith(".json"):
                n+=1
                try:size+=os.path.getsize(os.path.join(base,name))
                except OSError:pass
    return {"proofs":n,"bytes":size}
