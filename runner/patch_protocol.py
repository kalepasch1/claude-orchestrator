#!/usr/bin/env python3
import difflib,hashlib,json,os,re
SCHEMA='orchestrator.patch/v1';MAX_FILES=80;MAX_BYTES=2_000_000
class PatchProtocolError(ValueError):pass
def _safe(p):
 p=str(p or '').replace('\\','/').strip()
 if not p or p.startswith('/') or '..' in p.split('/') or p.startswith('.git/') or '\0' in p:raise PatchProtocolError('unsafe patch path')
 return p
def provider_schema():
 import ast_rewrite_ir
 patch={'type':'object','additionalProperties':False,'required':['schema','files'],'properties':{'schema':{'const':SCHEMA},'files':{'type':'array','minItems':1,'maxItems':MAX_FILES,'items':{'type':'object','additionalProperties':False,'required':['path','operation','after_text'],'properties':{'path':{'type':'string'},'operation':{'enum':['create','modify','delete']},'before_sha256':{'type':'string'},'after_text':{'type':'string'}}}}}}
 return {'oneOf':[patch,ast_rewrite_ir.schema()]}
def system_prompt():return 'Return only JSON matching orchestrator.patch/v1 or orchestrator.ast-rewrite/v1. Include SHA-256 preimages and exact occurrence counts.'
def normalize(raw,repo):
 text=str(raw or '').strip();obj=None
 try:obj=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',text))
 except Exception:pass
 if isinstance(obj,dict):
  protocol=obj.get('schema')
  if protocol=='orchestrator.ast-rewrite/v1':
   import ast_rewrite_ir;obj=ast_rewrite_ir.compile_ir(obj,repo)
  if obj.get('schema')!=SCHEMA:raise PatchProtocolError('unsupported patch schema')
  chunks=[];files=[];total=0
  for item in obj.get('files') or []:
   path=_safe(item.get('path'));target=os.path.join(repo,path);exists=os.path.isfile(target)
   if exists:
    with open(target,encoding='utf-8') as h:before=h.read()
   else:before=''
   op=item.get('operation');after=str(item.get('after_text') or '')
   if op=='create' and exists:raise PatchProtocolError('create target exists')
   if op in ('modify','delete') and (not exists or hashlib.sha256(before.encode()).hexdigest()!=item.get('before_sha256')):raise PatchProtocolError('preimage mismatch: '+path)
   if op=='delete':after=''
   elif op not in ('create','modify'):raise PatchProtocolError('invalid operation')
   total+=len(before.encode())+len(after.encode())
   if total>MAX_BYTES:raise PatchProtocolError('patch too large')
   chunk=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='/dev/null' if op=='create' else 'a/'+path,tofile='/dev/null' if op=='delete' else 'b/'+path,lineterm='\n'))
   if not chunk:raise PatchProtocolError('no-op patch')
   chunks.append(chunk if chunk.endswith('\n') else chunk+'\n');files.append(path)
  if not chunks or len(chunks)>MAX_FILES:raise PatchProtocolError('invalid file count')
  return ''.join(chunks),sorted(set(files)),protocol
 text=re.sub(r'```(?:diff|patch)?\s*\n?|\n?```','',text);m=re.search(r'(?m)^(?:diff --git |--- (?:a/|/dev/null))',text)
 if not m:raise PatchProtocolError('no patch')
 patch=text[m.start():].strip()+'\n';files=[_safe(x) for x in re.findall(r'(?m)^\+\+\+ b/([^\t\n]+)',patch)]
 if not files or not re.search(r'(?m)^@@ ',patch):raise PatchProtocolError('incomplete diff')
 return patch,sorted(set(files)),'unified-diff/v1'
