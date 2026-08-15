#!/usr/bin/env python3
"""Classify apparently 'lost' ledger items: already-present vs genuinely-missing,
by reading the CURRENT dev tree. Cuts blind re-implementation of code that exists."""
import os, re, sys, json
sys.path.insert(0, '/Users/kpasch/Documents/beethoven/claude-orchestrator/runner')
import db
REPO='/Users/kpasch/Documents/apparently'
PATH_RE=re.compile(r'((?:server|app|shared|components|pages|composables)/[A-Za-z0-9_./-]+\.(?:ts|vue|tsx|js|mjs))')
# a spec often names a function/const to build; detect it in the live file
SYM_RE=re.compile(r'\b(?:build|compute|detect|apply|classify|dedup|score|ensure|generate|resolve|counter|forecast)[A-Z][A-Za-z0-9]+')

def main():
    pid=(db.select('projects',{'select':'id','name':'eq.apparently'}) or [{}])[0].get('id')
    rows=db.select('tasks',{'select':'slug,prompt','project_id':f'eq.{pid}',
        'state':'in.(PHANTOM_UNVERIFIED,DONE)','order':'created_at.asc','limit':'900'}) or []
    present=[]; missing=[]; nofile=[]
    for r in rows:
        pr=r.get('prompt') or ''
        paths=[p for p in dict.fromkeys(PATH_RE.findall(pr))]
        # primary target = first path that looks like a source file (skip test/aider/cache)
        tgt=next((p for p in paths if '.test.' not in p and '.aider' not in p and 'cache' not in p), None)
        if not tgt:
            nofile.append(r['slug']); continue
        fp=os.path.join(REPO,tgt)
        if not os.path.isfile(fp):
            missing.append((r['slug'],tgt,'file-absent')); continue
        # file exists; does it contain a symbol the spec asks to build?
        syms=set(SYM_RE.findall(pr))
        try: txt=open(fp,encoding='utf-8',errors='ignore').read()
        except Exception: txt=''
        hit=[s for s in syms if s in txt]
        if hit:
            present.append((r['slug'],tgt,hit[:3]))
        else:
            missing.append((r['slug'],tgt,'file-present-symbol-absent'))
    out={'present':present,'missing':missing,'no_target_file':nofile,
         'counts':{'present':len(present),'missing':len(missing),'nofile':len(nofile)}}
    json.dump(out,open('/tmp/present_vs_missing.json','w'),indent=1)
    print('PRESENT (already on dev):',len(present))
    print('MISSING (real work):',len(missing))
    print('NO extractable target file:',len(nofile))
    print('--- sample PRESENT ---')
    for s in present[:8]: print('  ',s[0],'->',s[1])
    print('--- sample MISSING ---')
    for s in missing[:8]: print('  ',s[0],'->',s[1],s[2])

if __name__=='__main__': main()
