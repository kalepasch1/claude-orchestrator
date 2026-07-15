#!/usr/bin/env python3
import hashlib,json,os,re,shutil,socket,subprocess,tempfile,time,patch_protocol
def _git(repo,*args,input_text=None,timeout=180):return subprocess.run(['git',*args],cwd=repo,input=input_text,capture_output=True,text=True,timeout=timeout)
def verify(repo,raw_patch,slug,base_ref='HEAD',test_cmd='',materialize=True,timeout=900):
 started=time.monotonic();base=_git(repo,'rev-parse',base_ref)
 if base.returncode:return {'ok':False,'stage':'base','detail':base.stderr[-1000:]}
 base_sha=base.stdout.strip();root=tempfile.mkdtemp(prefix='orch-proof-');tree=os.path.join(root,'tree');added=False
 try:
  made=_git(repo,'worktree','add','--detach',tree,base_sha)
  if made.returncode:return {'ok':False,'stage':'worktree','detail':made.stderr[-1000:]}
  added=True
  try:patch,files,protocol=patch_protocol.normalize(raw_patch,tree)
  except Exception as exc:return {'ok':False,'stage':'protocol','detail':str(exc)[:1000]}
  if _git(tree,'apply','--check','--whitespace=error-all','-',input_text=patch).returncode:return {'ok':False,'stage':'apply-check'}
  if _git(tree,'apply','--index','--whitespace=error-all','-',input_text=patch).returncode:return {'ok':False,'stage':'apply'}
  tail='git invariants passed'
  if test_cmd:
   test_env=os.environ.copy();test_env['PYTHONPYCACHEPREFIX']=os.path.join(tree,'.orch-pycache')
   tested=subprocess.run(['bash','-lc',test_cmd],cwd=tree,env=test_env,capture_output=True,text=True,timeout=timeout);tail=((tested.stdout or '')+(tested.stderr or ''))[-3000:]
   if tested.returncode:return {'ok':False,'stage':'tests','detail':tail}
  tree_sha=_git(tree,'write-tree').stdout.strip();commit=_git(tree,'commit-tree',tree_sha,'-p',base_sha,'-m','native: '+re.sub(r'[^\w.-]+','-',slug)[:100]).stdout.strip()
  receipt={'schema':'orchestrator.verification/v1','base_sha':base_sha,'commit_sha':commit,'patch_sha256':hashlib.sha256(patch.encode()).hexdigest(),'protocol':protocol,'files':files,'test_cmd':test_cmd,'host':socket.gethostname(),'tests_passed':True};artifact=hashlib.sha256(json.dumps(receipt,sort_keys=True).encode()).hexdigest();branch='agent/'+re.sub(r'[^\w.-]+','-',slug)[:100]
  if materialize:
   current=_git(repo,'rev-parse','--verify','refs/heads/'+branch);old=current.stdout.strip() if current.returncode==0 else '0'*40
   update=_git(repo,'update-ref','refs/heads/'+branch,commit,old)
   if update.returncode:return {'ok':False,'stage':'materialize','detail':update.stderr[-1000:]}
  result={'ok':True,'artifact_id':artifact,'base_sha':base_sha,'commit':commit,'branch':branch if materialize else None,'files':files,'test_tail':tail,'duration_ms':int((time.monotonic()-started)*1000),'receipt':receipt}
  try:
   import capability_activation;capability_activation.record('branchless_delivery_proof',artifact,effect=True,outcome='verified',metrics={'duration_ms':result['duration_ms'],'files':len(files),'materialized':materialize})
  except Exception:pass
  return result
 finally:
  if added:_git(repo,'worktree','remove','--force',tree)
  shutil.rmtree(root,ignore_errors=True)
