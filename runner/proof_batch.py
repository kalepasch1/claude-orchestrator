#!/usr/bin/env python3
"""Conflict-free commit composition with one full-suite proof."""
import hashlib,json,os,shutil,subprocess,tempfile,time
def git(repo,*args):return subprocess.run(['git',*args],cwd=repo,capture_output=True,text=True,timeout=180)
def compose(repo,base_ref,commits,test_cmd,project_id=None,timeout=1800):
 started=time.monotonic();base=git(repo,'rev-parse',base_ref).stdout.strip();occupied=set()
 for commit in commits:
  files=set(git(repo,'diff','--name-only',base,commit).stdout.splitlines());overlap=occupied&files
  if overlap:return {'ok':False,'stage':'conflict','files':sorted(overlap)}
  occupied|=files
 batch=hashlib.sha256((base+'\0'+'\0'.join(commits)+'\0'+test_cmd).encode()).hexdigest();root=tempfile.mkdtemp(prefix='proof-batch-');tree=os.path.join(root,'tree');added=False
 try:
  r=git(repo,'worktree','add','--detach',tree,base)
  if r.returncode:return {'ok':False,'stage':'worktree','detail':r.stderr[-1000:]}
  added=True
  for commit in commits:
   r=git(tree,'cherry-pick','--no-commit',commit)
   if r.returncode:return {'ok':False,'stage':'compose','detail':r.stderr[-1000:]}
  if test_cmd:
   r=subprocess.run(['bash','-lc',test_cmd],cwd=tree,capture_output=True,text=True,timeout=timeout)
   if r.returncode:return {'ok':False,'stage':'tests','detail':((r.stdout or '')+(r.stderr or ''))[-3000:]}
  tree_sha=git(tree,'write-tree').stdout.strip();candidate=git(tree,'commit-tree',tree_sha,'-p',base,'-m','orchestrator: proven batch').stdout.strip();ref='refs/heads/orchestrator/proof-batch/'+batch[:16];git(repo,'update-ref',ref,candidate);receipt={'id':batch,'base_sha':base,'candidate_sha':candidate,'artifact_commits':commits,'files':sorted(occupied),'test_cmd':test_cmd,'duration_ms':int((time.monotonic()-started)*1000)};receipt['proof_digest']=hashlib.sha256(json.dumps(receipt,sort_keys=True).encode()).hexdigest()
  try:
   import db;db.insert('proof_batches',dict(receipt,project_id=project_id,state='proven',completed_at='now()'),upsert=True)
  except Exception:pass
  return {'ok':True,'ref':ref.replace('refs/heads/',''),**receipt}
 finally:
  if added:git(repo,'worktree','remove','--force',tree)
  shutil.rmtree(root,ignore_errors=True)
