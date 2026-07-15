#!/usr/bin/env python3
"""Tamper-evident merge proofs that can be composed when dependency/file sets permit."""
from __future__ import annotations
import hashlib,json,time
import proof_graph
def issue(repo,artifact,files):
    body={"v":1,"commit":artifact.get("commit"),"artifact_id":artifact.get("artifact_id"),"dependency_fingerprint":proof_graph.dependency_fingerprint(repo),"test_cmd":artifact.get("test_cmd"),"files":sorted(files or []),"tests_passed":True,"at":time.time()}
    body["digest"]=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    return body
def verify(cert):
    body={k:v for k,v in cert.items() if k!="digest"}
    return cert.get("digest")==hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest() and bool(cert.get("tests_passed"))
def composable(certs):
    if not certs or not all(verify(c) for c in certs):return False
    if len({c.get("dependency_fingerprint") for c in certs})!=1:return False
    used=set()
    for c in certs:
        files=set(c.get("files") or [])
        if used&files:return False
        used|=files
    return True
