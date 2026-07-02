#!/usr/bin/env python3
"""
business_radar.py - catch business-model-altering work BEFORE it's built, not as a late legal gate.
Scans QUEUED task prompts for signals that a change would alter PRICING, DATA USE, or REGULATORY
posture, and surfaces an early decision card so you rule on direction up front (cheaper than building
then blocking). Keyword pre-filter (free) -> cheap-model confirm only on hits (costless-first).

Tags: pricing | data_use | regulatory. Files ONE decision card per flagged task (deduped via radar_tag
already-set). Schedule every ~15 min.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SIGNALS = {
    "pricing": re.compile(r"\b(pricing|price|paywall|subscription tier|billing plan|charge|monetiz|"
                          r"upsell|discount|free tier|usage.?based|per-seat)\b", re.I),
    "data_use": re.compile(r"\b(share .*data|sell .*data|third.?party|export .*user|pii|personal data|"
                           r"tracking|analytics vendor|data retention|cross-app .*customer)\b", re.I),
    "regulatory": re.compile(r"\b(kyc|aml|money transmission|securities|lending|insurance|reinsur|"
                             r"derivativ|hipaa|gdpr|ccpa|license|regulat|custod|deposit)\b", re.I),
}


def _classify(text):
    hits = [tag for tag, rx in SIGNALS.items() if rx.search(text or "")]
    return hits


def run(limit=300):
    tasks = db.select("tasks", {"select": "id,slug,prompt,project_id,state", "state": "eq.QUEUED",
                                "limit": str(limit)}) or []
    projs = {p["id"]: p.get("name") for p in (db.select("projects", {"select": "id,name"}) or [])}
    # avoid duplicate radar cards
    existing = {(r.get("project"), r.get("radar_tag")) for r in
                (db.select("approvals", {"select": "project,radar_tag", "status": "eq.pending",
                                         "radar_tag": "not.is.null"}) or [])}
    flagged = 0
    for t in tasks:
        hits = _classify(t.get("prompt"))
        if not hits:
            continue
        name = projs.get(t.get("project_id"), "?")
        for tag in hits:
            if (name, tag) in existing:
                continue
            db.insert("approvals", {"project": name, "kind": "material", "radar_tag": tag,
                "title": f"Business-model check ({tag}): {t.get('slug')}",
                "why": f"Queued work may change {tag.replace('_',' ')} for {name}. Decide the direction "
                       f"before it's built. Task: {(t.get('prompt') or '')[:200]}",
                "value": "Rule on business-model direction up front (cheaper than build-then-block).",
                "risk": "This alters how the business operates; your call.", "command": ""})
            existing.add((name, tag))
            flagged += 1
    print(f"business_radar: flagged {flagged} early business-model decisions")
    return flagged


if __name__ == "__main__":
    run()
