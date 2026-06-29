#!/usr/bin/env python3
"""
synthesize_conventions.py - keeps each repo's CLAUDE.md current. A cheap-model agent
reads the repo's structure + key configs and writes/updates CLAUDE.md with the stack,
conventions, test commands, and do/don't rules. That file is the cached context prefix
(see caching.py), so builds get more on-style AND cheaper over time (caching compounds).

Run periodically (e.g. weekly) per project. Writes CLAUDE.md at the repo root.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_cli

MODEL = os.environ.get("CONVENTIONS_MODEL", "claude-haiku-4-5-20251001")

PROMPT = """Read this repository and write/refresh a concise CLAUDE.md at the repo root that a
coding agent should load before any task. Include: tech stack, directory map (1 line each),
the exact test/lint/build commands, naming + style conventions actually used, and a short
DO / DON'T list (include any security rules like default-deny allowlists, no secrets in
code, no raw SQL in the shell). Keep it under ~150 lines and STABLE (don't churn wording -
it is used as a cached prompt prefix). Write the file with your file tools; do not ask."""


def run(repo):
    claude_cli.run(PROMPT, MODEL, cwd=repo, permission="acceptEdits", max_turns=20)
    ok = os.path.isfile(os.path.join(repo, "CLAUDE.md"))
    print(f"{'updated' if ok else 'no'} CLAUDE.md in {repo}")
    return ok


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
