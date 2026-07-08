#!/usr/bin/env python3
"""
regression.py - so the fleet stops repeating mistakes. Records failed approaches +
root causes, and injects the matching "avoid this" lessons into future prompts for
similar work. Seeded with the failure modes we already saw in your sessions.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import knowledge as kw

# Built-in lessons from observed incidents (always injected; project-specific ones come from the DB).
SEEDED = [
    {"keywords": ["sql", "policy", "psql", "shell", "zsh", "supabase", "rls"],
     "lesson": "Never paste raw SQL (create policy/table...) into the shell - it errors with 'parse error'. "
               "Put SQL in a migration file and apply via the migration tool."},
    {"keywords": ["allowlist", "auth", "mint", "security", "permission", "gate"],
     "lesson": "Default-DENY on allowlists. A fail-OPEN allowlist (permit on lookup miss) is a security bug - "
               "close it fail-closed, like the novel-instrument minting fix."},
    {"keywords": ["merge", "conflict", "branch", "worktree", "parallel"],
     "lesson": "Two agents editing the same files corrupt each other. Stay within your task's file scope; "
               "shared interfaces belong in the 'contracts' task."},
    {"keywords": ["secret", "gitleaks", "key", "token", "env"],
     "lesson": "Never commit secrets. If gitleaks flags one: rotate it, purge history, gitignore, re-run."},
]


def record(project, slug, kind, approach, root_cause, lesson):
    keywords = kw.toks(f"{approach} {root_cause} {lesson}")[:30]
    try:
        db.insert("failures", {"project": project, "slug": slug, "kind": kind,
                               "approach": approach[:2000], "root_cause": root_cause[:2000],
                               "lesson": lesson[:1000], "keywords": keywords})
    except Exception as e:
        # Learning telemetry must never turn a fixable task into BLOCKED. Duplicate lessons and
        # transient PostgREST 409s are safe to ignore; the next successful run can record again.
        print(f"regression.record skipped for {project}/{slug}: {e}")


def lessons_for(prompt, k=4):
    q = set(kw.toks(prompt))
    hits = []
    for s in SEEDED:                                   # always-on incident rules
        if q & set(s["keywords"]):
            hits.append(s["lesson"])
    try:                                               # learned project lessons
        rows = db.select("failures", {"select": "lesson,keywords", "order": "created_at.desc", "limit": "500"}) or []
        for r in kw.rank(prompt, rows, k):
            if r.get("lesson"):
                hits.append(r["lesson"])
    except Exception:
        pass
    seen, out = set(), []
    for l in hits:
        if l not in seen:
            seen.add(l); out.append(l)
    return out[:k + len(SEEDED)]


def inject(prompt):
    ls = lessons_for(prompt)
    if not ls:
        return prompt
    return ("# Avoid these known failure modes (learned from past runs):\n" +
            "\n".join(f"- {l}" for l in ls) + "\n\n" + prompt)
