#!/usr/bin/env python3
"""Merkle-addressed symbol slices for delta-only model context."""
from __future__ import annotations
import ast, hashlib, json, os, re, subprocess, threading, time

WORD=re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
JS=re.compile(r"(?m)^(?:export\s+)?(?:async\s+)?(?:function|class|interface|type|const|let)\s+([A-Za-z_$][\w$]*)")
_cache={};_manifest_cache={};_lock=threading.Lock();_MAX_CACHE=8
def _chunks(path,text):
    spans=[]
    if path.endswith(".py"):
        try:
            tree=ast.parse(text)
            for n in tree.body:
                if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                    lines=text.splitlines(); spans.append((n.name,"\n".join(lines[n.lineno-1:getattr(n,"end_lineno",n.lineno)])))
        except Exception: pass
    else:
        hits=list(JS.finditer(text))
        for i,m in enumerate(hits): spans.append((m.group(1),text[m.start():hits[i+1].start() if i+1<len(hits) else len(text)]))
    if not spans: spans=[("module",text)]
    return [{"path":path,"symbol":name,"text":body,"hash":hashlib.sha256(body.encode()).hexdigest()} for name,body in spans]
def merkle(files):
    version=hashlib.sha256("".join(f"{p}\0{len(t)}\0{hashlib.sha256(t.encode()).hexdigest()}" for p,t in sorted(files.items())).encode()).hexdigest()
    with _lock:
        hit=_cache.get(version)
        if hit:return hit
    chunks=[c for p,t in files.items() for c in _chunks(p,t)]
    root=hashlib.sha256("".join(sorted(c["hash"] for c in chunks)).encode()).hexdigest()
    with _lock:
        _cache[version]=(root,chunks)
        while len(_cache)>_MAX_CACHE:_cache.pop(next(iter(_cache)))
    return root,chunks
def _manifest_path(repo,commit):
    repo_id=hashlib.sha256(os.path.realpath(repo).encode()).hexdigest()[:16]
    root=os.environ.get("CLAUDE_ORCH_HOME",os.path.join(os.path.dirname(os.path.dirname(__file__)),".runtime"))
    return os.path.join(root,"symbol-manifests",repo_id,commit+".json")
def _head(repo):
    try:
        git=os.path.join(repo,".git")
        if os.path.isfile(git):
            with open(git) as f:git=os.path.join(repo,f.read().split(":",1)[1].strip())
        with open(os.path.join(git,"HEAD")) as f:head=f.read().strip()
        if head.startswith("ref:"):
            with open(os.path.join(git,head.split(":",1)[1].strip())) as f:return f.read().strip()
        return head
    except Exception:
        return subprocess.run(["git","rev-parse","HEAD"],cwd=repo,capture_output=True,text=True,timeout=10).stdout.strip()
def precompute(repo,files=None,commit=None):
    """Persist the immutable symbol Merkle manifest for a landed Git commit."""
    commit=commit or _head(repo)
    if not commit:return {}
    path=_manifest_path(repo,commit)
    if os.path.isfile(path):
        try:
            with open(path) as f:manifest=json.load(f)
            with _lock:_manifest_cache[path]=manifest
            return manifest
        except Exception:pass
    if files is None:
        files={}
        listed=subprocess.run(["git","ls-files"],cwd=repo,capture_output=True,text=True,timeout=20)
        for rel in listed.stdout.splitlines():
            if os.path.splitext(rel)[1].lower() not in {".py",".js",".jsx",".ts",".tsx",".vue",".go",".rs"}:continue
            p=os.path.join(repo,rel)
            try:
                if os.path.getsize(p)<=500000:
                    with open(p,errors="replace") as f:files[rel]=f.read()
            except OSError:pass
    root,chunks=merkle(files)
    manifest={"commit":commit,"root":root,"chunks":chunks,"created_at":time.time()}
    os.makedirs(os.path.dirname(path),exist_ok=True)
    tmp=path+".tmp"
    with open(tmp,"w") as f:json.dump(manifest,f,separators=(",",":"))
    os.replace(tmp,path)
    with _lock:_manifest_cache[path]=manifest
    return manifest
def load(repo,commit=None):
    commit=commit or _head(repo)
    path=_manifest_path(repo,commit)
    with _lock:
        if path in _manifest_cache:return _manifest_cache[path]
    try:
        with open(path) as f:manifest=json.load(f)
        with _lock:_manifest_cache[path]=manifest
        return manifest
    except Exception:return {}
def select(prompt,files,budget=12000,max_chunks=12,repo=None):
    manifest=load(repo) if repo else {}
    if not manifest and repo:manifest=precompute(repo,files)
    if manifest:root,chunks=manifest["root"],manifest["chunks"]
    else:root,chunks=merkle(files)
    terms={w.lower() for w in WORD.findall(prompt or "")}; ranked=[]
    for c in chunks:
        words={w.lower() for w in WORD.findall(c["path"]+" "+c["symbol"])}
        score=len(terms&words)*10 + (5 if c["path"].lower() in (prompt or "").lower() else 0)
        ranked.append((score,c))
    out={}; used=0
    for score,c in sorted(ranked,key=lambda x:(-x[0],len(x[1]["text"])))[:max_chunks]:
        if score<=0 and out: break
        text=c["text"][:max(0,budget-used)]
        if not text: break
        out[f"{c['path']}#{c['symbol']}@{c['hash'][:12]}"]=text; used+=len(text)
    return {"root":root,"chunks":out,"chars":used,"total_chunks":len(chunks)}
