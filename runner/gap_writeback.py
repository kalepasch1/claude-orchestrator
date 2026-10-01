#!/usr/bin/env python3
"""gap_writeback.py — close the loop: a gap the docket answered gets its answer in the law app.

WHY (2026-09-29). gap_intake.py makes the law app's open `advisory_inquiry_gaps` the docket's primary
source. An answer that stays in the control plane unblocks nothing; the propositions a gap blocks are
unblocked only when the app can see the answer next to the gap.

OPERATOR POLICY. The answer is written UNREVIEWED and linked to the gap. Below medium risk, attorney
review is not required (it stays optional and additive): the gap is marked `answered`. At medium or
high risk the answer is attached but the gap stays `open` for an attorney.

WHAT IS WRITTEN (one `advisory_inquiry_answers` row per card):
    advisory_use      internal_only. Research is not correspondence; the app's citation trigger
                      requires a named responder, organisation and date for any wider use, and none
                      is invented here.
    source_party      "Apparently Law research (Consilium)"; source_channel "research"
    source_url        the card's first fetched citation
    document_ref      verdict_card:<id>
    authority_weight  informal
    confidence        the card's computed confidence

PRECEDENT. A gap question the docket retired as a duplicate of an answered card (legal_docket's
precedent step, zero model calls) gets that card's answer too, always banded at least medium: the
match is by similarity, so an attorney confirms it fits.

RISK BAND. Starts from the export's own tiering (adversary severity, unsettled, confidence), then:
a provisional (local-tier) acceptance or a composite under ACCEPT_LOW_COMPOSITE is at least medium;
fewer than MIN_LOW_CITATIONS fetched citations is at least medium. Only `low` closes a gap.

RISK SCORE (owner decision 2026-09-30; law-project migration al_002, smarter#1177). Every answer carries
`risk_score`: the MAXIMUM of Smarter's existing intel_propositions.risk_score (0-100) over the propositions
the answer's gap blocks. The law gap names its Smarter gap (source_system 'smarter', source_gap_id), and
Smarter's intel_gap_propositions links that gap to its propositions. `risk_score_basis` names the source.
No score is invented. A gap from another source (corpus-swarm, exo-hivemind), a gap with no linked
proposition, or propositions without a score give NULL, and the law trigger then treats the answer as
70+, so a superadmin must review it before client advice. The answer is still written internal_only.
Until al_002 is applied the law project has no such columns: the insert is retried without them and
the ledger records `risk_score_unwritten`.

Idempotent: a local ledger (<home>/consilium/gap_writeback.jsonl) records every write; a card is
written once. Nothing else in the law app is modified.
"""
from __future__ import annotations
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common_utils
import db

_s = common_utils.safe_string_coerce

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
LEDGER = os.path.join(HOME, "consilium", "gap_writeback.jsonl")
SOURCE_PARTY = "Apparently Law research (Consilium)"
ACCEPT_LOW_COMPOSITE = float(os.environ.get("ORCH_GAP_LOW_COMPOSITE", "0.6"))
MIN_LOW_CITATIONS = int(os.environ.get("ORCH_GAP_LOW_MIN_CITES", "3"))
PER_RUN = int(os.environ.get("ORCH_GAP_WRITEBACK_PER_RUN", "40"))
RANK = {"low": 0, "medium": 1, "high": 2}
RISK_BASIS = "smarter.intel_propositions.risk_score:max"


def _written():
    out = set()
    try:
        with open(LEDGER) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("ok") and not r.get("dry_run"):
                    out.add(r.get("card_id"))
    except OSError:
        pass
    return out


def _log(rec):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def _cites(card):
    import consilium_export
    return [c for c in consilium_export._loads(card.get("citations"), []) if isinstance(c, dict)]


def risk_band(card, review):
    """-> (band, reasons). Only `low` lets the gap close without an attorney."""
    import consilium_export
    proc = consilium_export._loads(card.get("process"), {})
    band = consilium_export._risk_tier(card, proc)
    why = [f"base {band}"]
    detail = consilium_export._loads(review.get("detail"), {})

    def at_least(b, reason):
        nonlocal band
        if RANK[b] > RANK[band]:
            band = b
            why.append(reason)

    if review.get("_via_precedent"):
        at_least("medium", f"answer by precedent (similarity {review.get('_similarity')})")
    if str(proc.get("tier") or "").lower() == "local":
        at_least("medium", "answered on the local tier")
    if detail.get("provisional"):
        at_least("medium", "provisional (local-tier) review")
    if float(review.get("composite") or 0) < ACCEPT_LOW_COMPOSITE:
        at_least("medium", f"composite {review.get('composite')} < {ACCEPT_LOW_COMPOSITE}")
    urls = [c for c in _cites(card) if _s(c.get("url") or c.get("source")).startswith("http")]
    if len(urls) < MIN_LOW_CITATIONS:
        at_least("medium", f"{len(urls)} fetched citations < {MIN_LOW_CITATIONS}")
    return band, why


def _valid_score(v):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100


def gap_risk_score(gap, select=None):
    """-> (risk_score | None, basis | None) for a law gap, from Smarter's own proposition scores.

    Read-only on Smarter. `select` is db.select (the runner's Smarter connection); injectable for tests.
    """
    if _s((gap or {}).get("source_system")) != "smarter" or not (gap or {}).get("source_gap_id"):
        return None, None
    select = select or db.select
    links = select("intel_gap_propositions", {"select": "proposition_id",
                                              "gap_id": f"eq.{gap['source_gap_id']}", "limit": "1000"}) or []
    pids = sorted({_s(r.get("proposition_id")) for r in links if r.get("proposition_id")})
    scores = []
    for k in range(0, len(pids), 100):
        chunk = pids[k:k + 100]
        rows = select("intel_propositions", {"select": "id,risk_score", "id": "in.(" + ",".join(chunk) + ")",
                                             "risk_score": "not.is.null", "limit": str(len(chunk))}) or []
        scores += [r["risk_score"] for r in rows if _valid_score(r.get("risk_score"))]
    if not scores:
        return None, None
    return max(scores), RISK_BASIS


def answer_row(gap_id, card, review):
    cites = _cites(card)
    url = next((_s(c.get("url") or c.get("source")) for c in cites
                if _s(c.get("url") or c.get("source")).startswith("http")), None)
    verdict = _s(card.get("verdict")).strip()
    body = [f"ANSWER: {verdict}", "", _s(card.get("position")).strip()]
    if _s(card.get("conditions")).strip():
        body += ["", "CONDITIONS: " + _s(card.get("conditions")).strip()]
    if _s(card.get("flips_if")).strip():
        body += ["", "WOULD CHANGE IF: " + _s(card.get("flips_if")).strip()]
    labels = [(_s(c.get("source") or c.get("label")), _s(c.get("url"))) for c in cites[:12]]
    if labels:
        body += ["", "AUTHORITIES:"] + [f"- {l}" + (f" <{u}>" if u and u != l else "") for l, u in labels]
    body += ["", "Unreviewed research answer (Consilium). Attorney review is optional below medium risk."]
    return {"gap_id": gap_id, "source_party": SOURCE_PARTY, "source_channel": "research", "source_url": url,
            "document_ref": f"verdict_card:{card['id']}", "answer_text": "\n".join(body)[:20000],
            "answer_summary": verdict[:1000] or None, "authority_weight": "informal",
            "advisory_use": "internal_only",
            "confidence": max(0.0, min(1.0, float(card.get("confidence") or 0)))}


def candidates(limit=PER_RUN):
    """(gap_id, card, review) for accepted cards on gap-origin docket rows not yet written back."""
    import consilium_export
    reviews = consilium_export.accepted_reviews(limit=1000)
    if not reviews:
        return []
    done = _written()
    ids = [i for i in reviews if i and i not in done]
    out = []
    for k in range(0, len(ids), 60):
        cards = db.select("verdict_cards", {
            "select": "id,docket_id,vertical,question,verdict,position,confidence,citations,conditions,flips_if,"
                      "unsettled,status,process", "status": "eq.fresh",
            "id": "in.(" + ",".join(ids[k:k + 60]) + ")", "limit": "60"}) or []
        dids = [c["docket_id"] for c in cards if c.get("docket_id")]
        origins = {}
        if dids:
            for r in db.select("legal_docket", {"select": "id,origin", "id": "in.(" + ",".join(dids) + ")",
                                                "limit": str(len(dids))}) or []:
                origins[r["id"]] = _s(r.get("origin"))
        for c in cards:
            o = origins.get(c.get("docket_id"), "")
            if o.startswith("advisory_gap:"):
                out.append((o.split(":", 1)[1], c, reviews[c["id"]]))
            if len(out) >= limit:
                return out
    return out


def precedent_candidates(reviews=None, done=None):
    """(gap_id, card, review) for gap questions retired as duplicates of an accepted card."""
    import consilium_export
    path = os.path.join(HOME, "consilium", "escalation_ledger.jsonl")
    hits = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("route") == "precedent" and r.get("precedent_card") and r.get("docket_id"):
                    hits.append(r)
    except OSError:
        return []
    if not hits:
        return []
    reviews = reviews if reviews is not None else consilium_export.accepted_reviews(limit=1000)
    done = done if done is not None else _written()
    hits = [h for h in hits if h["precedent_card"] in reviews and f"{h['precedent_card']}@{h['docket_id']}" not in done]
    if not hits:
        return []
    dids = sorted({h["docket_id"] for h in hits})[:120]
    origins = {r["id"]: _s(r.get("origin")) for r in (db.select("legal_docket", {
        "select": "id,origin", "id": "in.(" + ",".join(dids) + ")", "limit": str(len(dids))}) or [])}
    hits = [h for h in hits if origins.get(h["docket_id"], "").startswith("advisory_gap:")]
    if not hits:
        return []
    cids = sorted({h["precedent_card"] for h in hits})
    cards = {c["id"]: c for c in (db.select("verdict_cards", {
        "select": "id,docket_id,vertical,question,verdict,position,confidence,citations,conditions,flips_if,"
                  "unsettled,status,process", "status": "eq.fresh", "id": "in.(" + ",".join(cids) + ")",
        "limit": str(len(cids))}) or [])}
    out = []
    for h in hits:
        c = cards.get(h["precedent_card"])
        if c:
            rv = dict(reviews[c["id"]], _via_precedent=True, _similarity=h.get("similarity"),
                      _ledger_key=f"{c['id']}@{h['docket_id']}")
            out.append((origins[h["docket_id"]].split(":", 1)[1], c, rv))
    return out


def _missing_risk_columns(err):
    """True when the law project rejected the insert because al_002's columns are not there yet."""
    text = str(err)
    body = getattr(err, "read", None)
    if callable(body):
        try:
            text += body().decode("utf-8", "replace")
        except Exception:
            pass
    return "risk_score" in text and ("PGRST204" in text or "column" in text.lower())


def run(limit=PER_RUN, dry_run=False, items=None, req=None, smarter_select=None):
    import consilium_export
    req = req or consilium_export._req
    if items is None:
        items = candidates(limit)
        try:
            items += precedent_candidates()
        except Exception as e:
            print(f"gap_writeback: precedent scan skipped: {type(e).__name__}: {str(e)[:100]}")
    tally = {"candidates": len(items), "written": 0, "answered": 0, "left_open": 0, "errors": 0, "dry_run": dry_run,
             "bands": {"low": 0, "medium": 0, "high": 0}}
    for gap_id, card, review in items[:limit]:
        band, why = risk_band(card, review)
        tally["bands"][band] += 1
        rec = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "gap_id": gap_id,
               "card_id": review.get("_ledger_key") or card["id"], "band": band, "why": why, "dry_run": dry_run}
        if dry_run:
            rec["ok"] = True
            _log(rec)
            continue
        try:
            gap = req("GET", "advisory_inquiry_gaps", params={"select": "id,status,source_system,source_gap_id",
                                                              "id": f"eq.{gap_id}", "limit": "1"})
            if not gap:
                raise RuntimeError("gap not found")
            row = answer_row(gap_id, card, review)
            try:
                score, basis = gap_risk_score(gap[0], smarter_select)
            except Exception as e:  # a Smarter read failure leaves the score unknown (= review), never invented
                score, basis = None, None
                rec["risk_score_error"] = f"{type(e).__name__}: {str(e)[:120]}"
            rec["risk_score"] = score
            if score is not None:
                row["risk_score"], row["risk_score_basis"] = score, basis
            try:
                ins = req("POST", "advisory_inquiry_answers", body=row, prefer="return=representation")
            except Exception as e:
                if score is None or not _missing_risk_columns(e):
                    raise
                bare = {k: v for k, v in row.items() if k not in ("risk_score", "risk_score_basis")}
                rec["risk_score_unwritten"] = "law project lacks al_002 columns"
                ins = req("POST", "advisory_inquiry_answers", body=bare, prefer="return=representation")
            rec["answer_id"] = (ins[0] if isinstance(ins, list) and ins else {}).get("id")
            tally["written"] += 1
            if band == "low" and gap[0].get("status") == "open":
                req("PATCH", "advisory_inquiry_gaps", body={"status": "answered"},
                    params={"id": f"eq.{gap_id}", "status": "eq.open"}, prefer="return=minimal")
                rec["gap_status"] = "answered"
                tally["answered"] += 1
            else:
                rec["gap_status"] = gap[0].get("status")
                tally["left_open"] += 1
            rec["ok"] = True
        except Exception as e:
            rec["ok"] = False
            rec["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            tally["errors"] += 1
        _log(rec)
    print("gap_writeback: " + json.dumps(tally), flush=True)
    return tally


if __name__ == "__main__":
    import single_instance
    _owned, _deadline = single_instance.guard("gap_writeback", interval_s=3600)
    if not _owned:
        print(json.dumps({"skipped": "gap_writeback already running"}))
        raise SystemExit(0)
    try:
        run(dry_run="--dry-run" in sys.argv[1:])
    finally:
        if _deadline is not None:
            _deadline.cancel()
