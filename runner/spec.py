#!/usr/bin/env python3
"""
spec.py - spec-as-source-of-truth (drift detection). Compares a repo's SPEC.md against the
code and, if they've drifted, files a task to reconcile them (update code to match spec, or
flag the spec for your review). Keeps intent and implementation in sync. Schedule per repo.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, claude_cli

MODEL = os.environ.get("SPEC_MODEL", "claude-sonnet-4-6")

PROMPT = """Read SPEC.md and the codebase. List concrete points where the CODE no longer
matches the SPEC (behavior, endpoints, schema, invariants). If they match, reply exactly
'IN SYNC'. Otherwise list each drift as a bullet."""


def check(repo, project, project_id):
    if not os.path.isfile(os.path.join(repo, "SPEC.md")):
        return None
    try:
        out = claude_cli.run(PROMPT, MODEL, cwd=repo, timeout=200)["text"]
    except Exception:
        return None
    if "IN SYNC" in out.upper():
        return "in sync"
    db.insert("tasks", {"project_id": project_id, "slug": "spec-reconcile", "kind": "build",
                        "state": "QUEUED",
                        "prompt": "SPEC.md and the code have drifted. Reconcile them (prefer updating code "
                                  "to satisfy the spec; if the spec is wrong, file an approval). Drift found:\n" + out[:3000]})
    db.insert("approvals", {"project": project, "kind": "proposal", "title": f"Spec drift in {project}",
                            "why": "Code no longer matches SPEC.md.", "value": "Keeps intent and code in sync.",
                            "detail": out[:3000]})
    return "drift queued"


if __name__ == "__main__":
    print("spec.py: import and call check(repo, project, project_id) from a scheduled job")
