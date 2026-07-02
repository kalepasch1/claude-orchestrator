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

FORCE_NOVEL = re.compile(r"cftc|dcm|sec\b|securities|money transmission|money service|msb|"
                         r"broker.?dealer|reinsur|insurance license|lending license|custod|deposit|"
                         r"derivativ|patent|litigation|regulat|kyc|aml", re.I)
AUTO_APPROVE = os.environ.get("LEGAL_AUTO_APPROVE_ROUTINE", "false").lower() == "true"

PROMPT = """Classify this decision's legal risk for a solo founder as exactly one word: routine,
elevated, or novel. routine = standard/boilerplate that founders normally self-approve. elevated =
worth a quick look. novel = genuinely new legal exposure needing counsel. Reply with ONLY the word.
ITEM: {title}
DETAIL: {why}"""


def run(limit=40):
    rows = db.select("approvals", {"select": "id,title,why,legal_risk_level", "status": "eq.pending",
                                   "kind": "eq.legal", "limit": str(limit)}) or []
    tagged = cleared = 0
    for a in rows:
        if a.get("legal_risk_level"):
            continue
        blob = (a.get("title") or "") + " " + (a.get("why") or "")
        if FORCE_NOVEL.search(blob):
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
            cleared += 1
        db.update("approvals", {"id": a["id"]}, upd)
        tagged += 1
    print(f"legal_triage: classified {tagged} legal cards, auto-cleared {cleared} routine "
          f"({'ON' if AUTO_APPROVE else 'classify-only; set LEGAL_AUTO_APPROVE_ROUTINE=true to auto-clear'})")
    return {"tagged": tagged, "cleared": cleared}


if __name__ == "__main__":
    run()
