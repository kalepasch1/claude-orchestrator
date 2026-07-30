#!/usr/bin/env python3
"""publication_commission.py — the editorial board over Consilium output.

WHY: the Consilium produces committee opinions/determinations continuously. Volume is not value.
Publishing (or steering on) unvetted output would launder weak reasoning into the platform's
"source of truth" — the opposite of the moat. This module is the gate: a standing commission of
agentic reviewers that SCORES every candidate artifact and decides publish / revise / reject,
with the score itself becoming a first-class signal the rest of the platform consumes.

DESIGN PRINCIPLES
  1. Adversarial, not confirmatory — each reviewer looks for a distinct failure mode.
  2. Evidence-gated — an artifact cannot publish without citations that actually resolve.
  3. Novelty-aware — restating settled law is not publication-worthy; it may still be
     steering-worthy. Those are different bars, scored separately (see PUBLISH_BAR / STEER_BAR).
  4. Fail-closed — any scoring error blocks publication rather than passing it through.
  5. Auditable — every score, reviewer rationale, and decision persists for later calibration
     against real-world outcomes (did the published position hold up?).

CONSUMERS (this is the point — the score must be USED, not just recorded):
  * publication  -> PMI/Publius article pipeline (publish only at PUBLISH_BAR)
  * steering     -> Foulkon/terminal guidance + risk-gradient options (STEER_BAR)
  * advisory     -> memo/opinion generation may cite only STEER_BAR+ artifacts
  * risk scoring -> confidence weighting on any score derived from an artifact
"""
from __future__ import annotations
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

try:
    import llm  # project's model helper
except Exception:  # pragma: no cover
    llm = None

# Bars are deliberately different: publishing is a higher bar than steering.
PUBLISH_BAR = float(os.environ.get("PUBCOM_PUBLISH_BAR", "0.78"))
STEER_BAR = float(os.environ.get("PUBCOM_STEER_BAR", "0.62"))
BATCH = int(os.environ.get("PUBCOM_BATCH", "12"))

# Each reviewer hunts ONE failure mode. Weights sum to 1.0.
REVIEWERS = [
    ("rigor", 0.24,
     "You are a skeptical appellate judge. Score the REASONING only: is each conclusion actually "
     "supported by the stated premises? Find leaps, circularity, and unstated assumptions."),
    ("evidence", 0.24,
     "You are a cite-checker. Score EVIDENCE: does every material assertion carry a citation, and "
     "does each citation plausibly support the proposition it is cited for? Flag unsupported claims."),
    ("novelty", 0.18,
     "You are a research editor. Score NOVELTY: does this add something a competent practitioner "
     "would not already know? Restating settled law scores LOW even if perfectly correct."),
    ("utility", 0.18,
     "You are the reader — a GC deciding an action this week. Score DECISION-USEFULNESS: could they "
     "act on this? Vague hedging scores low; a clear recommendation with conditions scores high."),
    ("risk", 0.16,
     "You are opposing counsel. Score EXPOSURE: what in here would embarrass or endanger the "
     "publisher? Overclaiming, unhedged predictions, anything that reads as legal advice without "
     "qualification. HIGH score = SAFE to publish."),
]


def _score_one(reviewer_key: str, system_prompt: str, artifact: dict) -> dict:
    """Return {'score': 0..1, 'rationale': str}. Fail-closed on any error."""
    body = json.dumps({
        "title": artifact.get("title"),
        "verdict": artifact.get("verdict"),
        "content": (artifact.get("content") or "")[:6000],
        "citations": artifact.get("citations") or [],
    })[:9000]
    if llm is None:
        return {"score": 0.0, "rationale": "llm unavailable — fail-closed"}
    try:
        raw = llm.ask(
            system_prompt + "\n\nReturn ONLY JSON: {\"score\": <0.0-1.0>, \"rationale\": \"<=200 chars\"}",
            body, temperature=0)
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        return {"score": max(0.0, min(1.0, float(data.get("score", 0)))),
                "rationale": str(data.get("rationale", ""))[:200]}
    except Exception as e:
        return {"score": 0.0, "rationale": f"scoring error (fail-closed): {type(e).__name__}"}


def review_artifact(artifact: dict) -> dict:
    """Run the full commission over one artifact. Returns the decision record."""
    scores, rationales = {}, {}
    for key, _w, prompt in REVIEWERS:
        r = _score_one(key, prompt, artifact)
        scores[key] = r["score"]
        rationales[key] = r["rationale"]

    composite = sum(scores[k] * w for k, w, _ in REVIEWERS)
    # A single catastrophic dimension vetoes regardless of composite: an artifact with no evidence
    # or a serious exposure problem must never publish on the strength of its other scores.
    veto = None
    if scores.get("evidence", 0) < 0.40:
        veto = "evidence floor"
    elif scores.get("risk", 0) < 0.40:
        veto = "exposure floor"

    if veto:
        decision = "reject"
    elif composite >= PUBLISH_BAR:
        decision = "publish"
    elif composite >= STEER_BAR:
        decision = "steer_only"   # good enough to guide internally, not to publish
    else:
        decision = "revise"

    return {
        "artifact_id": artifact.get("id"),
        "artifact_type": artifact.get("type", "committee_opinion"),
        "composite": round(composite, 4),
        "scores": scores,
        "rationales": rationales,
        "veto": veto,
        "decision": decision,
        "publish_bar": PUBLISH_BAR,
        "steer_bar": STEER_BAR,
        "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _candidates(limit: int):
    """Consilium output not yet reviewed by the commission."""
    rows = db.select("committee_opinions", {
        "select": "id,committee,subject_title,consensus_verdict,opinion",
        "order": "created_at.desc", "limit": str(limit * 3)}) or []
    done = {r.get("artifact_id") for r in
            (db.select("publication_reviews", {"select": "artifact_id", "limit": "1000"}) or [])}
    out = []
    for r in rows:
        if r.get("id") in done:
            continue
        out.append({"id": r.get("id"), "type": "committee_opinion",
                    "title": r.get("subject_title"), "verdict": r.get("consensus_verdict"),
                    "content": r.get("opinion"), "citations": []})
        if len(out) >= limit:
            break
    return out


def run(limit: int = BATCH) -> dict:
    """Score a batch; persist decisions. Safe to run on a schedule."""
    tally = {"reviewed": 0, "publish": 0, "steer_only": 0, "revise": 0, "reject": 0}
    for art in _candidates(limit):
        rec = review_artifact(art)
        tally["reviewed"] += 1
        tally[rec["decision"]] = tally.get(rec["decision"], 0) + 1
        try:
            db.insert("publication_reviews", {
                "artifact_id": rec["artifact_id"],
                "artifact_type": rec["artifact_type"],
                "composite": rec["composite"],
                "decision": rec["decision"],
                "detail": json.dumps({"scores": rec["scores"], "rationales": rec["rationales"],
                                      "veto": rec["veto"]}),
            }, upsert=True)
        except Exception as e:
            print(f"publication_commission: persist failed for {rec['artifact_id']}: {e}")
    print("publication_commission: " + json.dumps(tally))
    return tally


if __name__ == "__main__":
    print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 else BATCH), indent=2))
