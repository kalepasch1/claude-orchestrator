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


def _s(v):
    """Coerce ANY model-returned value to a sliceable string. The model intermittently returns a
    dict/list where the schema says string; `somedict[:1500]` then throws KeyError: slice — the
    exact bug family that killed committees for weeks (Part 0). Never slice model output raw."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        import json as _j
        return _j.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)

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


VALUE_RANK = os.environ.get("ORCH_DOCKET_VALUE_RANK", "true").lower() not in ("0", "false", "no", "off")
MATRIX_TOPUP = int(os.environ.get("ORCH_DOCKET_MATRIX_TOPUP", "4"))
MAX_PENDING = int(os.environ.get("ORCH_DOCKET_MAX_PENDING", "300"))
# DEMAND FIRST (2026-09-29, operator). The law app's open advisory gaps are the docket's primary source
# (gap_intake.py): while any gap-origin question is pending it is answered first, by value, and the
# synthetic matrix top-up is paused.
GAP_FIRST = os.environ.get("ORCH_DOCKET_GAP_FIRST", "true").lower() not in ("0", "false", "no", "off")


FAMILY_FIRST = os.environ.get("ORCH_DOCKET_FAMILY_FIRST", "true").lower() not in ("0", "false", "no", "off")


def _family_ready():
    try:
        import frontier
        return frontier.can_think(min_tokens=20000)
    except Exception:
        return False


def _gap_rows(limit):
    if not GAP_FIRST:
        return []
    try:
        import gap_intake
        return gap_intake.pending_gap_rows()[:limit]
    except Exception as e:
        print(f"legal_docket: gap queue unavailable: {type(e).__name__}: {str(e)[:100]}")
        return []


def _stale_or_unanswered(limit):
    """Questions needing a panel: never answered, or whose card has been invalidated.

    VALUE-RANKED, FAIR-SHARE (2026-09-21). The old sort was `priority.asc,created_at.asc` on a
    TEXT column: alphabetical (high, low, medium), oldest first. With 1,022 questions stamped
    "high" by their generators, the panel answered the oldest gaming questions forever; the
    `data` vertical was never reached. docket_matrix.pick ranks by risk x lens x starvation
    and rotates verticals. The legacy sort remains as the fallback."""
    if VALUE_RANK:
        try:
            import docket_matrix
            rows = docket_matrix.pick(limit)
            if rows:
                return rows
        except Exception as e:
            print(f"legal_docket: value-ranked pick failed, using legacy order: {type(e).__name__}: {str(e)[:100]}")
    try:
        return db.select("legal_docket", {
            "select": "id,vertical,question,priority,status",
            "status": "in.(pending,stale)",
            "order": "priority.asc,created_at.asc",
            "limit": str(limit)}) or []
    except Exception:
        return []


# FRONTIER-ONLY (2026-09-12). When the frontier budget was spent, the docket fell to the 21-call local
# path: each 27B seat call took ~10 minutes, the job hit its 45-minute cap with no card minted, and
# the tick's one slot was held the whole time while the commission, drafter and theory lab waited.
# A question nobody frontier-grade can answer right now stays pending for the next cycle; the local
# path remains available by setting ORCH_DOCKET_FRONTIER_ONLY=false.
FRONTIER_ONLY = os.environ.get("ORCH_DOCKET_FRONTIER_ONLY", "true").lower() not in ("0", "false", "no", "off")


def _frontier_ready():
    try:
        import consilium_v2
        return consilium_v2.ready()      # engine-aware: the local tier needs no subscription budget
    except Exception:
        return False


def _json_capped(obj, cap):
    """Serialise within `cap` characters WITHOUT breaking the JSON (2026-09-12: a flat [:8000] slice
    truncated every v2 card's 20-citation array mid-string, so readers parsed it as empty and the
    commission scored 'citations array empty' on fully grounded cards). Lists lose trailing items;
    dicts lose their largest values first and record what was dropped."""
    txt = json.dumps(obj)
    if len(txt) <= cap:
        return txt
    if isinstance(obj, list):
        items = list(obj)
        while items and len(json.dumps(items)) > cap:
            items.pop()
        return json.dumps(items)
    if isinstance(obj, dict):
        d = dict(obj)
        dropped = []
        while d and len(json.dumps(d)) > cap:
            k = max(d, key=lambda kk: len(json.dumps(d[kk])))
            dropped.append(k)
            d.pop(k)
            d["_truncated"] = dropped
        return json.dumps(d)
    return json.dumps(str(obj)[:max(0, cap - 2)])


def mint_card(row, agg):
    """Persist a Consilium result as a verdict card with validity conditions."""
    # HOLLOW-CARD GUARD (2026-07-30): the first live cards minted with NULL verdict, empty
    # position, and zero citations (early model calls returning empty) — and still marked the
    # docket question 'answered', permanently blocking a re-debate. An empty answer is not an
    # answer: refuse to mint, leave the question pending, let the next cycle try again.
    if len((agg.get("opinion") or "").strip()) < 200 or not (agg.get("verdict") or "").strip():
        print(f"legal_docket: refusing hollow card for {row.get('id')} "
              f"(opinion={len((agg.get('opinion') or '').strip())} chars, "
              f"verdict={'set' if (agg.get('verdict') or '').strip() else 'EMPTY'}) — question stays pending")
        return False
    citations = agg.get("citations") or []
    card = {
        "docket_id": row.get("id"),
        "vertical": row.get("vertical"),
        "question": row.get("question"),
        "position": _s(agg.get("opinion"))[:12000],
        "verdict": agg.get("verdict"),
        "confidence": float(agg.get("conviction", 5) or 5) / 10.0,
        "citations": _json_capped(citations, 60000),
        "assumptions": _json_capped(agg.get("assumptions") or [], 8000),
        "dissent": _s(agg.get("dissent"))[:4000],
        # validity: the authority chain. If any of these change, this card goes stale.
        "authority_chain": _json_capped([c.get("source") for c in citations if isinstance(c, dict)], 16000),
        "minted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "fresh",
        # Gauntlet-only fields (absent on the committees fallback — hence the .get defaults).
        "flips_if": _s(agg.get("flips_if"))[:2000] or None,
        "conditions": _s(agg.get("conditions"))[:2000] or None,
        "unsettled": bool(agg.get("unsettled")),
        "process": _json_capped(agg.get("process") or {}, 24000),
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
        card["process"] = _json_capped(proc, 24000)
    try:
        db.insert("verdict_cards", card, upsert=True)
        db.update("legal_docket", {"id": row["id"]}, {"status": "answered"})
        return True
    except Exception as e:
        print(f"legal_docket: card persist failed for {row.get('id')}: {e}")
        return False


def _triaged_ids():
    """Ids the docket clerk kept or rewrote (docket_triage ledger). Empty when triage never ran."""
    path = os.path.join(os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator")),
                        "consilium", "docket_triage.jsonl")
    ids = set()
    try:
        with open(path) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("dry_run") or rec.get("decision") == "retire" or rec.get("tier") == "local":
                    continue
                ids.add(rec.get("id"))
    except OSError:
        pass
    return ids


def run(limit=BATCH):
    """Convene the Consilium on the next batch of docket questions."""
    seeded = _ensure_seeded()
    # BACKLOG GATE (2026-09-28). 1,643 questions were pending while every run generated four more.
    # Generation resumes when the vetted backlog is short enough that new questions would be reached.
    try:
        backlog = db.count("legal_docket", {"status": "eq.pending"}) or 0
    except Exception:
        backlog = 0
    only = {p.strip().lower() for p in os.environ.get("ORCH_DOCKET_PRIORITIES", "").split(",") if p.strip()}
    all_gaps = _gap_rows(500)
    # QUESTION FAMILIES (2026-09-29). Gap questions asked once per jurisdiction are charted together by
    # family_matrix (one framework, free per-jurisdiction research, one chart call per few members)
    # instead of one tournament each. While a family has uncharted members, a tick charts them; those
    # members are held back from the one-at-a-time route. Open cells come back to it afterwards.
    if all_gaps and FAMILY_FIRST:
        try:
            import family_matrix
            fam = family_matrix.next_family(all_gaps) if family_matrix.ENABLED else None
            if fam and _family_ready():
                res = family_matrix.run(fam, mint=mint_card)
                summary = {"seeded": seeded, "convened": res["cells"], "cards_minted": res["minted"],
                           "family": {k: res.get(k) for k in ("family", "members", "settled", "contested", "open",
                                                              "chart_calls", "tiers", "doc")}}
                print(json.dumps(summary), flush=True)
                return summary
            if family_matrix.ENABLED:
                held = family_matrix.held_for_family(all_gaps)
                if held:
                    print(f"legal_docket: {len(held)} gap question(s) held for a family pass")
                all_gaps = [r for r in all_gaps if r["id"] not in held]
        except Exception as e:
            print(f"legal_docket: family pass skipped: {type(e).__name__}: {str(e)[:120]}")
    gap_rows = [r for r in all_gaps if not only or str(r.get("priority") or "").lower() in only][:limit * 12]
    if gap_rows or all_gaps:
        print(f"legal_docket: {len(gap_rows)} law-app gap question(s) queued first; synthetic top-up paused")
    elif MATRIX_TOPUP > 0 and backlog > MAX_PENDING:
        print(f"legal_docket: matrix top-up skipped: {backlog} questions pending (> {MAX_PENDING})")
    elif MATRIX_TOPUP > 0:
        # Fill the emptiest lens x risk x vertical cells before choosing what to answer, so
        # innovation pathways and cross-industry analogs are on the docket at all.
        try:
            import docket_matrix
            topped = docket_matrix.generate(MATRIX_TOPUP)
            print("legal_docket: matrix top-up " + json.dumps({k: topped[k] for k in ("proposed", "admitted", "rejected")}))
        except Exception as e:
            print(f"legal_docket: matrix top-up skipped: {type(e).__name__}: {str(e)[:100]}")
    vetted = _triaged_ids() if os.environ.get("ORCH_DOCKET_TRIAGED_FIRST", "true").lower() not in ("0", "false", "no", "off") else set()
    if gap_rows:
        rows = gap_rows[:limit]
    elif vetted:
        # Prefer questions the clerk has kept or rewritten; untriaged ones wait their turn.
        pool = [r for r in _stale_or_unanswered(limit * 12) if r.get("id") in vetted
                and (not only or str(r.get("priority") or "").lower() in only)]
        rows = pool[:limit] if pool else []
        if not rows and not only:
            rows = _stale_or_unanswered(limit)
    elif only:
        # Host-constrained run: only questions the frontier tier will take are convened; the rest
        # wait for a tick that can fund local inference rather than being skipped one by one.
        rows = [r for r in _stale_or_unanswered(limit * 6) if str(r.get("priority") or "").lower() in only][:limit]
    else:
        rows = _stale_or_unanswered(limit)
    if not rows:
        print(json.dumps({"seeded": seeded, "convened": 0, "note": "docket empty or fully answered"}))
        return {"seeded": seeded, "convened": 0}
    minted, skipped, convened, precedents = 0, 0, 0, 0
    for row in rows:
        if FRONTIER_ONLY and not _frontier_ready():
            skipped = len(rows) - convened
            print(f"legal_docket: frontier budget cannot fund a tournament; {skipped} question(s) stay pending "
                  f"for the next cycle (ORCH_DOCKET_FRONTIER_ONLY)", flush=True)
            break
        q = row.get("question") or ""
        try:
            import escalation
            card, sim = escalation.precedent(q, row.get("vertical"))
        except Exception:
            card, sim = None, 0.0
        if card and card.get("docket_id") != row.get("id"):
            # Already answered: retire as a duplicate of the card, reversibly, with zero model calls.
            try:
                db.update("legal_docket", {"id": row["id"]}, {"status": "retired"})
                escalation._append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "docket_id": row.get("id"),
                                    "vertical": row.get("vertical"), "priority": row.get("priority"), "question": q[:300],
                                    "route": "precedent", "precedent_card": card.get("id"), "similarity": sim,
                                    "original_status": row.get("status")})
                print(f"legal_docket: {row.get('id')} resolved by precedent (card {str(card.get('id'))[:8]}, similarity {sim})", flush=True)
                precedents += 1
                continue
            except Exception:
                pass
        convened += 1
        ctx = (f"VERTICAL: {row.get('vertical')}\nPRIORITY: {row.get('priority')}\n\n"
               f"Answer as a memo a GC will act on this week. Cite the operative authority for "
               f"every material assertion; state explicitly what would change the conclusion.")
        agg = None
        # CONSILIUM V2 FIRST (2026-09-12): one frontier-grade tournament. Then, only when the operator
        # allows local fallbacks, the legacy GAUNTLET (2026-07-30: five adversarial rounds against the
        # persistent corps) and committees.review behind it.
        try:
            import consilium_v2
            agg = consilium_v2.run(q, context=ctx, vertical=row.get("vertical"), docket_id=row.get("id"),
                                   priority=row.get("priority"))
        except Exception as e:
            print(f"legal_docket: consilium_v2 failed on {row.get('id')}: {type(e).__name__}: {str(e)[:120]}")
        if not agg and FRONTIER_ONLY:
            print(f"legal_docket: {row.get('id')} stays pending — no frontier-grade tournament was possible", flush=True)
            skipped += 1
            continue
        if not agg:
            try:
                import gauntlet
                agg = gauntlet.run(q, context=ctx, vertical=row.get("vertical"), docket_id=row.get("id"), v2=False)
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
    insights = None
    try:
        # A card that steers nothing is a document. Distil every new card into insights.
        import steering_insights
        insights = steering_insights.sync()
    except Exception as e:
        print(f"legal_docket: insight sync skipped: {type(e).__name__}: {str(e)[:100]}")
    out = {"seeded": seeded, "precedents": precedents, "convened": convened, "cards_minted": minted, "left_pending": skipped,
           "frontier_only": FRONTIER_ONLY, "insights": insights}
    print("legal_docket: " + json.dumps(out))
    return out


if __name__ == "__main__":
    import single_instance
    _owned, _deadline = single_instance.guard("legal_docket", interval_s=1800)
    if not _owned:
        print(json.dumps({"skipped": "legal_docket already running"}))
        raise SystemExit(0)
    try:
        print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 else BATCH), indent=2))
    finally:
        if _deadline is not None:
            _deadline.cancel()
