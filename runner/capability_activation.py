#!/usr/bin/env python3
import hashlib,json
def record(capability,invocation_key,task=None,effect=False,outcome=None,metrics=None):
 task=task or {};key=str(invocation_key or hashlib.sha256(json.dumps(metrics or {},sort_keys=True).encode()).hexdigest())
 try:
  import db
  return db.insert('capability_activation_proofs',{'task_id':task.get('id'),'project_id':task.get('project_id'),'capability':str(capability),'invocation_key':key[:256],'invoked':True,'effect':bool(effect),'outcome':outcome,'metrics':metrics or {}},upsert=True)
 except Exception:return None
