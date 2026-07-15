#!/usr/bin/env python3
"""REAPI-style action submission over the shared DB with CAS result reuse."""
from __future__ import annotations
import hashlib,os,time
import db,hermetic_cas
def action_digest(repo,commit,command,image=""):
    return hashlib.sha256((commit+"\0"+hermetic_cas.key(repo,commit,command)+"\0"+image).encode()).hexdigest()
def verify(repo,commit,command,task=None,project=None,image="",timeout=20):
    hit=hermetic_cas.lookup(repo,commit,command)
    if hit:return {"done":True,"passed":True,"cas_hit":True,"result":hit}
    digest=action_digest(repo,commit,command,image)
    row={"action_digest":digest,"repository":repo,"commit_sha":commit,"command":command,
         "oci_image":image or None,"task_id":task.get("id") if task else None,
         "project_id":project.get("id") if project else None}
    db.insert("verification_jobs",row,upsert=True)
    end=time.time()+max(1,timeout)
    while time.time()<end:
        rows=db.select("verification_jobs",{"select":"state,result,result_digest","action_digest":f"eq.{digest}","limit":"1"}) or []
        if rows and rows[0].get("state") in ("DONE","FAILED"):
            result=rows[0].get("result") or {}
            return {"done":True,"passed":rows[0]["state"]=="DONE","result":result,
                    "result_digest":rows[0].get("result_digest")}
        time.sleep(.5)
    return {"done":False,"passed":False,"fallback":"local","action_digest":digest}

