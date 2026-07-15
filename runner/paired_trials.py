#!/usr/bin/env python3
"""Mutation-free paired trial evidence: both lanes are measured, neither is merged here."""
from __future__ import annotations
import hashlib,json
import db
def key(task,base_sha=""):
    if task.get("paired_trial_key"):return str(task["paired_trial_key"])
    objective=" ".join((task.get("prompt") or "").lower().split())
    return hashlib.sha256((str(task.get("project_id"))+"\0"+base_sha+"\0"+objective).encode()).hexdigest()
def record(task,lane,passed,artifact=None,duration_ms=0,value_per_hour=None,detail=None,base_sha=""):
    row={"trial_key":key(task,base_sha),"lane":lane,"task_id":task.get("id"),"base_sha":base_sha or None,
         "artifact_id":(artifact or {}).get("artifact_id"),"passed":bool(passed),
         "duration_ms":int(duration_ms or 0),"value_per_hour":value_per_hour,
         "detail":detail or {"mutation_applied":False}}
    db.insert("paired_shadow_trials",row,upsert=True);return row
