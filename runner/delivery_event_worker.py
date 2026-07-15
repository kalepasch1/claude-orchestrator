#!/usr/bin/env python3
import json,socket,db,symbol_manifest
def run_once():
 rows=db.rpc('claim_delivery_event',{'p_runner':socket.gethostname()}) or []
 if not rows:return {'claimed':False}
 event=rows[0];payload=event.get('payload') or {}
 try:
  if event.get('provider')=='github':
   repo_name=(payload.get('repository') or {}).get('name');sha=(payload.get('after') or payload.get('head_commit',{}).get('id'))
   projects=db.select('projects',{'select':'*','repo_path':f'ilike.%/{repo_name}','limit':'1'}) or []
   if projects and sha:
    project=projects[0];repo=db.localize_repo_path(project['repo_path']);parents=db.select('commit_manifests',{'select':'*','project_id':f"eq.{project['id']}",'order':'created_at.desc','limit':'1'}) or [];m=symbol_manifest.create(repo,sha,parents[0] if parents else None)
    db.insert('commit_manifests',{'id':m['id'],'project_id':project['id'],'commit_sha':m['commit_sha'],'parent_sha':m['parent_sha'],'tree_sha':m['tree_sha'],'symbols':m['symbols'],'files':m['files'],'changed_files':m['changed_files'],'parse_ms':m['parse_ms']},upsert=True)
    commands=[x for x in (project.get('test_cmd'),project.get('build_cmd')) if x];db.insert('native_verification_jobs',{'project_id':project['id'],'commit_sha':sha,'manifest_id':m['id'],'commands':commands},upsert=True)
  db.update('delivery_events',{'id':event['id']},{'state':'done','completed_at':'now()'});return {'claimed':True,'ok':True}
 except Exception as exc:
  db.update('delivery_events',{'id':event['id']},{'state':'failed','error':str(exc)[:1000],'completed_at':'now()'});return {'claimed':True,'ok':False,'error':str(exc)}
if __name__=='__main__':print(json.dumps(run_once()))
