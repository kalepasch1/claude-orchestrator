#!/usr/bin/env python3
"""
legal_triage.py - reserve your attention for genuinely novel legal exposure. A cheap model classifies
each pending legal card into routine | elevated | novel:
  routine  - standard, well-trodden (e.g. a normal ToS/privacy update, boilerplate DPA) -> AUTO-APPROVE
             with the brief attached, so it clears itself.
  elevated - non-trivial but common (e.g. a new data-sharing partner) -> stays for a quick look.
  novel    - genuine new exposure (new regulated activity, securities, money transmission, licensing)
             -> stays, flagged clearly for counsel.
Conservative: anything matching hard-regulatory keywords is FORCED to novel regardless of the model, so
we never auto-clear real regulatory decisions. Schedule every few minutes. Costless-first.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import legal_filter

AUTO_APPROVE = os.environ.get("LEGAL_AUTO_APPROVE_ROUTINE", "true").lower() == "true"
# Cap on the backlog probe: enough to answer "is the queue still deep", reported as
# ">= N" rather than pretending to be an exact count of a table we will not scan.
BACKLOG_PROBE = int(os.environ.get("LEGAL_TRIAGE_BACKLOG_PROBE", "500"))

PROMPT = """Classify this decision's legal risk for a solo founder as exactly one word: routine,
elevated, or novel. routine = standard/boilerplate that founders normally self-approve. elevated =
worth a quick look. novel = genuinely new legal exposure needing counsel. Reply with ONLY the word.
ITEM: {title}
DETAIL: {why}"""


def _pending_backlog():
    """How many unclassified legal cards remain after this pass. Best effort.

    A queue that cannot keep up should say so rather than print a busy-looking zero.
    """
    try:
        rows = db.select("approvals", {"select": "id", "status": "eq.pending", "kind": "eq.legal",
                                       "legal_risk_level": "is.null",
                                       "limit": str(BACKLOG_PROBE)}) or []
    except Exception:
        return None
    return len(rows)


def run(limit=40):
    """Classify pending legal cards, oldest first.

    THE UNCLASSIFIED FILTER BELONGS IN THE QUERY, NOT THE LOOP. This used to select
    `limit` pending legal cards in server-chosen order and then `continue` past any that
    already had a legal_risk_level. Elevated and novel cards stay pending on purpose —
    that is the whole point of the triage — so they accumulate, and they are exactly the
    rows that are already classified. Once `limit` of them can fill the page, every run
    fetched 40 already-done cards, skipped all 40, classified nothing, and printed
    "classified 0" while genuinely new cards sat unreachable behind them. The job looked
    healthy on a 300s interval and did no work.

    Ordering ascending makes it a FIFO drain, so the oldest unclassified card is always
    reachable and nothing can be starved indefinitely.
    """
    rows = db.select("approvals", {"select": "id,title,why,legal_risk_level", "status": "eq.pending",
                                   "kind": "eq.legal", "legal_risk_level": "is.null",
                                   "order": "created_at.asc", "limit": str(limit)}) or []
    tagged = cleared = 0
    failed = []
    for a in rows:
        if a.get("legal_risk_level"):
            continue
        blob = (a.get("title") or "") + " " + (a.get("why") or "")
        if legal_filter.requires_owner_approval(a, text=blob, kind="legal"):
            level = "novel"
        else:
            try:
                import model_policy, model_gateway
                prov, model, _ = model_policy.choose("review", agentic=False)
                r = model_gateway.complete(prov, model,
                        PROMPT.replace("{title}", (a.get("title") or "")[:300]).replace("{why}", (a.get("why") or "")[:600]))
                t = (r.get("text") or "").strip().lower()
                level = "routine" if "routine" in t else ("novel" if "novel" in t else "elevated")
            except Exception:
                level = "elevated"
        upd = {"legal_risk_level": level}
        if level == "routine" and AUTO_APPROVE:
            upd.update({"status": "approved", "decided_by": "legal-triage-routine", "decided_at": "now()"})
        try:
            db.update("approvals", {"id": a["id"]}, upd)
        except Exception as exc:
            # HEAD-OF-LINE HAZARD, and it is the crash loop this recovery is named for.
            # This write was unguarded while every other failure path here degrades, so a
            # single card whose update fails raised straight out of run(), the periodic
            # job died, and the scheduler restarted it 300 seconds later onto the SAME
            # card. Nothing after it was ever reached. Ascending order makes that worse,
            # not better: the poison row is now permanently at the front.
            #
            # Recorded and stepped over, never swallowed silently — a drain that stalls
            # invisibly is the failure mode this whole wave exists to end.
            failed.append((a.get("id"), str(exc)[:120]))
            continue
        if level == "routine" and AUTO_APPROVE:
            cleared += 1
        tagged += 1
    remaining = _pending_backlog()
    print(f"legal_triage: classified {tagged} legal cards, auto-cleared {cleared} routine "
          f"({'ON' if AUTO_APPROVE else 'classify-only; set LEGAL_AUTO_APPROVE_ROUTINE=true to auto-clear'})")
    if failed:
        print(f"legal_triage: {len(failed)} card(s) could not be updated and were skipped: {failed[:5]}")
    if remaining:
        print(f"legal_triage: {'>=' if remaining >= BACKLOG_PROBE else ''}{remaining} unclassified legal card(s) still pending")
    return {"tagged": tagged, "cleared": cleared, "failed": failed, "backlog": remaining}


if __name__ == "__main__":
    run()
