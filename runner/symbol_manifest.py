#!/usr/bin/env python3
import hashlib,json,os,re,subprocess,time
SYMBOL=re.compile(r'\b(?:class|def|function|interface|type|const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)');TEXT={'.py','.js','.ts','.tsx','.jsx','.go','.rs','.java','.vue','.sql'}
def _git(repo,*args):return subprocess.run(['git',*args],cwd=repo,capture_output=True,text=True,timeout=120)
def create(repo,commit,previous=None):
 t0=time.monotonic();commit=_git(repo,'rev-parse',commit).stdout.strip();tree=_git(repo,'rev-parse',commit+'^{tree}').stdout.strip();pr=_git(repo,'rev-parse',commit+'^');parent=pr.stdout.strip() if pr.returncode==0 else None
 files=[];by={}
 for line in _git(repo,'ls-tree','-r','--format=%(objectname) %(path)',commit).stdout.splitlines():
  blob,_,path=line.partition(' ');row={'path':path,'blob':blob};files.append(row);by[path]=row
 prior=previous or {};oldfiles={r['path']:r.get('blob') for r in prior.get('files',[])};changed={p for p,r in by.items() if oldfiles.get(p)!=r['blob']}|set(oldfiles)-set(by);symbols={p:v for p,v in prior.get('symbols',{}).items() if p in by and p not in changed}
 for path in sorted(changed):
  if os.path.splitext(path)[1].lower() not in TEXT:continue
  out=subprocess.run(['git','show',commit+':'+path],cwd=repo,capture_output=True,text=True,timeout=120)
  if out.returncode==0:
   found=sorted(set(SYMBOL.findall(out.stdout)))
   if found:symbols[path]=found
 root=hashlib.sha256('\n'.join(r['blob']+' '+r['path'] for r in files).encode()).hexdigest();body={'schema':'orchestrator.symbol-manifest/v2','commit_sha':commit,'parent_sha':parent,'tree_sha':tree,'merkle_root':root,'files':files,'symbols':symbols,'changed_files':sorted(changed),'parse_ms':int((time.monotonic()-t0)*1000)};body['id']=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest();return body
