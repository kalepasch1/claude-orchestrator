#!/usr/bin/env python3
"""Fail-closed billing-aware Cowork/native arbitration."""
import os,time
DETERMINISTIC_KINDS={'mechanical','format','lint','bump','cleanup','replay'}
def cowork_capacity():
 try:
  import account_pool
  pool=account_pool.AccountPool(); accounts=pool.subscription_accounts(); healthy=[a for a in accounts if pool._healthy(a)]
  return {'configured':len(accounts),'healthy':len(healthy),'exhausted':bool(accounts) and not healthy,'accounts':[a.get('name') for a in healthy]}
 except Exception as exc:return {'configured':0,'healthy':0,'exhausted':False,'accounts':[],'error':str(exc)[:160]}
def decide(task=None,capacity=None):
 task=task or {};cap=capacity or cowork_capacity();forced=str(task.get('execution_lane') or '').lower()
 if forced in ('cowork','orchestrator_native'):
  if forced=='cowork' and cap.get('exhausted'):return {'lane':'orchestrator_native','paid_api_eligible':True,'reason':'all bundled accounts exhausted; forced Cowork overridden','capacity':cap}
  return {'lane':forced,'paid_api_eligible':forced=='orchestrator_native' and bool(cap.get('exhausted')),'reason':'explicit execution lane','capacity':cap}
 if (str(task.get('kind') or '').lower() in DETERMINISTIC_KINDS and task.get('deterministic_patch')) or task.get('reuse_artifact_id'):return {'lane':'orchestrator_native','paid_api_eligible':False,'reason':'zero-token deterministic/reuse artifact','capacity':cap}
 if cap.get('exhausted'):return {'lane':'orchestrator_native','paid_api_eligible':True,'reason':'all bundled Cowork accounts exhausted; native overflow enabled','capacity':cap}
 if os.environ.get('ORCH_PREFER_COWORK_PATH','true').lower() in ('1','true','yes','on') and cap.get('healthy',0)>0:return {'lane':'cowork','paid_api_eligible':False,'reason':'bundled Cowork capacity available','capacity':cap}
 return {'lane':'orchestrator_native','paid_api_eligible':False,'reason':'native selected without paid API permission','capacity':cap}
def record(task,decision):
 try:
  import db,capability_activation
  row=db.insert('pathway_decisions',{'task_id':task.get('id'),'project_id':task.get('project_id'),'lane':decision['lane'],'reason':decision['reason'],'cowork_exhausted':bool(decision.get('capacity',{}).get('exhausted')),'paid_api_eligible':bool(decision.get('paid_api_eligible')),'detail':decision})
  capability_activation.record('billing_aware_pathway_arbitration',task.get('id') or str(time.time_ns()),task=task,effect=True,outcome=decision['lane'],metrics={'cowork_exhausted':bool(decision.get('capacity',{}).get('exhausted'))});return row
 except Exception:return None
