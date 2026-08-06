#!/usr/bin/env python3
"""benchmark_redlines.py — the proof-of-superiority engine.

THE PLAY (operator direction 2026-07-30): social/benchmark evidence that our output beats the most
premium firms in the world cannot come from us grading our own homework on questions we invented.
It comes from taking THEIR work product — real briefs and memos filed in the most contentious,
highest-stakes regulatory/compliance matters (pending SCOTUS and circuit arguments, plus the
consequential fights of the last 20-40 years) — and doing two things in public:
    1) a REDLINE: issue-by-issue, where the filed argument is weak, what it missed, what a stronger
       version says, each entry scored for novelty and risk;
    2) an ADDENDUM: a fully-revised memo, cited end-to-end, good enough that it could be used in the
       matter as it stands today.
A reader does not have to trust our benchmark; they can hold our version next to the one a
top-ranked firm billed seven figures for and judge with their own eyes.

FIVE INTEGRITY RULES — each one exists because breaking it converts the marketing asset into a
liability, and each is enforced in code, not in a style guide:

  1. NEVER REDLINE A DOCUMENT WE DO NOT HOLD. The model's memory of a famous brief is not the
     brief. A target stays 'pending_source' until the actual public filing text is ingested
     (schema CHECK enforces it), and every quoted excerpt is verified VERBATIM against the source
     by substring match before it may persist as grounded. One fabricated quote in a public
     redline of a named firm's work ends the entire program.
  2. OPINION, GROUNDED. Entries critique the ARGUMENT ("a stronger position was available under
     X"), and any claim of outright error must carry the controlling authority that shows it.
     Filed briefs are public records and commentary on them is core protected speech — but the
     defamation-safe posture is the same one that makes the content good: reasoned analysis over
     accusation.
  3. PUBLIC RECORD ONLY. Filings, opinions, transcripts. Nothing from any private engagement, ever.
  4. PENDING MATTERS get a standing banner: commentary on the public record, not advice to any
     party, no relationship with any party. (Redlining PENDING arguments is also where the play is
     strongest: our addendum is checkable against a ruling that hasn't happened yet — which is why
     every target also carries a SEALED outcome prediction. When the court rules, our Brier score
     becomes the benchmark no firm can match, because none of them publish forecasts at all.)
  5. SAME GATE AS EVERYTHING ELSE. commission_review -> attorney_review -> published. The gauntlet
     drafts; the commission scores; Brian signs; only then does it ship.

The hedge note (operator ask): each contentious issue may carry ONE quiet line framing what an
adverse-outcome hedge on that issue would look like on Tomorrow — indicative, no numbers we cannot
support, subtle enough not to degrade the memo. The memo is the product; the hedge line is a door
left ajar.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import expert_corps as corps

BATCH = int(os.environ.get("ORCH_BENCH_REDLINE_BATCH", "1"))
MAX_ISSUES = int(os.environ.get("ORCH_BENCH_MAX_ISSUES", "8"))

# Seed docket of target CLASSES. Deliberately not fake case data: each row names a real, findable
# matter-class and where its public filings live. Targets activate only when source_text arrives
# (operator paste, court RSS/CourtListener fetch task, or the research loop).
SEED_TARGETS = [
    {"case_name": "Kalshi v. state gaming regulators (event-contract preemption line)", "court": "federal courts of appeals",
     "vertical": "finserv", "filing_type": "brief", "pending": True, "prominence": "landmark",
     "stakes": "whether CEA preemption ousts state gaming law from sports event contracts — existential for prediction markets",
     "filing_url": "https://www.courtlistener.com/ (party + amicus briefs, public docket)"},
    {"case_name": "Sweepstakes dual-currency enforcement actions (state AG matters)", "court": "state courts / AG consent decrees",
     "vertical": "gaming", "filing_type": "memo", "pending": True, "prominence": "high",
     "stakes": "the operative consideration test for sweeps models — the exact question our launch clients pay for",
     "filing_url": "public consent decrees + complaints, state AG sites"},
    {"case_name": "Murphy v. NCAA (PASPA, 2018) — merits briefing", "court": "SCOTUS",
     "vertical": "gaming", "filing_type": "brief", "pending": False, "prominence": "landmark",
     "stakes": "the anticommandeering holding that created the modern sports-betting market",
     "filing_url": "SCOTUSblog / Supreme Court docket 16-476"},
    {"case_name": "Loper Bright v. Raimondo (2024) — merits briefing", "court": "SCOTUS",
     "vertical": "aidata", "filing_type": "brief", "pending": False, "prominence": "landmark",
     "stakes": "Chevron's end — reshapes every agency-deference argument in every regulated vertical we serve",
     "filing_url": "Supreme Court docket 22-451"},
    {"case_name": "CFPB funding / major-questions line (post-Seila, post-West Virginia)", "court": "SCOTUS / CA5",
     "vertical": "finserv", "filing_type": "brief", "pending": False, "prominence": "high",
     "stakes": "the structural-challenge playbook every regulated fintech now argues from",
     "filing_url": "public dockets"},
]

REDLINE_PROMPT = """You are a gauntlet-hardened panel redlining a REAL filed {filing_type} in:
  {case_name} ({court}{docket}). Stakes: {stakes}

Below is the verbatim text of the filing (public record). Your job is the one no firm will do in
public: find where this work product — from one of the most credentialed legal teams in the world —
is weaker than it had to be, and show the stronger version.

RULES, non-negotiable:
- `original_excerpt` must be COPIED VERBATIM from the text below (it will be machine-verified by
  substring match; a paraphrase fails and the entry is discarded).
- Critique the ARGUMENT. "A stronger position was available under [authority]" — and if you assert
  an outright error, cite the controlling authority that establishes it.
- Every `improvement` carries its authority. An uncited improvement is an opinion, not a redline.
- `novelty_score`: how non-obvious is our improvement (0 = any associate would catch it, 1 = a
  genuinely new line of argument). `risk_score`: how much of the matter's outcome turns on this
  issue (0-1), with a one-sentence rationale — this is the risk gradient we show readers.
- `hedge_note`: ONE quiet sentence, only where natural: what hedging the adverse outcome of THIS
  issue would look like as a parametric position (indicative, no invented prices). Omit (empty
  string) where it would feel forced. The memo must never read like an ad.
- Find at most {max_issues} issues. Rank by risk_score. Fewer, deeper entries beat many shallow ones.

FILING TEXT:
{source}

Return a JSON ARRAY of entries:
[{{"issue":"...","original_excerpt":"verbatim","critique":"...","improvement":"...",
   "citations":[{{"source":"authority","proposition":"...","confidence":0.0-1.0}}],
   "novelty_score":0.0-1.0,"risk_score":0.0-1.0,"risk_rationale":"one sentence",
   "hedge_note":"one quiet sentence or ''","severity":"dispositive|material|marginal"}}]"""

ADDENDUM_PROMPT = """You are the chair. The panel has redlined the filed {filing_type} in
{case_name} ({court}). Now write the ADDENDUM: the fully-revised memo — the version we claim is
better than what was filed. It must stand alone: a lawyer in this matter could pick it up and use
it TODAY.

Structure: question presented -> summary of the answer -> argument (issue by issue, incorporating
every improvement below, each with its authority) -> what would change the analysis -> conclusion.
Cite everything. Where the filed version was already strong, SAY SO and keep it — a revision that
manufactures disagreement to justify itself is weaker than the original, and readers will see it.

THE REDLINE ENTRIES TO INCORPORATE:
{entries}

ALSO: seal an outcome prediction. If this matter is or were decided on these arguments, what is the
probability the position prevails? You are betting our public calibration record on it.

Return ONE JSON object:
{{"addendum":"the full revised memo, cited inline",
  "citations":[{{"source":"authority","proposition":"...","confidence":0.0-1.0}}],
  "outcome_prediction":{{"probability":0.0-1.0,"what_resolves_it":"the ruling/event that scores this",
                         "horizon":"when we expect resolution"}},
  "kept_from_original":"what the filed version got right that we preserved"}}"""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_seeded():
    try:
        if (db.count("benchmark_targets", {}) or 0) > 0:
            return 0
    except Exception:
        return 0
    n = 0
    for t in SEED_TARGETS:
        try:
            db.insert("benchmark_targets", {**t, "status": "pending_source"}, upsert=True)
            n += 1
        except Exception:
            pass
    return n


def ingest_source(target_id, source_text, filing_url=None):
    """The ONLY door from pending_source to ready. Digest recorded so the redline is pinned to
    exactly the text we held — if the source is ever disputed, we can prove what we redlined."""
    if not source_text or len(source_text) < 2000:
        return {"error": "source_text too short to be a real filing — refusing to mark ready"}
    digest = hashlib.sha256(source_text.encode("utf-8", "replace")).hexdigest()
    patch = {"source_text": source_text[:900000], "source_digest": digest,
             "status": "ready", "updated_at": _now()}
    if filing_url:
        patch["filing_url"] = filing_url
    try:
        db.update("benchmark_targets", {"id": target_id}, patch)
        return {"ok": True, "digest": digest}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}


def _verify_excerpt(excerpt, source):
    """Grounding check: the quote must appear verbatim (whitespace-normalized) in the source."""
    if not excerpt or len(excerpt) < 20:
        return False
    norm = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()
    return norm(excerpt) in norm(source)


def redline_target(t):
    src = t.get("source_text") or ""
    entries = corps._json(REDLINE_PROMPT.format(
        filing_type=t.get("filing_type"), case_name=t.get("case_name"), court=t.get("court"),
        docket=f", No. {t['docket_no']}" if t.get("docket_no") else "",
        stakes=(t.get("stakes") or "")[:400], max_issues=MAX_ISSUES,
        source=src[:80000]), kind="review", need="redline", arr=True) or []
    kept, dropped = [], 0
    for e in entries[:MAX_ISSUES]:
        if not isinstance(e, dict) or not e.get("critique"):
            continue
        grounded = _verify_excerpt(e.get("original_excerpt"), src)
        if not grounded:
            dropped += 1          # rule 1: an unverifiable quote never persists as grounded
        row = {"target_id": t["id"], "issue": str(e.get("issue") or "")[:500],
               "original_excerpt": str(e.get("original_excerpt") or "")[:4000],
               "critique": str(e.get("critique") or "")[:6000],
               "improvement": str(e.get("improvement") or "")[:8000],
               "citations": json.dumps(e.get("citations") or [])[:6000],
               "novelty_score": max(0.0, min(1.0, float(e.get("novelty_score") or 0))),
               "risk_score": max(0.0, min(1.0, float(e.get("risk_score") or 0))),
               "risk_rationale": str(e.get("risk_rationale") or "")[:600],
               "hedge_note": str(e.get("hedge_note") or "")[:400],
               "severity": e.get("severity") if e.get("severity") in ("dispositive", "material", "marginal") else "material",
               "grounded": grounded}
        try:
            db.insert("benchmark_redline_entries", row)
            kept.append(row)
        except Exception:
            pass
    return kept, dropped


def draft_addendum(t, entries):
    grounded = [e for e in entries if e.get("grounded")]
    if not grounded:
        return None
    out = corps._json(ADDENDUM_PROMPT.format(
        filing_type=t.get("filing_type"), case_name=t.get("case_name"), court=t.get("court"),
        entries=json.dumps([{k: e.get(k) for k in ("issue", "critique", "improvement", "citations",
                                                   "risk_score", "severity")} for e in grounded])[:40000]),
        kind="review", need="chair") or {}
    if not out.get("addendum"):
        return None
    try:
        db.update("benchmark_targets", {"id": t["id"]}, {
            "addendum": str(out["addendum"])[:400000],
            "addendum_citations": json.dumps(out.get("citations") or [])[:20000],
            "outcome_prediction": json.dumps(out.get("outcome_prediction") or {})[:2000],
            "status": "commission_review",           # gate: minting is not publishing
            "process": json.dumps({"entries": len(entries), "grounded": len(grounded),
                                   "kept_from_original": (out.get("kept_from_original") or "")[:2000],
                                   "drafted_at": _now()})[:8000],
            "updated_at": _now()})
        return out
    except Exception as e:
        print(f"benchmark_redlines: addendum persist failed: {type(e).__name__}: {str(e)[:120]}")
        return None


def run(limit=BATCH):
    seeded = ensure_seeded()
    try:
        ready = db.select("benchmark_targets", {
            "select": "id,case_name,court,docket_no,vertical,filing_type,stakes,source_text,pending",
            "status": "eq.ready", "order": "priority.asc,created_at.asc", "limit": str(limit)}) or []
    except Exception:
        ready = []
    done = 0
    for t in ready:
        entries, dropped = redline_target(t)
        if dropped:
            print(f"benchmark_redlines: {dropped} entries dropped (excerpt failed verbatim check) on {t['case_name'][:60]}")
        if entries and draft_addendum(t, entries):
            done += 1
        elif entries:
            try:
                db.update("benchmark_targets", {"id": t["id"]}, {"status": "redlined", "updated_at": _now()})
            except Exception:
                pass
    out = {"seeded": seeded, "ready": len(ready), "completed": done}
    print("benchmark_redlines: " + json.dumps(out))
    return out


if __name__ == "__main__":
    # Single-instance lock for the scheduled run; `ingest` is an operator-driven one-shot
    # and stays unlocked. See lane_guard for the leak this prevents.
    if not (len(sys.argv) > 3 and sys.argv[1] == "ingest") \
            and not os.environ.get("ORCH_NO_SINGLE_INSTANCE"):
        import lane_guard
        _lock = lane_guard.guard_or_exit("benchmark_redlines", interval_s=3600)
    if len(sys.argv) > 3 and sys.argv[1] == "ingest":
        # benchmark_redlines.py ingest <target_id> <path-to-filing.txt> [url]
        with open(sys.argv[3], "r", encoding="utf-8", errors="replace") as f:
            txt = f.read()
        print(json.dumps(ingest_source(sys.argv[2], txt,
                                       sys.argv[4] if len(sys.argv) > 4 else None), indent=2))
    else:
        print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else BATCH), indent=2))
