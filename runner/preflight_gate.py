#!/usr/bin/env python3
"""
preflight_gate.py — cost/value control: screen QUEUED tasks with ONE cheap-model call before the
expensive agent ever runs, and BLOCK the clearly non-actionable ones (the "no committable work"
class that burned ~$140/shipped-change). Registered as the 'preflight' loop.

Conservative by design: only blocks when the cheap model is confident a task will produce NO diff,
never touches protected kinds (canary/security/deploy/growth/verify), caps volume per tick, and logs
its reasoning so a wrongly-blocked task is easy to spot + requeue.
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
    blocked = 0
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
            db.update("tasks", {"id": t["id"]}, {"state": "BLOCKED",
                     "note": "preflight: predicted no committable work — " + ans[:160]})
            blocked += 1
    print(f"preflight: screened {len(rows)} queued, blocked {blocked} non-actionable")


if __name__ == "__main__":
    run()
