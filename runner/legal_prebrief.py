#!/usr/bin/env python3
"""
legal_prebrief.py - make each legal decision take seconds. For every pending legal card without a
pre-brief, a cheap model writes a plain-English brief: what's being decided, the specific risk, the
usual precedent/approach, and a crisp recommendation — so you can decide fast (and know when to call
counsel). Costless-first. Schedule every few minutes. This is decision support, NOT legal advice; the
brief says so.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PROMPT = """Write a concise decision brief (<=120 words) for a solo founder deciding this item. Cover:
(1) what you're actually deciding in one sentence, (2) the specific legal/business risk, (3) the common
precedent or standard approach others take, (4) a one-line recommendation and whether a lawyer is truly
needed. Plain English, no legalese. End with: "Not legal advice — consult counsel for anything binding."
ITEM: {title}
DETAIL: {why}"""


def run(limit=30):
    rows = db.select("approvals", {"select": "id,title,why,prebrief", "status": "eq.pending",
                                   "kind": "eq.legal", "limit": str(limit)}) or []
    done = 0
    for a in rows:
        if a.get("prebrief"):
            continue
        prompt = PROMPT.replace("{title}", (a.get("title") or "")[:300]).replace("{why}", (a.get("why") or "")[:800])
        try:
            import model_policy, model_gateway
            prov, model, _ = model_policy.choose("review", agentic=False)
            r = model_gateway.complete(prov, model, prompt)
            brief = (r.get("text") or "").strip()
        except Exception:
            brief = ""
        if brief:
            db.update("approvals", {"id": a["id"]}, {"prebrief": brief[:2000]})
            done += 1
    print(f"legal_prebrief: briefed {done} legal cards ({len(rows)} scanned)")
    return done


if __name__ == "__main__":
    run()
