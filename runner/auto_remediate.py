#!/usr/bin/env python3
"""
auto_remediate.py - drive BLOCKED to zero, autonomously. Every BLOCKED task is classified and remediated
so it flows back toward shipped/merged, existing AND future — no task lingers stuck.

Remediation by cause (tasks.remediation_count changes strategy; it does not punt to manual review):
  * transient (network/budget/rate/overload)  -> requeue as-is (retry_policy handles the detail).
  * conflict                                    -> requeue to rebuild on fresh base (merge fix + staging).
  * no-op / "changed nothing" / agent failed    -> requeue with a SHARPER prompt (inject the failure note)
                                                   and ESCALATE the model one tier so the retry is smarter.
  * verify / judge / quality reject             -> requeue with the reviewer's notes injected so the agent
                                                   fixes the specific issue on the next attempt.
  * legal / material                            -> leave for the human (surfaced with a decision brief).
  * over the remediation cap                    -> reclaim as implementation work with a smaller,
                                                   explicit prompt; do not create manual-review backlog.
  * old cap-review cards / no-op auto-closures  -> recover and put the task back in the queue.

Runs every couple minutes; also callable. This is the "self-remedy everything" loop.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import legal_filter
import pipeline_contract

CAP = int(os.environ.get("REMEDIATION_CAP", "3"))
# HARD TERMINAL CAP: a task remediated this many times without ever merging is almost certainly
# mis-scoped or impossible. Every branch below used to re-queue it, so no-op / empty-diff tasks
# recycled FOREVER — burning fleet lanes and sinking merge throughput. At the hard cap we SHELVE it
# (terminal state nothing re-picks) with a clear note, so a human can re-scope it instead.
HARD_CAP = int(os.environ.get("REMEDIATION_HARD_CAP", "6"))
MAX_REMEDIATION_PROMPT_CHARS = int(os.environ.get("ORCH_MAX_REMEDIATION_PROMPT_CHARS", "16000"))
RECOVERY_MARK = "auto-remediate:reclaimed-20260703"
DIRECTIVE_MARKER = "AUTO-REMEDIATION DIRECTIVE"
_BUDGET = re.compile(r"budget cap|call cap|hourly \$ cap|daily \$ cap|cost circuit", re.I)
_TRANSIENT = re.compile(r"budget cap|connection reset|urlopen|errno|timeout|overload|503|high demand|rate.?limit", re.I)
_NOOP = re.compile(r"no committable|changed nothing|no file changes|agent run failed", re.I)
_REVIEW = re.compile(r"verify:|judge:|quality gate", re.I)
_CONFLICT = re.compile(r"conflict", re.I)
_MISSING_BRANCH = re.compile(r"branch.*missing|no longer exists|approved.*agent/", re.I)
_HUMAN = re.compile(r"credential needed|missing credential|auth failure|secret|api key|two-key", re.I)
_CAP_CARD = re.compile(r"blocked after \d+ auto-fixes|can't self-revise|needs a look:|re-scope needed", re.I)
_PARKED = re.compile(r"ev-parked|near-zero expected value|preflight: predicted no committable|permission denial|tool use", re.I)
_MAX_TURNS = re.compile(r"max_turns|maximum number of turns|reached.*turn.*limit", re.I)
_TOO_LONG = re.compile(r"prompt is too long|context.*limit|single-exchange conversation cannot be compacted", re.I)
_READY_UNCOMMITTED = re.compile(r"ready to commit|git commit|changes are safe|implementation is complete", re.I)
_QUOTED_SLUG = re.compile(r"'([^']+)'")


def run(limit=120):
    """Anti-burn remediation. NEVER blindly re-run the same failing task into a credit loop:
      attempt 1  : one smart retry (transient/conflict) or escalate+sharpen (review/no-op).
      attempt 2  : RE-PLAN - a cheap model fully revises the task prompt to be concrete + achievable
                   from the failure; a persistent no-op is reclaimed with a direct implementation prompt.
      attempt >=CAP or a repeat of the SAME failure signature -> reclaim with a full-implementation
                   prompt and keep it moving, except genuine legal/material gates.
    """
    recovered_cards = recover_pending_manual_reviews()
    restored_noops = recover_auto_closed_noops()
    blocked = db.select("tasks", {"select": "id,slug,prompt,note,remediation_count,model,project_id,material,log_tail,state",
                                  "state": "in.(BLOCKED,CONFLICT,TESTFAIL)", "limit": str(limit)}) or []
    requeued = escalated = revised = reclaimed = left = shelved = 0
    for t in blocked:
        note = t.get("note") or ""
        signal = f"{note}\n{t.get('log_tail') or ''}"
        rc = int(t.get("remediation_count") or 0)

        # HARD TERMINAL CAP: stop burning lanes on a task that has been remediated past the hard cap
        # without ever merging. Legal/material holds still route to the human path below, but everything
        # else is SHELVED (terminal — the claim loop and this remediator both ignore SHELVED) so it
        # surfaces in the cockpit for a re-scope instead of recycling indefinitely.
        if rc >= HARD_CAP and not _requires_human_hold(t, signal):
            db.update("tasks", {"id": t["id"]},
                      {"state": "SHELVED", "account": None, "updated_at": "now()",
                       "note": (f"shelved after {rc} remediations without merge — needs human re-scope. "
                                + note)[:500]})
            shelved += 1
            continue

        upd = {"state": "QUEUED", "remediation_count": rc + 1, "account": None, "updated_at": "now()"}

        if _MAX_TURNS.search(signal):
            if rc < CAP:
                upd["note"] = f"auto-remediate: retry after max_turns limit ({rc + 1}/{CAP})"
                requeued += 1
            else:
                upd["prompt"] = _implementation_prompt(t, signal, "Agent hit turn limit repeatedly; implement with focused, direct approach avoiding excessive tool use.")
                upd["model"] = _escalate(_escalate(t.get("model")))
                upd["note"] = f"auto-remediate: cap reached on max_turns; implement focused approach ({rc + 1})"
                reclaimed += 1
            db.update("tasks", {"id": t["id"]}, upd)
            continue

        if _TOO_LONG.search(signal):
            upd["prompt"] = _implementation_prompt(t, signal, "Previous prompt exceeded the model context limit; use this compacted instruction and inspect files directly.")
            upd["model"] = _escalate(t.get("model"))
            upd["note"] = f"auto-remediate: compacted overlong prompt ({rc + 1})"
            db.update("tasks", {"id": t["id"]}, upd)
            reclaimed += 1
            continue

        if _PARKED.search(signal):
            upd["prompt"] = _implementation_prompt(t, signal, "This was incorrectly parked as non-actionable; implement the smallest concrete useful improvement now.")
            upd["model"] = _escalate(_escalate(t.get("model")))
            upd["note"] = f"auto-remediate: unparked for implementation ({rc + 1})"
            db.update("tasks", {"id": t["id"]}, upd)
            reclaimed += 1
            continue

        if _CONFLICT.search(signal):
            upd["prompt"] = _implementation_prompt(t, signal, "Recover from the merge/build conflict on a fresh branch and complete the implementation.")
            upd["model"] = _escalate(_escalate(t.get("model")))
            upd["note"] = f"auto-remediate: conflict recovery queued ({rc + 1})"
            db.update("tasks", {"id": t["id"]}, upd)
            requeued += 1
            continue

        if _BUDGET.search(signal):
            upd["remediation_count"] = 0
            upd["note"] = "auto-remediate: budget guard converted to subscription/failover route"
            db.update("tasks", {"id": t["id"]}, upd)
            requeued += 1
            continue

        if _requires_human_hold(t, signal):
            left += 1
            continue

        # A repeated no-op means the instruction was too vague or context was lost. Keep it in the cue
        # with an explicit implementation directive instead of marking it DONE.
        if (_NOOP.search(signal) and rc >= 1) or _READY_UNCOMMITTED.search(signal):
            upd["prompt"] = _implementation_prompt(t, signal, "The prior run found/created work but did not leave a committable branch. Verify the diff, commit it, and let merge train integrate it.")
            upd["model"] = _escalate(_escalate(t.get("model")))
            upd["note"] = f"auto-remediate: reclaimed no-op; implement fully ({rc + 1})"
            db.update("tasks", {"id": t["id"]}, upd)
            reclaimed += 1
            continue

        if rc >= CAP:
            upd["prompt"] = _implementation_prompt(t, note, f"Remediation cap {CAP} reached; finish the implementation instead of escalating to manual review.")
            upd["model"] = _escalate(_escalate(t.get("model")))
            upd["note"] = f"auto-remediate: cap reached; reclaimed for full implementation ({rc + 1})"
            db.update("tasks", {"id": t["id"]}, upd)
            reclaimed += 1
            continue

        if rc == 0 and (_TRANSIENT.search(signal) or _CONFLICT.search(signal) or _MISSING_BRANCH.search(signal)):
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
                upd["prompt"] = _implementation_prompt(t, note, "Planner could not rewrite this; implement the smallest useful fix directly.")
                upd["model"] = _escalate(_escalate(t.get("model")))
                upd["note"] = f"auto-remediate: fallback implementation prompt ({rc + 1})"
                reclaimed += 1
        db.update("tasks", {"id": t["id"]}, upd)
    print(f"auto_remediate: retry {requeued}, escalate {escalated}, re-plan {revised}, "
          f"reclaimed {reclaimed}, shelved {shelved}, recovered-cards {recovered_cards}, "
          f"restored-noops {restored_noops}, left {left}")
    return {"requeued": requeued, "escalated": escalated, "revised": revised,
            "reclaimed": reclaimed, "shelved": shelved, "recovered_cards": recovered_cards,
            "restored_noops": restored_noops, "left": left}


def recover_pending_manual_reviews(limit=500):
    """Convert old 'blocked after N auto-fixes' cards back into executable work."""
    cards = db.select("approvals", {"select": "*", "status": "eq.pending",
                                    "order": "created_at.asc", "limit": str(limit)}) or []
    recovered = 0
    for card in cards:
        text = " ".join(str(card.get(k) or "") for k in ("title", "why", "detail"))
        if not _CAP_CARD.search(text):
            continue
        slug = _slug_from_card(card)
        if not slug:
            continue
        tasks = db.select("tasks", {"select": "*", "slug": f"eq.{slug}", "limit": "5"}) or []
        task = tasks[0] if tasks else _create_task_from_card(card, slug)
        if not task:
            continue
        state = task.get("state")
        if state in ("QUEUED", "RUNNING", "RETRY", "MERGING"):
            _close_review_card(card, "task already active")
            recovered += 1
            continue
        note = task.get("note") or card.get("why") or text
        if state == "MERGED" or (state == "DONE" and "auto-closed: no committable" not in note.lower()):
            _close_review_card(card, f"task already {state}")
            recovered += 1
            continue
        patch = {"state": "QUEUED", "account": None, "updated_at": "now()",
                 "remediation_count": 0,
                 "prompt": _implementation_prompt(task, note, "Recovered from stale manual-review card; implement now."),
                 "model": _escalate(_escalate(task.get("model"))),
                 "note": "auto-remediate: reclaimed pending manual review; implementing fully"}
        db.update("tasks", {"id": task["id"]}, patch)
        _close_review_card(card, "requeued matching task for implementation")
        recovered += 1
    return recovered


def recover_auto_closed_noops(limit=500):
    """Put tasks that were incorrectly marked DONE for no-op retries back into the cue."""
    rows = db.select("tasks", {"select": "id,slug,prompt,note,remediation_count,model,project_id,material,log_tail",
                               "state": "eq.DONE", "limit": str(limit)}) or []
    restored = 0
    for task in rows:
        note = task.get("note") or ""
        if "auto-closed: no committable" not in note.lower():
            continue
        if _requires_human_hold(task, note):
            continue
        rc = int(task.get("remediation_count") or 0)
        # Don't let the no-op restore dodge the hard cap by resetting the counter: a task that has
        # already been remediated past the hard cap is SHELVED for human re-scope, not restored again.
        if rc >= HARD_CAP:
            db.update("tasks", {"id": task["id"]},
                      {"state": "SHELVED", "account": None, "updated_at": "now()",
                       "note": (f"shelved after {rc} remediations (repeat no-op) — needs human re-scope. "
                                + note)[:500]})
            continue
        # Preserve (increment) the counter across restores so repeat no-ops converge to the hard cap.
        db.update("tasks", {"id": task["id"]},
                  {"state": "QUEUED", "account": None, "updated_at": "now()",
                   "remediation_count": rc + 1,
                   "prompt": _implementation_prompt(task, note, "This was incorrectly removed from the cue; implement the underlying work."),
                   "model": _escalate(_escalate(task.get("model"))),
                   "note": "auto-remediate: restored incorrectly auto-closed no-op task"})
        restored += 1
    return restored


def _slug_from_card(card):
    if card.get("slug"):
        return card["slug"]
    text = " ".join(str(card.get(k) or "") for k in ("title", "why", "detail"))
    m = _QUOTED_SLUG.search(text)
    return m.group(1) if m else None


def _project_id(name):
    if not name:
        return None
    rows = db.select("projects", {"select": "id", "name": f"eq.{name}", "limit": "1"}) or []
    return rows[0]["id"] if rows else None


def _create_task_from_card(card, slug):
    pid = _project_id(card.get("project"))
    if not pid:
        return None
    prompt = _implementation_prompt({"slug": slug, "prompt": ""}, card.get("why") or card.get("title") or "",
                                    "Original task row was missing; reconstruct from the recovery card.")
    rows = db.insert("tasks", {"project_id": pid, "slug": slug, "state": "QUEUED", "kind": "build",
                               "prompt": prompt, "note": "auto-remediate: reconstructed from stale review card"})
    return rows[0] if rows else None


def _close_review_card(card, reason):
    db.update("approvals", {"id": card["id"]},
              {"status": "approved", "decided_by": RECOVERY_MARK,
               "decision_type": "approve",
               "decision_text": f"Auto-reclaimed: {reason}. Work is back in the task queue."})


def _requires_human_hold(task, note):
    text = " ".join(str(task.get(k) or "") for k in ("slug", "prompt", "log_tail")) + " " + str(note or "")
    if _HUMAN.search(text):
        return True
    return legal_filter.requires_owner_approval(text=text)


def _implementation_prompt(task, note, directive):
    raw = task.get("prompt") or f"Implement the queued task '{task.get('slug')}'."
    base = pipeline_contract.original_request(raw).split(DIRECTIVE_MARKER, 1)[0].rstrip()
    if len(base) > MAX_REMEDIATION_PROMPT_CHARS:
        keep_tail = MAX_REMEDIATION_PROMPT_CHARS - 4000
        base = (
            base[:4000].rstrip() +
            "\n\n[auto-remediate compaction: omitted bulky middle transcript/context. "
            "Continue from the concrete task summary and inspect files directly.]\n\n" +
            base[-keep_tail:].lstrip()
        )
    return (base +
            f"\n\n{DIRECTIVE_MARKER}\n"
            f"{directive}\n"
            f"Failure context: {(note or '')[:800]}\n"
            "Do not stop at analysis or manual review. Make the smallest complete code change, "
            "restore any missing/deleted branch or worktree artifacts if needed, run the relevant checks, "
            "and commit the implementation.")


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
