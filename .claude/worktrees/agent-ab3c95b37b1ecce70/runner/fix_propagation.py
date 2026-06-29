#!/usr/bin/env python3
"""
fix_propagation.py - one fix protects the whole fleet. Given a bug PATTERN (regex) and a
lesson, scan every registered repo for the same pattern and file a remediation proposal
(or queue a fix task) for each repo that still has it. Turns a single fix into fleet-wide
coverage - exactly what you'd want for the fail-open-allowlist / committed-secret classes.

Usage:
  python3 fix_propagation.py --pattern 'allowlist.*\\|\\| true' --lesson 'fail-open allowlist' [--queue]
  python3 fix_propagation.py --preset fail_open_allowlist
"""
import os, sys, subprocess, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PRESETS = {
    "fail_open_allowlist": (r"(allow|permit).{0,30}(\|\|\s*true|return\s+true)", "fail-open allowlist; make it default-deny"),
    "raw_sql_shell": (r"^\s*(create|alter|drop)\s+(policy|table|function)", "raw SQL likely run in shell; move to a migration"),
    "console_log_secret": (r"(api[_-]?key|secret|token)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}", "possible hardcoded secret"),
}


def repos():
    return db.select("projects", {"select": "name,repo_path"}) or []


def scan(pattern, lesson, queue=False):
    hits = []
    for p in repos():
        repo = p["repo_path"]
        if not os.path.isdir(repo):
            continue
        try:
            r = subprocess.run(["rg", "-l", "--pcre2", pattern], cwd=repo,
                               capture_output=True, text=True, timeout=30)
            files = [f for f in r.stdout.splitlines() if f]
        except Exception:
            files = []
        if not files:
            continue
        hits.append({"project": p["name"], "files": files})
        detail = "Found in:\n" + "\n".join(files[:20])
        if queue:
            proj = db.select("projects", {"select": "id", "name": f"eq.{p['name']}"})[0]
            db.insert("tasks", {"project_id": proj["id"], "slug": "fixprop-" + lesson[:20].replace(" ", "-"),
                                "prompt": f"Fix this fleet-wide issue: {lesson}. Affected files:\n{detail}\nApply the fix and add a regression test.",
                                "kind": "build", "state": "QUEUED"})
        else:
            db.insert("approvals", {"project": p["name"], "kind": "proposal",
                                    "title": f"Fleet-wide fix: {lesson} ({len(files)} files)",
                                    "why": f"Same pattern '{pattern}' found in {p['name']}.",
                                    "value": "Closes a bug class across the fleet.",
                                    "risk": "Review the matched files before applying.", "detail": detail})
    print(f"propagation: {sum(len(h['files']) for h in hits)} matches across {len(hits)} repos")
    return hits


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern"); ap.add_argument("--lesson", default="bug pattern")
    ap.add_argument("--preset"); ap.add_argument("--queue", action="store_true")
    a = ap.parse_args()
    if a.preset:
        pat, les = PRESETS[a.preset]; scan(pat, les, a.queue)
    elif a.pattern:
        scan(a.pattern, a.lesson, a.queue)
    else:
        print("presets:", ", ".join(PRESETS))
