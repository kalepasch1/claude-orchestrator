#!/usr/bin/env python3
"""
auto_remediate.py - drive BLOCKED to zero, autonomously. Every BLOCKED task is classified and remediated
so it flows back toward shipped/merged, existing AND future — no task lingers stuck.

Remediation by cause (capped by tasks.remediation_count to avoid infinite loops):
  * transient (network/budget/rate/overload)  -> requeue as-is (retry_policy handles the detail).
  * conflict                                    -> requeue to rebuild on fresh base (merge fix + staging).
  * no-op / "changed nothing" / agent failed    -> requeue with a SHARPER prompt (inject the failure note)
                                                   and ESCALATE the model one tier so the retry is smarter.
  * verify / judge / quality reject             -> requeue with the reviewer's notes injected so the agent
                                                   fixes the specific issue on the next attempt.
  * legal / material                            -> leave for the human (surfaced with a decision brief).
  * over the remediation cap                    -> stop retrying; file ONE concise human card with the
                                                   full history so it's a quick decision, not a mystery.

Runs every couple minutes; also callable. This is the "self-remedy everything" loop.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

CAP = int(os.environ.get("REMEDIATION_CAP", "3"))
_TRANSIENT = re.compile(r"budget cap|connection reset|urlopen|errno|timeout|overload|503|high demand|rate.?limit", re.I)
_NOOP = re.compile(r"no committable|changed nothing|no file changes|agent run failed", re.I)
_REVIEW = re.compile(r"verify:|judge:|quality gate", re.I)
_CONFLICT = re.compile(r"conflict", re.I)
_HUMAN = re.compile(r"legal|counsel|awaiting.*approval|two-key", re.I)


def run(limit=120):
    """Anti-burn remediation. NEVER blindly re-run the same failing task into a credit loop:
      attempt 1  : one smart retry (transient/conflict) or escalate+sharpen (review/no-op).
      attempt 2  : RE-PLAN — a cheap model fully REVISES the task prompt to be concrete + achievable
                   from the failure; a persistent NO-OP is auto-CLOSED (nothing to build), not retried.
      attempt >=CAP or a repeat of the SAME failure signature -> stop, file a human card. No more spend.
    """
    blocked = db.select("tasks", {"select": "id,slug,prompt,note,remediation_count,model,project_id,material,log_tail",
                                  "state": "eq.BLOCKED", "limit": str(limit)}) or []
    requeued = escalated = revised = closed = human = left = 0
    for t in blocked:
        note = t.get("note") or ""
        rc = int(t.get("remediation_count") or 0)
        if t.get("material") or _HUMAN.search(note):
            left += 1
            continue

        # HARD ANTI-BURN: a task that has produced NO commit and no-op'd more than once is genuinely
        # nothing to build -> CLOSE it (don't keep paying to re-discover there's nothing to do).
        if _NOOP.search(note) and rc >= 1:
            db.update("tasks", {"id": t["id"]}, {"state": "DONE",
                      "note": "auto-closed: no committable work after retry (not a real task)"})
            closed += 1
            continue

        if rc >= CAP:
            db.insert("approvals", {"project": None, "kind": "self",
                      "title": f"Needs a look: '{t['slug']}' blocked after {CAP} auto-fixes",
                      "why": f"Last error: {note[:200]}. Auto-remediation exhausted — re-scope or cancel.",
                      "value": "Unblock or drop this task.", "risk": "Low.", "command": ""})
            db.update("tasks", {"id": t["id"]}, {"note": note + " [remediation cap reached]"})
            human += 1
            continue

        upd = {"state": "QUEUED", "remediation_count": rc + 1, "account": None, "updated_at": "now()"}
        if rc == 0 and (_TRANSIENT.search(note) or _CONFLICT.search(note)):
            upd["note"] = f"auto-remediate: retry (1/{CAP}) — {note[:70]}"
            requeued += 1
        elif rc == 0:
            # first real failure -> escalate model + sharpen with the specific reason
            upd["prompt"] = ((t.get("prompt") or "") +
                             f"\n\nPRIOR ATTEMPT FAILED — address specifically: {note[:250]}\n"
                             f"Make a concrete, tested change and COMMIT it; do not return with no edits.")
            upd["model"] = _escalate(t.get("model"))
            upd["note"] = f"auto-remediate: escalate+sharpen (1/{CAP})"
            escalated += 1
        else:
            # 2nd+ failure -> RE-PLAN the task from scratch instead of burning another blind retry
            new_prompt = _revise(t, note)
            if new_prompt:
                upd["prompt"] = new_prompt
                upd["note"] = f"auto-remediate: re-planned (2/{CAP})"
                revised += 1
            else:
                # couldn't revise -> stop, hand to human (don't loop)
                db.insert("approvals", {"project": None, "kind": "self",
                          "title": f"Re-scope needed: '{t['slug']}' can't self-revise",
                          "why": f"Failing repeatedly: {note[:200]}.", "value": "Re-scope or drop.",
                          "risk": "Low.", "command": ""})
                db.update("tasks", {"id": t["id"]}, {"note": note + " [needs human re-scope]"})
                human += 1
                continue
        db.update("tasks", {"id": t["id"]}, upd)
    print(f"auto_remediate: retry {requeued}, escalate {escalated}, re-plan {revised}, "
          f"closed-noop {closed}, human {human}, left {left}")
    return {"requeued": requeued, "escalated": escalated, "revised": revised, "closed": closed, "human": human}


def _revise(task, note):
    """Fully rewrite a repeatedly-failing task's prompt to be concrete + achievable (cheap model)."""
    prompt = ("A build task keeps failing. Rewrite it into a SHARPER, SMALLER, unambiguous instruction "
              "that a coding agent can complete in one pass: exact files/scope, a concrete acceptance "
              "test, and no vague goals. If the task is genuinely not doable or is a no-op, reply with "
              "exactly 'DROP'.\n"
              f"TASK: {(task.get('prompt') or '')[:1200]}\nFAILURE: {note[:400]}\n"
              f"LOG: {(task.get('log_tail') or '')[:600]}\nRewritten task:")
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose("plan", agentic=False)
        r = model_gateway.complete(prov, model, prompt)
        txt = (r.get("text") or "").strip()
        if not txt or txt.upper().startswith("DROP") or len(txt) < 20:
            return None
        return txt[:4000]
    except Exception:
        return None


def _escalate(model):
    order = ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-8"]
    try:
        i = order.index(model)
        return order[min(i + 1, len(order) - 1)]
    except ValueError:
        return "claude-sonnet-4-6"


if __name__ == "__main__":
    run()
