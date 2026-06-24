#!/usr/bin/env python3
"""
knowledge.py - cross-project learning. So you stop drafting from scratch and every
project benefits from what the others already solved.

Two verbs:
  extract  - after a task, save a reusable note (what was built, key functions,
             gotchas) tagged with keywords, into ~/.claude-orchestrator/knowledge/
  inject   - before a task, search that store and PREPEND the most relevant prior
             solutions to the prompt ("here's how we solved this before: ...").

Dependency-free keyword/TF retrieval - good enough to surface reuse without a vector
DB. Swap in embeddings later for the 100x version (see README roadmap).

CLI:
  knowledge.py extract --project tomorrow --title "RLS policy helper" --tags "supabase,rls" --body-file note.md
  knowledge.py inject "add row-level security to the ledger table"      # prints augmented prompt
"""
import os, sys, json, re, argparse, glob, math, time
from collections import Counter

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
KB = os.path.join(HOME, "knowledge")
os.makedirs(KB, exist_ok=True)
STOP = set("the a an and or of to in for on with is are be this that it as at by from".split())


def toks(s):
    return [w for w in re.findall(r"[a-z0-9_]+", (s or "").lower()) if w not in STOP and len(w) > 2]


def extract(project, title, tags, body):
    rec = {"project": project, "title": title, "tags": [t.strip() for t in tags.split(",") if t.strip()],
           "body": body, "ts": time.time(),
           "keywords": list(Counter(toks(title + " " + tags + " " + body)).keys())[:40]}
    fn = os.path.join(KB, f"{project}--{re.sub('[^a-z0-9]+','-',title.lower())[:50]}-{int(rec['ts'])}.json")
    json.dump(rec, open(fn, "w"), indent=2)
    print(f"stored {fn}")


def _load():
    out = []
    for f in glob.glob(os.path.join(KB, "*.json")):
        try: out.append(json.load(open(f)))
        except Exception: pass
    return out


def rank(query, rows, k=3):
    """Rank provided row dicts (each with 'keywords') by tf-idf overlap with query."""
    if not rows:
        return []
    q = Counter(toks(query))
    df = Counter()
    for n in rows:
        for w in set(n.get("keywords", []) or []):
            df[w] += 1
    N = len(rows)
    scored = []
    for n in rows:
        kw = set(n.get("keywords", []) or [])
        s = sum(q[w] * math.log(1 + N / (1 + df[w])) for w in q if w in kw)
        if s > 0:
            scored.append((s, n))
    scored.sort(key=lambda x: -x[0])
    return [n for _, n in scored[:k]]


def search(query, k=3):
    notes = _load()
    if not notes:
        return []
    q = Counter(toks(query))
    # idf over the corpus
    df = Counter()
    for n in notes:
        for w in set(n.get("keywords", [])):
            df[w] += 1
    N = len(notes)
    scored = []
    for n in notes:
        kw = set(n.get("keywords", []))
        s = sum(q[w] * math.log(1 + N / (1 + df[w])) for w in q if w in kw)
        if s > 0:
            scored.append((s, n))
    scored.sort(key=lambda x: -x[0])
    return [n for _, n in scored[:k]]


def inject(prompt, k=3):
    hits = search(prompt, k)
    if not hits:
        return prompt
    blocks = []
    for h in hits:
        blocks.append(f"### {h['title']} (from {h['project']})\n{h['body'].strip()}")
    pre = ("# Relevant prior solutions from other projects - REUSE or adapt these "
           "instead of writing from scratch:\n\n" + "\n\n".join(blocks) +
           "\n\n# ---- your task ----\n")
    return pre + prompt


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--project", required=True); e.add_argument("--title", required=True)
    e.add_argument("--tags", default=""); e.add_argument("--body-file"); e.add_argument("--body", default="")
    i = sub.add_parser("inject"); i.add_argument("query"); i.add_argument("-k", type=int, default=3)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("-k", type=int, default=3)
    a = ap.parse_args()
    if a.cmd == "extract":
        body = open(a.body_file).read() if a.body_file else a.body
        extract(a.project, a.title, a.tags, body)
    elif a.cmd == "inject":
        print(inject(a.query, a.k))
    elif a.cmd == "search":
        for n in search(a.query, a.k):
            print(f"- {n['title']} ({n['project']}) tags={n.get('tags')}")
