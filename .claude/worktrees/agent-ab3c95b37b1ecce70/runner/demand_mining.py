#!/usr/bin/env python3
"""
demand_mining.py - build what's wanted, not what's guessed. Mines user requests / support
tickets (PII-stripped) across apps to detect demand for a capability BEFORE building it, then
files a proposal. Source is pluggable: a `requests` table (project,text,created_at) or a
newline file via REQUESTS_FILE. Aggregates use differential privacy so no individual leaks.
"""
import os, sys, re, json, subprocess
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, privacy, knowledge as kw

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
MODEL = os.environ.get("DEMAND_MODEL", "claude-haiku-4-5-20251001")
MIN_DEMAND = int(os.environ.get("DEMAND_MIN", "5"))


def _requests():
    f = os.environ.get("REQUESTS_FILE")
    if f and os.path.isfile(f):
        return [{"project": "?", "text": l.strip()} for l in open(f) if l.strip()]
    try:
        return db.select("requests", {"select": "project,text", "limit": "5000"}) or []
    except Exception:
        return []


def run():
    rows = _requests()
    if not rows:
        print("demand_mining: no request source (set REQUESTS_FILE or a 'requests' table)"); return 0
    # scrub + theme by keyword cluster
    themes = Counter()
    samples = {}
    for r in rows:
        clean, _ = privacy.scrub(r.get("text", ""))
        for tok in set(kw.toks(clean)):
            if len(tok) > 4:
                themes[tok] += 1
                samples.setdefault(tok, clean[:140])
    made = 0
    for theme, raw_count in themes.most_common(20):
        count = privacy.dp_count(raw_count)            # privacy-preserving aggregate
        if count < MIN_DEMAND:
            continue
        db.insert("approvals", {"project": "PORTFOLIO", "kind": "proposal",
                                "title": f"Demand signal: '{theme}' ({count}+ requests)",
                                "why": f"Recurring user demand around '{theme}'. e.g. \"{samples.get(theme,'')}\"",
                                "value": "Build a capability for proven demand before competitors.",
                                "risk": "validate the cluster is a real capability, not noise.",
                                "command": ""})
        made += 1
        if made >= 5:
            break
    print(f"demand_mining: filed {made} demand-driven proposals")
    return made


if __name__ == "__main__":
    run()
