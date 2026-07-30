#!/usr/bin/env python3
"""legal_docket.py — the standing legal/regulatory question set the Consilium debates.

THE PROBLEM THIS FIXES (2026-07-30): the Consilium was only ever fed `improvement_proposals` —
our own engineering backlog. Sampled output was panels named "Legal & Compliance" opining on
Kubernetes. It had never once been pointed at a legal question. Volume looked healthy (100+
opinions); relevance was zero.

WHAT THIS DOES: maintains a durable docket of REAL regulatory questions per vertical, feeds them
to the Consilium continuously, and stores the resulting analysis as a VERDICT CARD — a
pre-computed, citation-backed position with explicit validity conditions.

WHY VERDICT CARDS (the speed requirement): autonomous coding moves faster than deliberation. If
Foulkon had to convene a panel at decision time, guidance would gate the build. Instead the panel
pre-debates the standing question set; at decision time Foulkon LOOKS UP the card (milliseconds)
and runs only a freshness check against the corpus. Target: >90% of steering served from cards.

A card is STALE when any authority in its chain has changed since it was minted — event-driven,
not time-based, so a rule change invalidates exactly the cards it touches and nothing else.
"""
from __future__ import annotations
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

BATCH = int(os.environ.get("LEGAL_DOCKET_BATCH", "6"))

# Seed docket. These are the questions our first two verticals actually get asked — the ones a
# client pays a firm $15-30K to answer. Each becomes a pre-debated, citable verdict card.
# Extend by inserting rows into `legal_docket`; this list only bootstraps an empty table.
SEED_DOCKET = [
    # ── Gaming (launch vertical) ───────────────────────────────────────────────
    ("gaming", "Is a dual-currency sweepstakes model lawful in {state} as of today, and what "
               "specific features (no-purchase-necessary mechanics, prize redemption, "
               "sweeps-coin sourcing) drive the answer?", "high"),
    ("gaming", "What triggers a change-of-control filing obligation for a licensed operator in "
               "{state}, and what is the filing window?", "high"),
    ("gaming", "When does a promotional mechanic cross from permitted sweepstakes into regulated "
               "gambling — what is the operative consideration test in each launch state?", "high"),
    ("gaming", "What are the key-person/qualifier disclosure obligations when adding an officer or "
               "5%+ holder mid-license-term?", "medium"),
    ("gaming", "Which jurisdictions permit operating pending application approval, and under what "
               "conditions?", "medium"),
    # ── Regulated financial services (vertical #2) ─────────────────────────────
    ("finserv", "At what point does a gaming operator's wallet/payout flow constitute money "
                "transmission requiring state MTL or federal MSB registration?", "high"),
    ("finserv", "What AML program elements are mandatory for a casino/card club vs. an online "
                "operator under 31 CFR Chapter X, and what are the SAR thresholds?", "high"),
    ("finserv", "When does a prediction-market or event-contract product implicate CEA "
                "jurisdiction vs. state gaming law?", "high"),
    ("finserv", "What are the practical CIP/KYC obligations for a fintech operating through a "
                "bank partner, and where does liability sit?", "medium"),
    # ── AI & data regulatory (vertical #3) ─────────────────────────────────────
    ("aidata", "Which obligations under the EU AI Act attach to a company deploying (not "
               "developing) a high-risk AI system, and when do they bite?", "high"),
    ("aidata", "What disclosure is required when AI materially assists in generating "
               "customer-facing legal or financial work product?", "medium"),
]


def _ensure_seeded():
    """Bootstrap the docket table if empty. Idempotent."""
    try:
        existing = db.select("legal_docket", {"select": "id", "limit": "1"}) or []
        if existing:
            return 0
    except Exception:
        return 0  # table not migrated yet — fail soft
    n = 0
    for vertical, question, priority in SEED_DOCKET:
        try:
            db.insert("legal_docket", {
                "vertical": vertical, "question": question, "priority": priority,
                "status": "pending"}, upsert=True)
            n += 1
        except Exception:
            pass
    return n


def _stale_or_unanswered(limit):
    """Questions needing a panel: never answered, or whose card has been invalidated."""
    try:
        return db.select("legal_docket", {
            "select": "id,vertical,question,priority,status",
            "status": "in.(pending,stale)",
            "order": "priority.asc,created_at.asc",
            "limit": str(limit)}) or []
    except Exception:
        return []


def mint_card(row, agg):
    """Persist a Consilium result as a verdict card with validity conditions."""
    citations = agg.get("citations") or []
    card = {
        "docket_id": row.get("id"),
        "vertical": row.get("vertical"),
        "question": row.get("question"),
        "position": (agg.get("opinion") or "")[:12000],
        "verdict": agg.get("verdict"),
        "confidence": float(agg.get("conviction", 5) or 5) / 10.0,
        "citations": json.dumps(citations)[:8000],
        "assumptions": json.dumps(agg.get("assumptions") or [])[:4000],
        "dissent": (agg.get("dissent") or "")[:4000],
        # validity: the authority chain. If any of these change, this card goes stale.
        "authority_chain": json.dumps([c.get("source") for c in citations if isinstance(c, dict)])[:4000],
        "minted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "fresh",
        # Gauntlet-only fields (absent on the committees fallback — hence the .get defaults).
        "flips_if": (agg.get("flips_if") or "")[:2000] or None,
        "conditions": (agg.get("conditions") or "")[:2000] or None,
        "unsettled": bool(agg.get("unsettled")),
        "process": json.dumps(agg.get("process") or {})[:8000],
        # A card is INTERNAL until the publication commission scores it and an attorney signs off.
        # Minting is not publishing; nothing reaches a customer on the strength of a model alone.
        "publication_state": "internal",
    }
    # CITATION-DEPTH FLOOR (2026-07-30): <10 sourced citations may still mint (internal steering
    # beats nothing) but is flagged below-floor — the commission auto-fails it for publication and
    # the question re-queues for a deeper pass instead of letting a thin card ossify as truth.
    if len([c for c in citations if isinstance(c, dict) and c.get("source")]) < 10:
        try:
            proc = json.loads(card["process"]) if card.get("process") else {}
        except Exception:
            proc = {}
        proc["citation_floor"] = "below_floor_10"
        card["process"] = json.dumps(proc)[:8000]
    try:
        db.insert("verdict_cards", card, upsert=True)
        db.update("legal_docket", {"id": row["id"]}, {"status": "answered"})
        return True
    except Exception as e:
        print(f"legal_docket: card persist failed for {row.get('id')}: {e}")
        return False


def run(limit=BATCH):
    """Convene the Consilium on the next batch of docket questions."""
    seeded = _ensure_seeded()
    rows = _stale_or_unanswered(limit)
    if not rows:
        print(json.dumps({"seeded": seeded, "convened": 0, "note": "docket empty or fully answered"}))
        return {"seeded": seeded, "convened": 0}
    minted = 0
    for row in rows:
        q = row.get("question") or ""
        ctx = (f"VERTICAL: {row.get('vertical')}\nPRIORITY: {row.get('priority')}\n\n"
               f"Answer as a memo a GC will act on this week. Cite the operative authority for "
               f"every material assertion; state explicitly what would change the conclusion.")
        agg = None
        # GAUNTLET FIRST (2026-07-30): five adversarial rounds against the persistent expert corps —
        # blind -> steelman -> rebuttal -> red team -> chair. committees.review remains the fallback
        # so a cold/empty corps degrades to the old path instead of producing nothing.
        try:
            import gauntlet
            agg = gauntlet.run(q, context=ctx, vertical=row.get("vertical"), docket_id=row.get("id"))
            if agg and agg.get("error"):
                agg = None
        except Exception as e:
            print(f"legal_docket: gauntlet unavailable on {row.get('id')}: {type(e).__name__}: {str(e)[:120]}")
        if not agg:
            try:
                import committees
                agg = committees.review("legal_question", row.get("id"), q, ctx, app="apparently")
            except Exception as e:
                print(f"legal_docket: panel failed on {row.get('id')}: {type(e).__name__}: {str(e)[:120]}")
        if agg and mint_card(row, agg):
            minted += 1
    out = {"seeded": seeded, "convened": len(rows), "cards_minted": minted}
    print("legal_docket: " + json.dumps(out))
    return out


if __name__ == "__main__":
    print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 else BATCH), indent=2))
