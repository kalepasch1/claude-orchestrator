#!/usr/bin/env python3
"""Deterministic holdouts and causal product-value observations."""
from __future__ import annotations
import hashlib, math, os, statistics, time
import db

def assignment(subject: str, experiment: str, treatment_pct=90) -> str:
    bucket=int(hashlib.sha256(f"{experiment}:{subject}".encode()).hexdigest()[:8],16)%100
    return "treatment" if bucket < max(0,min(100,int(treatment_pct))) else "control"

def record(project_id, experiment, metric, value, subject="", variant="", task_id=None,
           release_id=None, guardrail=False, **metadata):
    variant=variant or assignment(subject or "anonymous",experiment)
    row={"project_id":project_id,"task_id":task_id,"release_id":release_id,
         "experiment":experiment,"metric":metric,"variant":variant,
         "subject_hash":hashlib.sha256(str(subject).encode()).hexdigest()[:24] if subject else None,
         "value":float(value),"guardrail":bool(guardrail),"metadata":metadata}
    try:
        result=db.insert("product_metric_events",row)
        try:
            import activation_proof
            activation_proof.record("product_metrics", "outcome", True, task_id=task_id,
                                    experiment=experiment, metric=metric, variant=variant)
        except Exception: pass
        return result
    except Exception:return None

def effect(experiment, metric, days=30):
    import datetime
    cutoff=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=days)).isoformat()
    try: rows=db.select("product_metric_events",{"select":"variant,value,guardrail,observed_at",
        "experiment":f"eq.{experiment}","metric":f"eq.{metric}","observed_at":f"gte.{cutoff}","limit":"10000"}) or []
    except Exception: rows=[]
    vals={"treatment":[],"control":[]}
    for r in rows:
        if r.get("variant") in vals:vals[r["variant"]].append(float(r.get("value") or 0))
    t,c=vals["treatment"],vals["control"]
    delta=(statistics.mean(t)-statistics.mean(c)) if t and c else 0.0
    se=math.sqrt((statistics.pvariance(t)/len(t) if len(t)>1 else 0)+
                 (statistics.pvariance(c)/len(c) if len(c)>1 else 0)) if t and c else float("inf")
    return {"experiment":experiment,"metric":metric,"treatment_n":len(t),"control_n":len(c),
            "delta":delta,"lower_95":delta-1.96*se if math.isfinite(se) else None,
            "upper_95":delta+1.96*se if math.isfinite(se) else None}
