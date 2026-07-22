#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,os,re,subprocess,time
SYMBOL=re.compile(r'\b(?:class|def|function|interface|type|const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)');TEXT={'.py','.js','.ts','.tsx','.jsx','.go','.rs','.java','.vue','.sql'}
def _git(repo,*args):return subprocess.run(['git',*args],cwd=repo,capture_output=True,text=True,timeout=120)
def create(repo,commit,previous=None):
 t0=time.monotonic();commit=_git(repo,'rev-parse',commit).stdout.strip();tree=_git(repo,'rev-parse',commit+'^{tree}').stdout.strip();pr=_git(repo,'rev-parse',commit+'^');parent=pr.stdout.strip() if pr.returncode==0 else None
 files=[];by={}
 for line in _git(repo,'ls-tree','-r','--format=%(objectname) %(path)',commit).stdout.splitlines():
  blob,_,path=line.partition(' ');row={'path':path,'blob':blob};files.append(row);by[path]=row
 prior=previous or {};oldfiles={r['path']:r.get('blob') for r in prior.get('files',[])};changed={p for p,r in by.items() if oldfiles.get(p)!=r['blob']}|set(oldfiles)-set(by);symbols={p:v for p,v in prior.get('symbols',{}).items() if p in by and p not in changed}
 targets=[p for p in sorted(changed) if os.path.splitext(p)[1].lower() in TEXT]
 if targets:
  proc=subprocess.Popen(['git','cat-file','--batch'],cwd=repo,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
  for path in targets:proc.stdin.write((commit+':'+path+'\n').encode())
  proc.stdin.close()
  for path in targets:
   header=proc.stdout.readline().decode(errors='replace').strip().split()
   if len(header)<3 or header[1]!='blob':continue
   content=proc.stdout.read(int(header[2])).decode(errors='replace');proc.stdout.read(1);found=sorted(set(SYMBOL.findall(content)))
   if found:symbols[path]=found
  proc.wait(timeout=120);proc.stdout.close()
 root=hashlib.sha256('\n'.join(r['blob']+' '+r['path'] for r in files).encode()).hexdigest();body={'schema':'orchestrator.symbol-manifest/v2','commit_sha':commit,'parent_sha':parent,'tree_sha':tree,'merkle_root':root,'files':files,'symbols':symbols,'changed_files':sorted(changed),'parse_ms':int((time.monotonic()-t0)*1000)};body['id']=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest();return body
