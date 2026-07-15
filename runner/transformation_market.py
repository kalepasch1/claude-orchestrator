#!/usr/bin/env python3
"""Cross-project market of verified transformation shapes."""
from __future__ import annotations
import hashlib,json,os,re,threading,time
import merged_diff_library
_lock=threading.Lock()
def _path(): return os.path.join(os.environ.get("CLAUDE_ORCH_HOME",os.path.join(os.path.dirname(__file__),"..",".runtime")),"transformation-market.jsonl")
def record(task,diff,artifact):
    files=re.findall(r"(?m)^\+\+\+ b/(.+)$",diff or ""); feat=merged_diff_library.features(task.get("prompt") or "",diff,files)
    typed_ir=None
    try:
        import ast_rewrite_ir
        typed_ir=ast_rewrite_ir.derive(artifact.get("repository") or "",artifact.get("commit") or "",diff)
    except Exception:pass
    row={"id":hashlib.sha256(((artifact.get("commit") or "")+diff).encode()).hexdigest(),"at":time.time(),"project_id":task.get("project_id"),"slug":task.get("slug"),"artifact_id":artifact.get("artifact_id"),"commit":artifact.get("commit"),"files":files,"features":feat,"typed_ir":typed_ir,"diff":diff[:60000],"verified":True}
    os.makedirs(os.path.dirname(_path()),exist_ok=True)
    with _lock,open(_path(),"a") as f:f.write(json.dumps(row,separators=(",",":"),default=str)+"\n")
    if typed_ir:
        try:
            import activation_proof
            activation_proof.record("typed_ast_rewrite_ir","effect",True,task_id=task.get("id"),artifact_id=row["id"],operations=len(typed_ir.get("operations",[])))
        except Exception:pass
    return row
def find(task,limit=3):
    query=merged_diff_library.features(task.get("prompt") or "")
    q=set(query["words"])
    try:
        with open(_path()) as f: rows=[json.loads(x) for x in f if x.strip()][-5000:]
    except Exception:return []
    scored=[]
    for r in rows:
        words=set((r.get("features") or {}).get("words") or [])
        score=len(q&words)/max(1,len(q|words))
        if score: scored.append((score,r))
    return [{"score":round(s,4),**r} for s,r in sorted(scored,key=lambda x:-x[0])[:limit]]
def prompt_hint(task,max_chars=1800):
    hits=[h for h in find(task,limit=8) if h.get("typed_ir")]
    if not hits:return ""
    lines=["VERIFIED TYPED AST REWRITE IR (apply only with matching hash/symbol preconditions):"]
    for h in hits:
        try:
            import ast_rewrite_ir
            lines.extend(f"- score={h['score']} {x}" for x in ast_rewrite_ir.summarize(h["typed_ir"]))
        except Exception:continue
    return "\n".join(lines)[:max_chars]
def stats():
    try:
        with open(_path()) as f:rows=[json.loads(x) for x in f if x.strip()]
    except Exception:rows=[]
    return {"verified_transformations":len(rows),"projects":len({r.get("project_id") for r in rows})}
