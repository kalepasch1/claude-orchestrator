#!/usr/bin/env python3
"""Invocation → effect → outcome proofs for declared orchestration capabilities."""
from __future__ import annotations
import json, os, time, uuid
import db

DECLARED=("secondary_flow","objective_admission","patch_fabric","portfolio_planner",
          "actuator_leases","product_metrics","capability_registry","flow_promotion",
          "hermetic_cas","symbol_context","transformation_market","merge_certificates","sequential_allocator","workflow_comparison")

def _path():
    home=os.environ.get("CLAUDE_ORCH_HOME",os.path.join(os.path.dirname(__file__),"..",".runtime"))
    return os.path.join(home,"activation-proofs.jsonl")

def record(capability: str, stage: str, success: bool, trace_id=None, task_id=None,
           artifact_id=None, **detail):
    row={"capability":capability,"stage":stage,"success":bool(success),
         "trace_id":trace_id or str(uuid.uuid4()),"task_id":task_id,
         "artifact_id":artifact_id,"detail":detail,"at":time.time()}
    try:
        os.makedirs(os.path.dirname(_path()),exist_ok=True)
        with open(_path(),"a") as f:f.write(json.dumps(row,separators=(",",":"),default=str)+"\n")
    except OSError:pass
    try: db.insert("capability_activation_events",{k:v for k,v in row.items() if k!="at"})
    except Exception:pass
    return row

def audit(window_hours=24):
    cutoff=time.time()-window_hours*3600
    try:
        with open(_path()) as f:rows=[json.loads(x) for x in f if x.strip() and json.loads(x).get("at",0)>=cutoff]
    except Exception:rows=[]
    by={c:{"invocation":0,"effect":0,"outcome":0} for c in DECLARED}
    for row in rows:
        if row.get("capability") in by and row.get("success") and row.get("stage") in by[row["capability"]]:
            stage=row["stage"]
            by[row["capability"]]["invocation"]+=1
            if stage in ("effect", "outcome"): by[row["capability"]]["effect"]+=1
            if stage == "outcome": by[row["capability"]]["outcome"]+=1
    dormant=[c for c,v in by.items() if not v["invocation"]]
    hollow=[c for c,v in by.items() if v["invocation"] and not v["effect"]]
    unproven=[c for c,v in by.items() if v["effect"] and not v["outcome"]]
    report={"window_hours":window_hours,"capabilities":by,"dormant":dormant,
            "hollow":hollow,"unproven":unproven,"generated_at":time.time()}
    try: db.insert("controls",{"key":"activation_proofs","value":json.dumps(report),"updated_at":"now()"},upsert=True)
    except Exception:pass
    print("activation-proofs:",json.dumps(report,sort_keys=True));return report

if __name__=="__main__":audit()
