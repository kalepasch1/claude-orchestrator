#!/usr/bin/env python3
"""Cross-machine CAS verification worker; OCI when configured, isolated Git fallback."""
from __future__ import annotations
import hashlib,json,os,shlex,socket,subprocess,tempfile,time
import db,hermetic_cas
OWNER=f"{socket.gethostname()}:{os.getpid()}"
def run_once():
    rows=db.rpc("claim_verification_job",{"p_owner":OWNER,"p_ttl_seconds":900}) or []
    if not rows:return {"claimed":0}
    j=rows[0]; repo=db.localize_repo_path(j["repository"]); started=time.time()
    with tempfile.TemporaryDirectory(prefix="orch-verify-") as td:
        add=subprocess.run(["git","worktree","add","--detach",td,j["commit_sha"]],cwd=repo,capture_output=True,text=True)
        if add.returncode:return _finish(j,False,add.stderr,started)
        try:
            image=j.get("oci_image")
            if image and subprocess.run(["docker","version"],capture_output=True).returncode==0:
                cmd=["docker","run","--rm","-v",td+":/workspace","-w","/workspace",image,"sh","-lc",j["command"]]
                p=subprocess.run(cmd,capture_output=True,text=True,timeout=1800)
            else:p=subprocess.run(j["command"],cwd=td,shell=True,capture_output=True,text=True,timeout=1800)
            return _finish(j,p.returncode==0,(p.stdout or "")+"\n"+(p.stderr or ""),started)
        finally:subprocess.run(["git","worktree","remove","--force",td],cwd=repo,capture_output=True)
def _finish(j,ok,log,started):
    result={"passed":ok,"log":log[-12000:],"duration_ms":int((time.time()-started)*1000),"worker":OWNER}
    digest=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
    db.update("verification_jobs",{"id":j["id"]},{"state":"DONE" if ok else "FAILED","result_digest":digest,"result":result,"updated_at":"now()"})
    if ok:hermetic_cas.store(j["repository"],j["commit_sha"],j["command"],True,remote_worker=OWNER)
    try:
        import activation_proof
        activation_proof.record("remote_oci_cas_verification","outcome",ok,task_id=j.get("task_id"),
            artifact_id=digest,worker=OWNER,duration_ms=result["duration_ms"])
    except Exception:pass
    return {"claimed":1,"job_id":j["id"],**result}
if __name__=="__main__":print(json.dumps(run_once(),default=str))
