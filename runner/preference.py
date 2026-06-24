#!/usr/bin/env python3
"""
preference.py - RLHF-lite. Learns from your approve/deny history to predict whether you'd
approve a new proposal, so the swarm can pre-filter low-value cards to your taste (fewer
interruptions). Keyword/Bayesian now; swap in embeddings later.

score(title, why) -> 0..1 likelihood you approve.  Used to auto-rank/suppress proposals.
"""
import os, sys, math
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, knowledge as kw

SUPPRESS_BELOW = float(os.environ.get("PREF_SUPPRESS_BELOW", "0.25"))


def _history():
    rows = db.select("approvals", {"select": "title,why,kind,status",
                                   "status": "in.(approved,denied)", "limit": "1000"}) or []
    return rows


def _model():
    pos, neg = Counter(), Counter()
    np_, nn = 0, 0
    for r in _history():
        toks = kw.toks(f"{r.get('title','')} {r.get('why','')} {r.get('kind','')}")
        if r["status"] == "approved":
            pos.update(toks); np_ += 1
        else:
            neg.update(toks); nn += 1
    return pos, neg, np_, nn


def score(title, why="", kind=""):
    pos, neg, np_, nn = _model()
    if np_ + nn < 6:
        return 0.6                       # not enough history -> lean approve
    toks = set(kw.toks(f"{title} {why} {kind}"))
    # naive-Bayes-ish log-odds with Laplace smoothing
    lp = math.log((np_ + 1) / (np_ + nn + 2))
    ln = math.log((nn + 1) / (np_ + nn + 2))
    vp, vn = sum(pos.values()) + len(pos), sum(neg.values()) + len(neg)
    for w in toks:
        lp += math.log((pos[w] + 1) / vp)
        ln += math.log((neg[w] + 1) / vn)
    return round(1 / (1 + math.exp(ln - lp)), 3)


def should_suppress(title, why="", kind=""):
    return score(title, why, kind) < SUPPRESS_BELOW


if __name__ == "__main__":
    import sys
    print("approval likelihood:", score(sys.argv[1] if len(sys.argv) > 1 else "add a dark mode toggle"))
