#!/usr/bin/env python3
"""Repeatable, coverage-aware Cowork vs orchestrator-native performance comparison."""
from __future__ import annotations
import collections,datetime,json,statistics
import db
def summarize(outcomes,tasks,hours=2,contracts=None):
    contracts=contracts or []
    native=[r for r in outcomes if str(r.get("account") or "").lower()=="parallel-swarm"]
    cowork_out=[r for r in outcomes if str(r.get("account") or "").lower().startswith("cowork-")]
    cowork_tasks=[t for t in tasks if str(t.get("account") or "").lower().startswith("cowork-")]
    cowork_done=[t for t in cowork_tasks if t.get("state") in ("DONE","MERGED")]
    def outcome_stats(rows):
        passed=sum(r.get("tests_passed") is True for r in rows);integrated=sum(r.get("integrated") is True for r in rows);walls=[float(r.get("wall_ms") or 0) for r in rows]
        return {"attempts":len(rows),"unique_tasks":len({r.get("task_id") for r in rows if r.get("task_id")}),"tests_passed":passed,"pass_rate":passed/max(1,len(rows)),"verified_per_hour":passed/hours,"integrated":integrated,"integrated_per_hour":integrated/hours,"avg_wall_seconds":sum(walls)/max(1,len(walls))/1000,"tokens":sum(int(r.get("input_tokens") or 0)+int(r.get("output_tokens") or 0) for r in rows),"usd":sum(float(r.get("usd") or 0) for r in rows)}
    n=outcome_stats(native);c=outcome_stats(cowork_out);c.update({"tasks_touched":len(cowork_tasks),"task_state_counts":dict(collections.Counter(t.get("state") for t in cowork_tasks)),"task_completions":len(cowork_done),"task_completions_per_hour":len(cowork_done)/hours})
    by_lane={}
    for lane in ("cowork","orchestrator_native"):
        rows=[x for x in contracts if x.get("lane")==lane]
        by_lane[lane]={"contracts":len(rows),"attempted":sum(x.get("stage")=="attempted" for x in rows),
            "verified":sum(x.get("stage")=="verified" for x in rows),
            "integrated":sum(x.get("stage")=="integrated" for x in rows),
            "deployed":sum(x.get("stage")=="deployed" for x in rows),
            "failed":sum(x.get("stage")=="failed" for x in rows)}
    comparable=bool(by_lane.get("cowork",{}).get("verified") and by_lane.get("orchestrator_native",{}).get("verified"))
    return {"hours":hours,"cowork":c,"orchestrator_native":n,"canonical_contracts":by_lane,"comparison":{"task_completion_ratio_cowork_to_native_verified":len(cowork_done)/max(1,n["tests_passed"]),"verified_throughput_ratio_native_to_cowork":None if not c["tests_passed"] else n["verified_per_hour"]/c["verified_per_hour"]},"coverage":{"cowork_outcome_rows":len(cowork_out),"native_outcome_rows":len(native),"comparable_quality":comparable,"warning":None if comparable else "One lane has not emitted a canonical state transition in this window."}}
def run(hours=2):
    now=datetime.datetime.now(datetime.timezone.utc);cut=(now-datetime.timedelta(hours=hours)).isoformat()
    outcomes=db.select("outcomes",{"select":"task_id,account,tests_passed,integrated,wall_ms,input_tokens,output_tokens,usd,created_at","created_at":f"gte.{cut}","limit":"10000"}) or []
    tasks=db.select("tasks",{"select":"id,state,account,created_at,updated_at","updated_at":f"gte.{cut}","limit":"10000"}) or []
    contracts=db.select("workflow_outcome_contracts",{"select":"task_id,lane,stage,from_state,to_state,observed_at","observed_at":f"gte.{cut}","limit":"10000"}) or []
    report={"window_start":cut,"window_end":now.isoformat(),**summarize(outcomes,tasks,hours,contracts)}
    try:db.insert("controls",{"key":f"workflow_comparison_{hours}h","value":json.dumps(report),"updated_at":"now()"},upsert=True)
    except Exception:pass
    print(json.dumps(report,indent=2));return report
if __name__=="__main__":run()
