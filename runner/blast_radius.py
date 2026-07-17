#!/usr/bin/env python3
"""
blast_radius.py - before/while changing code, compute what a change could break by finding
the files that import/depend on the ones being touched, and tell the agent to add targeted
tests for that radius. Safer autonomous merges.

note_for_task(repo, prompt)  - heuristic: which modules the task targets + their dependents.
radius_after(repo, base)     - exact dependents of the files actually changed in the diff.
"""
import os, sys, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_retrieval as cr


def _dependents(repo, files):
    deps = set()
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        if len(stem) < 3:
            continue
        try:
            r = subprocess.run(["rg", "-l", rf"(import|require|from).*{re.escape(stem)}"],
                               cwd=repo, capture_output=True, text=True, timeout=20)
            for d in r.stdout.splitlines():
                if d and d not in files:
                    deps.add(d)
        except Exception:
            pass
    return sorted(deps)


def radius_after(repo, base="main"):
    try:
        changed = subprocess.check_output(["git", "diff", "--name-only", f"{base}...HEAD"],
                                          cwd=repo, text=True, timeout=30).split()
    except Exception:
        changed = []
    return {"changed": changed, "dependents": _dependents(repo, changed)}


def note_for_task(repo, prompt):
    targets = cr.select_files(repo, prompt)[:6]
    deps = _dependents(repo, targets)
    if not deps:
        return ""
    return ("# Blast radius: these files depend on what you're likely changing - keep them "
            "working and ADD/UPDATE tests covering them:\n" +
            "\n".join(f"- {d}" for d in deps[:12]) + "\n\n")


if __name__ == "__main__":
    print(radius_after(sys.argv[1] if len(sys.argv) > 1 else "."))
