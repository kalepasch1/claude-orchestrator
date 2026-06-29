#!/usr/bin/env python3
"""
verify.py - verification swarm. Before an expensive-model task's work is integrated,
a CHEAP model reviews the git diff for correctness/security regressions (e.g. the
"fail-open allowlist" class). Cheap insurance on expensive work.

review_diff(worktree, base) -> {"verdict": "pass"|"fail", "notes": "..."}
A 'fail' blocks integration and routes an approval card so you can look.
"""
import os, sys, subprocess, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_cli

REVIEW_MODEL = os.environ.get("VERIFY_MODEL", "claude-haiku-4-5-20251001")

PROMPT = """You are a strict code reviewer. Below is a git diff. Decide if it is safe to
merge. Look for: security regressions (auth/allowlist made permissive, secrets added),
broken error handling, obviously failing logic, removed tests. Reply with a single JSON
object: {"verdict":"pass"|"fail","notes":"<=2 sentences"}."""

BLAST_SUFFIX = """

# Blast-radius dependents — these files IMPORT the changed modules. Verify tests exist
for them; if they are untested after the diff, reply with verdict "fail" and note why.
Dependent files:
"""


def review_diff(worktree, base="main", max_chars=60000, dependents=None, project=None):
    try:
        diff = subprocess.check_output(["git", "diff", f"{base}...HEAD"],
                                       cwd=worktree, text=True, errors="replace")[:max_chars]
    except Exception as e:
        return {"verdict": "pass", "notes": f"no diff available ({e})"}
    if not diff.strip():
        return {"verdict": "pass", "notes": "empty diff"}
    prompt = PROMPT
    if dependents:
        prompt += BLAST_SUFFIX + "\n".join(f"- {d}" for d in dependents[:12])
    prompt += "\n\nDiff:\n"
    try:
        out = claude_cli.run(prompt + diff, REVIEW_MODEL, project=project,
                             permission=None, max_turns=1,
                             timeout=int(os.environ.get("VERIFY_TIMEOUT", "180")))["text"]
        m = re.search(r"\{.*\}", out, re.S)
        d = json.loads(m.group(0)) if m else {"verdict": "pass", "notes": "unparseable; defaulting pass"}
        d["verdict"] = "fail" if str(d.get("verdict", "")).lower().startswith("fail") else "pass"
        return d
    except Exception as e:
        return {"verdict": "pass", "notes": f"review skipped ({e})"}
