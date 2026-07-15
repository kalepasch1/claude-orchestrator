#!/usr/bin/env python3
"""Sequential evidence allocation: stop losers early and fund uncertain high-value lanes."""
from __future__ import annotations
import datetime,json,math
import db
def _summary(rows):
    out={}
    for r in rows:
        v=r.get("variant") or "unknown"; x=float(r.get("value") or 0); a=out.setdefault(v,{"n":0,"sum":0.0,"sum2":0.0});a["n"]+=1;a["sum"]+=x;a["sum2"]+=x*x
    for a in out.values():
        a["mean"]=a["sum"]/max(1,a["n"]); var=max(0,a["sum2"]/max(1,a["n"])-a["mean"]**2);a["se"]=math.sqrt(var/max(1,a["n"]));a["lower_95"]=a["mean"]-1.96*a["se"];a["upper_95"]=a["mean"]+1.96*a["se"]
    return out
def allocate(experiment="orchestration_flow_value",metric="deployed_non_regressed_value",days=30):
    cutoff=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=days)).isoformat()
    try: rows=db.select("product_metric_events",{"select":"variant,value,observed_at","experiment":f"eq.{experiment}","metric":f"eq.{metric}","observed_at":f"gte.{cutoff}","limit":"10000"}) or []
    except Exception:rows=[]
    arms=_summary(rows); total=sum(a["n"] for a in arms.values()); best=max((a["lower_95"] for a in arms.values()),default=0)
    allocation={}
    for v,a in arms.items():
        if a["n"]>=20 and a["upper_95"]<best: allocation[v]=0
        else: allocation[v]=max(5,round(100*(a["se"]+1/max(1,a["n"])) / max(1e-9,sum(x["se"]+1/max(1,x["n"]) for x in arms.values()))))
    report={"experiment":experiment,"metric":metric,"samples":total,"arms":arms,"allocation_pct":allocation}
    try:db.insert("controls",{"key":"sequential_evidence_allocation","value":json.dumps(report),"updated_at":"now()"},upsert=True)
    except Exception:pass
    try:
        import activation_proof
        activation_proof.record("sequential_allocator","outcome",True,samples=total,allocation=allocation)
    except Exception:pass
    print(json.dumps(report,sort_keys=True));return report
if __name__=="__main__":allocate()
