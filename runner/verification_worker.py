#!/usr/bin/env python3
import hashlib,json,os,shutil,socket,subprocess,tempfile,db,proof_graph,remote_cas
def run_once():
 rows=db.rpc('claim_native_verification_job',{'p_runner':socket.gethostname()}) or []
 if not rows:return {'claimed':False}
 job=rows[0];projects=db.select('projects',{'select':'*','id':f"eq.{job['project_id']}",'limit':'1'}) or []
 if not projects:return {'claimed':True,'ok':False,'error':'project missing'}
 repo=db.localize_repo_path(projects[0]['repo_path']);root=tempfile.mkdtemp(prefix='verify-job-');tree=os.path.join(root,'tree');added=False;result={'host':socket.gethostname(),'commands':[],'ok':False}
 try:
  r=subprocess.run(['git','worktree','add','--detach',tree,job['commit_sha']],cwd=repo,capture_output=True,text=True)
  if r.returncode:raise RuntimeError(r.stderr[-1000:])
  added=True
  try:
   import dependency_prewarm;dependency_prewarm.link_shared_runtime(repo,tree)
  except Exception:pass
  # Nuxt worktrees intentionally exclude generated .nuxt state. Generate its
  # type/config contract before Vitest or typecheck, just as CI does.
  web=os.path.join(tree,'web')
  if os.path.isfile(os.path.join(web,'nuxt.config.ts')) and not os.path.isfile(os.path.join(web,'.nuxt','tsconfig.json')):
   prepared=subprocess.run(['npx','nuxi','prepare'],cwd=web,capture_output=True,text=True,timeout=300)
   if prepared.returncode:raise RuntimeError('Nuxt prepare failed: '+((prepared.stdout or '')+(prepared.stderr or ''))[-1000:])
  dep=proof_graph.dependency_fingerprint(tree)
  for cmd in job.get('commands') or []:
   k=remote_cas.key(repo,job['commit_sha'],dep,cmd,job.get('image') or '');cached=remote_cas.get(k)
   if cached:result['commands'].append({'command':cmd,'ok':True,'cached':True});continue
   image=job.get('image')
   if image and shutil.which('docker'):run=subprocess.run(['docker','run','--rm','--network=none','--mount',f'type=bind,src={tree},dst=/workspace','-w','/workspace',image,'bash','-lc',cmd],capture_output=True,text=True,timeout=1800)
   else:run=subprocess.run(['bash','-lc',cmd],cwd=tree,capture_output=True,text=True,timeout=1800)
   entry={'command':cmd,'ok':run.returncode==0,'tail':((run.stdout or '')+(run.stderr or ''))[-2000:]};remote_cas.put(k,entry,run.returncode==0);result['commands'].append(entry)
   if run.returncode:raise RuntimeError('verification failed: '+cmd)
  result['ok']=True;digest=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest();db.update('native_verification_jobs',{'id':job['id']},{'state':'done','proof_digest':digest,'result':result,'completed_at':'now()'});return {'claimed':True,'ok':True,'proof_digest':digest}
 except Exception as exc:result['error']=str(exc)[:1000];db.update('native_verification_jobs',{'id':job['id']},{'state':'failed','result':result,'completed_at':'now()'});return {'claimed':True,'ok':False,'error':str(exc)}
 finally:
  if added:subprocess.run(['git','worktree','remove','--force',tree],cwd=repo,capture_output=True)
  shutil.rmtree(root,ignore_errors=True)
if __name__=='__main__':print(json.dumps(run_once()))
