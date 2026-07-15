#!/usr/bin/env python3
"""Typed, hash-guarded rewrite IR with language-specific validation adapters."""
from __future__ import annotations
import ast,hashlib,json,os,re,subprocess

SCHEMA="orchestrator.ast-rewrite/v1"
def file_hash(text):return hashlib.sha256(text.encode()).hexdigest()
def validate(ir):
    if ir.get("schema")!=SCHEMA:raise ValueError("unsupported rewrite schema")
    for op in ir.get("operations",[]):
        if op.get("kind") not in ("rename_symbol","replace_literal"):raise ValueError("unsupported operation")
        if not op.get("path") or not op.get("before_hash"):raise ValueError("unguarded operation")
    return True
def apply(repo,ir):
    validate(ir); changed={}
    for op in ir.get("operations",[]):
        path=os.path.join(repo,op["path"])
        with open(path,errors="replace") as f:text=f.read()
        if file_hash(text)!=op["before_hash"]:raise ValueError("precondition hash mismatch: "+op["path"])
        if op["kind"]=="rename_symbol":
            old,new=op["old"],op["new"]
            text,n=re.subn(r"(?<![\w$])"+re.escape(old)+r"(?![\w$])",new,text)
        else:
            text,n=text.replace(op["old"],op["new"]),text.count(op["old"])
        if not n:raise ValueError("rewrite matched nothing: "+op["path"])
        ext=os.path.splitext(path)[1]
        if ext==".py":ast.parse(text)
        elif ext in (".js",".jsx",".ts",".tsx",".vue") and text.count("{")!=text.count("}"):
            raise ValueError("unbalanced JS/TS adapter output")
        changed[op["path"]]=text
    return changed
def summarize(ir):
    validate(ir)
    return [f"{x['kind']}:{x['path']}:{x.get('old')}->{x.get('new')}" for x in ir.get("operations",[])]
def derive(repo,commit,diff):
    """Lift conservative one-symbol patches into reusable typed operations."""
    by_file={}; current=None
    for line in (diff or "").splitlines():
        if line.startswith("+++ b/"):current=line[6:];by_file.setdefault(current,{"minus":[],"plus":[]})
        elif current and line.startswith("-") and not line.startswith("---"):by_file[current]["minus"].append(line[1:])
        elif current and line.startswith("+") and not line.startswith("+++"):by_file[current]["plus"].append(line[1:])
    ops=[]
    for path,lines in by_file.items():
        old=subprocess.run(["git","show",f"{commit}^:{path}"],cwd=repo,capture_output=True,text=True,timeout=10)
        if old.returncode:continue
        for before,after in zip(lines["minus"],lines["plus"]):
            a=re.findall(r"[A-Za-z_$][\w$]*",before);b=re.findall(r"[A-Za-z_$][\w$]*",after)
            delta=[(x,y) for x,y in zip(a,b) if x!=y]
            if len(a)==len(b) and len(delta)==1 and before.replace(delta[0][0],delta[0][1])==after:
                ops.append({"kind":"rename_symbol","path":path,"old":delta[0][0],"new":delta[0][1],
                            "before_hash":file_hash(old.stdout),"language":os.path.splitext(path)[1].lstrip(".")})
    ir={"schema":SCHEMA,"operations":ops}
    return ir if ops else None
