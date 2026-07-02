#!/usr/bin/env python3
"""
inbox_apply.py - two-way email approvals. Parses reply commands like:
    approve 3f9a1c2b        reject 8c1d...        done 44be2a01        run 44be2a01
and applies them to the approvals queue (single approval = final). IDs may be the first 8+ chars of the
approval uuid (as shown in the digest). Used by the email-reply scheduled task, which fetches the reply
text from Gmail and calls apply_text(). Also callable directly for testing.

SAFETY: only acts on approvals that are still pending; 'run' only queues an executable+safe operator step
(the runner re-validates the allowlist). Never approves anything not already in the queue.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

CMD = re.compile(r"\b(approve|reject|deny|done|run|not\s*needed)\b[:\s]+([0-9a-f]{6,36})", re.I)
ACTION = {"approve": ("approved", None), "done": ("approved", None), "reject": ("denied", None),
          "deny": ("denied", None), "not needed": ("denied", None), "notneeded": ("denied", None)}


def _find(idfrag):
    rows = db.select("approvals", {"select": "id,status,kind,draft_cmd,executable",
                                   "status": "eq.pending", "limit": "500"}) or []
    idfrag = idfrag.lower()
    for r in rows:
        if str(r["id"]).lower().startswith(idfrag) or str(r["id"]).lower().replace("-", "").startswith(idfrag):
            return r
    return None


def apply_text(text):
    """Parse every command in a reply body and apply. Returns a list of results."""
    results = []
    for m in CMD.finditer(text or ""):
        verb = m.group(1).lower().replace(" ", ""); idfrag = m.group(2)
        a = _find(idfrag)
        if not a:
            results.append(f"{verb} {idfrag}: not found / already decided"); continue
        if verb == "run":
            cmd = (a.get("draft_cmd") or "").strip()
            if a.get("executable") and cmd:
                db.insert("action_runs", {"approval_id": a["id"], "cmd": cmd,
                          "requested_by": "email", "status": "queued"})
                db.update("approvals", {"id": a["id"]}, {"exec_status": "queued"})
                results.append(f"run {idfrag}: queued")
            else:
                results.append(f"run {idfrag}: not auto-runnable — do it manually")
            continue
        status, _ = ACTION.get(verb, (None, None))
        if not status:
            continue
        db.update("approvals", {"id": a["id"]},
                  {"status": status, "decided_by": "email", "decided_at": "now()"})
        results.append(f"{verb} {idfrag}: {status}")
    return results


if __name__ == "__main__":
    import json
    print(json.dumps(apply_text(sys.stdin.read()), indent=2))
