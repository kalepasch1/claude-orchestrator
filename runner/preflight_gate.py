#!/usr/bin/env python3
"""
preflight_gate.py - cost/value control before expensive agentic work.

It never terminally blocks work. If a cheap model thinks a task is vague/no-diff, the task
is rewritten into an explicit implementation directive and left QUEUED so the fleet keeps
moving instead of surfacing "blocked_task" interruptions.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
try:
    import app_triage
except Exception:
    app_triage = None

BATCH = int(os.environ.get("PREFLIGHT_BATCH", "15"))
PROTECT = ("canary-", "sec-rls-", "fix-", "verify-", "rollback-", "rls-", "auto-approve", "deploy")


def _protected(slug):
    s = (slug or "").lower()
    return any(s.startswith(p) or p in s for p in PROTECT)


def run():
    if not app_triage:
        print("preflight: app_triage unavailable; skipping"); return
    rows = db.select("tasks", {"select": "id,slug,prompt", "state": "eq.QUEUED",
                              "order": "created_at.asc", "limit": str(BATCH)}) or []
    sharpened = 0
    for t in rows:
        if _protected(t.get("slug", "")):
            continue
        prompt = (t.get("prompt") or "")[:1500]
        ask = ("You are a build-task triager. Will this task result in an actual committable code/file "
               "change in a repo? Reply strictly 'YES' or 'NO: <short reason>'. Vague, duplicate, "
               "already-done, discussion-only, or under-specified tasks => NO.\n\nTASK:\n" + prompt)
        try:
            r = app_triage.run("orchestrator", "preflight_triage", ask, task_class="rating")
            ans = (r or {}).get("text", "").strip().upper()
        except Exception as e:
            print(f"preflight {t['slug']}: {e}"); continue
        if ans.startswith("NO"):
            revised = ((t.get("prompt") or "").rstrip() +
                       "\n\nPREFLIGHT DIRECTIVE\n"
                       "A cheap preflight model thought this might not produce a concrete diff. "
                       "Do not stop at analysis. Implement the smallest useful code/file change, "
                       "or convert the idea into a specific test/docs/config improvement and commit it.\n"
                       f"Preflight concern: {ans[:220]}")
            db.update("tasks", {"id": t["id"]}, {"prompt": revised,
                     "note": "preflight: sharpened instead of blocked", "updated_at": "now()"})
            sharpened += 1
    print(f"preflight: screened {len(rows)} queued, sharpened {sharpened} non-actionable predictions")


if __name__ == "__main__":
    run()
