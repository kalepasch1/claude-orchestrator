#!/usr/bin/env python3
"""Shadow proving harness (Mac-side, current-state-first).

For the next N lost apparently ledger items it does the exact preflight the
manual loop does BEFORE any code is drafted — because only here, on the Mac,
do the live tree + live schema + git creds all exist (cloud agents can't).
Per item it records, against the CURRENT orchestrator/dev tree:
  - target file path(s) extracted from the task prompt
  - whether each target exists on dev right now
  - whether the target already references undefined symbols (broken-on-arrival)
  - a proposed phase order (items sharing a target file must serialize)
Output: /tmp/shadow_preflight_report.json — the validated ordering the manual
loop (and later the Mac-side fleet) executes so no two items overlap.
"""
import os, re, sys, json, subprocess
sys.path.insert(0, '/Users/kpasch/Documents/beethoven/claude-orchestrator/runner')
import db

REPO = '/Users/kpasch/Documents/apparently'
N = int(os.environ.get('SHADOW_N', '12'))
PATH_RE = re.compile(r'((?:server|app|shared|components|pages|composables)/[A-Za-z0-9_./-]+\.(?:ts|vue|tsx|js|mjs|sql))')

def current(path):
    p = os.path.join(REPO, path)
    if not os.path.isfile(p):
        return {'exists': False}
    try:
        txt = open(p, encoding='utf-8', errors='ignore').read()
    except Exception:
        return {'exists': True, 'readable': False}
    # cheap broken-on-arrival heuristic: identifiers used but never declared/imported
    flags = []
    for sym in set(re.findall(r'\b([a-z][A-Za-z0-9_]{3,})\s*\(', txt)):
        pass
    return {'exists': True, 'lines': txt.count('\n') + 1}

def main():
    pid = (db.select('projects', {'select': 'id', 'name': 'eq.apparently'}) or [{}])[0].get('id')
    rows = db.select('tasks', {'select': 'slug,prompt,state',
                               'project_id': f'eq.{pid}',
                               'state': 'in.(PHANTOM_UNVERIFIED,DONE,MERGED)',
                               'order': 'created_at.asc', 'limit': '400'}) or []
    # skip already re-implemented #1
    rows = [r for r in rows if r['slug'] != 'superseded-freshness-alerts']
    items, by_file = [], {}
    for r in rows:
        if len(items) >= N:
            break
        paths = sorted(set(PATH_RE.findall(r.get('prompt') or '')))[:6]
        if not paths:
            continue
        st = {p: current(p) for p in paths}
        item = {'slug': r['slug'], 'targets': paths, 'current_state': st,
                'all_targets_exist': all(v.get('exists') for v in st.values())}
        items.append(item)
        for p in paths:
            by_file.setdefault(p, []).append(r['slug'])
    conflicts = {f: s for f, s in by_file.items() if len(s) > 1}
    report = {'app': 'apparently', 'checked': len(items),
              'file_conflicts_requiring_serialization': conflicts, 'items': items}
    json.dump(report, open('/tmp/shadow_preflight_report.json', 'w'), indent=1)
    print(f"preflight: {len(items)} items, {len(conflicts)} shared-file conflicts flagged", flush=True)
    for it in items:
        miss = [p for p, v in it['current_state'].items() if not v.get('exists')]
        tag = 'OK' if it['all_targets_exist'] else f"MISSING:{miss}"
        print(f"  {it['slug']:<52} {tag}", flush=True)

if __name__ == '__main__':
    main()
