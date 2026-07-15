#!/usr/bin/env python3
import hashlib,io,keyword,os,re,tokenize
SCHEMA='orchestrator.ast-rewrite/v1';LANGUAGES={'python','javascript','typescript','tsx','jsx'}
class RewriteError(ValueError):pass
def schema():return {'type':'object','additionalProperties':False,'required':['schema','operations'],'properties':{'schema':{'const':SCHEMA},'operations':{'type':'array','minItems':1,'maxItems':100,'items':{'type':'object','additionalProperties':False,'required':['file','language','op','old','new','before_sha256','expected_occurrences'],'properties':{'file':{'type':'string'},'language':{'enum':sorted(LANGUAGES)},'op':{'enum':['rename_symbol','replace_string_literal']},'old':{'type':'string'},'new':{'type':'string'},'before_sha256':{'type':'string'},'expected_occurrences':{'type':'integer','minimum':1}}}}}}
def _safe(p):
 p=str(p or '').replace('\\','/');
 if not p or p.startswith('/') or '..' in p.split('/') or p.startswith('.git/'):raise RewriteError('unsafe rewrite path')
 return p
def _python(src,op):
 tokens=[];n=0
 for tok in tokenize.generate_tokens(io.StringIO(src).readline):
  v=tok.string
  if op['op']=='rename_symbol' and tok.type==tokenize.NAME and v==op['old']:
   if not op['new'].isidentifier() or keyword.iskeyword(op['new']):raise RewriteError('invalid Python identifier')
   v=op['new'];n+=1
  tokens.append(tok._replace(string=v))
 return tokenize.untokenize(tokens),n
def _js(src,op):
 if op['op']!='rename_symbol':raise RewriteError('JS literal rewrites require patch envelope')
 old,new=op['old'],op['new'];out=[];i=n=0;state='code'
 while i<len(src):
  c=src[i];pair=src[i:i+2]
  if state=='code' and pair in ('//','/*'):state='line' if pair=='//' else 'block';out.append(pair);i+=2;continue
  if state=='code' and c in "'\"`":state=c;out.append(c);i+=1;continue
  if state=='line' and c=='\n':state='code'
  elif state=='block' and pair=='*/':state='code';out.append(pair);i+=2;continue
  elif state in ("'",'"','`'):
   if c=='\\' and i+1<len(src):out.append(src[i:i+2]);i+=2;continue
   if c==state:state='code'
  if state=='code' and (c.isalpha() or c in '_$'):
   j=i+1
   while j<len(src) and (src[j].isalnum() or src[j] in '_$'):j+=1
   w=src[i:j]
   if w==old:w=new;n+=1
   out.append(w);i=j;continue
  out.append(c);i+=1
 return ''.join(out),n
def compile_ir(ir,repo):
 if ir.get('schema')!=SCHEMA:raise RewriteError('unsupported rewrite schema')
 grouped={}
 for op in ir.get('operations') or []:grouped.setdefault(_safe(op.get('file')),[]).append(op)
 files=[]
 for path,ops in grouped.items():
  target=os.path.join(repo,path)
  if not os.path.isfile(target):raise RewriteError('missing rewrite target: '+path)
  with open(target,encoding='utf-8') as h:before=h.read()
  current=before
  for op in ops:
   if hashlib.sha256(before.encode()).hexdigest()!=op.get('before_sha256'):raise RewriteError('preimage mismatch: '+path)
   current,n=(_python(current,op) if op['language']=='python' else _js(current,op))
   if n!=int(op.get('expected_occurrences') or 0):raise RewriteError('occurrence mismatch')
  files.append({'path':path,'operation':'modify','before_sha256':hashlib.sha256(before.encode()).hexdigest(),'after_text':current})
 return {'schema':'orchestrator.patch/v1','files':files}
