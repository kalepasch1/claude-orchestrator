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
import hashlib
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# 2026-09-11: this module imported a `llm` helper that does not exist in the repo, so every
# reviewer failed closed with "llm unavailable" and the commission never scored a single
# artifact (publication_reviews was empty after six weeks of Consilium output). Reviewers now
# route through frontier.py: rigor on Fable 5.1, evidence on Opus 5 WITH WebFetch so it can open
# the cited URLs, novelty/utility on the mid tier, exposure on the cross-vendor model (GPT-5.5)
# when available. Fail-closed semantics are unchanged: a scoring error still blocks publication.
try:
    import frontier
except Exception:  # pragma: no cover
    frontier = None

REVIEWER_TIER = {"rigor": 9, "evidence": 8, "novelty": 7, "utility": 6, "risk": 7}
SCORE_SCHEMA = {"type": "object", "properties": {"score": {"type": "number"}, "rationale": {"type": "string"}},
                "required": ["score", "rationale"]}

# Bars are deliberately different: publishing is a higher bar than steering.
PUBLISH_BAR = float(os.environ.get("PUBCOM_PUBLISH_BAR", "0.78"))
STEER_BAR = float(os.environ.get("PUBCOM_STEER_BAR", "0.62"))
BATCH = int(os.environ.get("PUBCOM_BATCH", "12"))
# 2026-09-12: the commission spent its afternoon scoring 8B-era cards with fabricated citations
# (24 reviews, 24 rejects, ~10K weighted tokens each). Only cards whose process names this engine
# are worth five frontier reviewers; set PUBCOM_ENGINE_FILTER="" to score everything again.
ENGINE_FILTER = os.environ.get("PUBCOM_ENGINE_FILTER", "consilium_v2")

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
        "content": artifact.get("content") or "",
        "citations": artifact.get("citations") or [],
    })
    # Never slice serialized evidence: that previously removed the citations and
    # left malformed JSON. A large record needs an explicit bounded review route.
    if len(body.encode("utf-8")) > 96000:
        return {"score": 0.0, "rationale": "review input exceeds bounded envelope", "error": "review_input_oversized"}
    if frontier is None:
        return {"score": 0.0, "rationale": "frontier unavailable — fail-closed", "error": "frontier_unavailable"}
    instr = system_prompt + "\n\nReturn ONLY JSON: {\"score\": <0.0-1.0>, \"rationale\": \"<=200 chars\"}"
    try:
        data = None
        if reviewer_key == "risk" and frontier.codex_available():
            r = frontier.codex_complete("ARTIFACT:\n" + body, system=instr, json_schema=SCORE_SCHEMA,
                                        tag="pubcom.risk")
            data = r.get("json") if not r.get("error") else None
        if data is None:
            tools = frontier.WEB_TOOLS if reviewer_key == "evidence" else None
            r = frontier.complete("ARTIFACT:\n" + body, system=instr + (
                "\nOpen the cited URLs with WebFetch and check that each actually supports its "
                "proposition; a citation that does not resolve or does not say what is claimed is a "
                "FAILED citation." if tools else ""),
                need=REVIEWER_TIER.get(reviewer_key, 7), tools=tools,
                max_turns=(10 if tools else 1), json_schema=SCORE_SCHEMA,
                tag=f"pubcom.{reviewer_key}")
            data = r.get("json") if not r.get("error") else None
            if data is None and r.get("text") and not r.get("error"):
                data = frontier.extract_json(r["text"])
        # A local completion cannot open the evidence reviewer's cited URLs. An
        # unavailable reviewer is a deferred review, not an adverse merits decision.
        if not isinstance(data, dict):
            raise ValueError("no score returned")
        score = data.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("invalid score")
        return {"score": score,
                "rationale": str(data.get("rationale", ""))[:200]}
    except Exception as e:
        return {"score": 0.0, "rationale": f"scoring error (fail-closed): {type(e).__name__}", "error": "reviewer_unavailable"}


def review_artifact(artifact: dict) -> dict:
    """Run the full commission over one artifact. Returns the decision record."""
    scores, rationales = {}, {}
    for key, _w, prompt in REVIEWERS:
        r = _score_one(key, prompt, artifact)
        if r.get("error"):
            return {"artifact_id": artifact.get("id"), "artifact_type": artifact.get("type", "committee_opinion"),
                    "decision": "deferred", "reason": r["error"]}
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


def _loads(v, default):
    try:
        return json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    except Exception:
        return default


def _candidates(limit: int):
    """Consilium output not yet reviewed by the commission. VERDICT CARDS FIRST (2026-09-11):
    they are the artifacts that steer Foulkon and feed papers, and the old query never looked at
    them at all — it only scored engineering-committee opinions."""
    reviews = db.select("publication_reviews", {"select": "id,artifact_id,artifact_type,decision,composite,detail,created_at", "limit": "5000"}) or []
    # A verified transport repair is not a merits reversal. Keep the old review
    # and its reasons, but permit one fresh review of the now-readable evidence.
    repaired = {r.get("artifact_id"): r for r in reviews
                if r.get("artifact_type") == "verdict_card"
                and isinstance(_loads(r.get("detail"), {}), dict)
                and _loads(r.get("detail"), {}).get("requires_rereview") is True}
    done = {r.get("artifact_id") for r in reviews if r.get("artifact_id") not in repaired}
    out = []
    cards = db.select("verdict_cards", {
        "select": "id,vertical,question,verdict,position,citations,assumptions,dissent,flips_if,"
                  "conditions,unsettled,confidence,publication_state,status,minted_at,process",
        "status": "eq.fresh", "publication_state": "eq.internal",
        "order": "minted_at.desc", "limit": str(limit * 3)}) or []
    for c in cards:
        if c.get("id") in done:
            continue
        if ENGINE_FILTER and ENGINE_FILTER not in str(c.get("process") or ""):
            continue
        content = (f"POSITION:\n{c.get('position') or ''}\n\nDISSENT: {c.get('dissent') or 'none'}\n"
                   f"FLIPS IF: {c.get('flips_if') or ''}\nCONDITIONS: {c.get('conditions') or ''}\n"
                   f"UNSETTLED: {c.get('unsettled')}\nASSUMPTIONS: {_loads(c.get('assumptions'), [])}")
        candidate = {"id": c.get("id"), "type": "verdict_card", "title": c.get("question"),
                    "verdict": c.get("verdict"), "content": content,
                    "citations": _loads(c.get("citations"), [])}
        if c.get("id") in repaired:
            prior = repaired[c.get("id")]
            detail = _loads(prior.get("detail"), {})
            digest = hashlib.sha256(json.dumps(candidate["citations"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if detail.get("repaired_citations_sha256") != digest:
                continue  # repair receipt does not describe this evidence version
            candidate["prior_review"] = prior
        out.append(candidate)
        if len(out) >= limit:
            return out
    rows = db.select("committee_opinions", {
        "select": "id,committee,subject_title,consensus_verdict,opinion,citations",
        "order": "created_at.desc", "limit": str(limit * 3)}) or []
    for r in rows:
        if r.get("id") in done:
            continue
        out.append({"id": r.get("id"), "type": "committee_opinion",
                    "title": r.get("subject_title"), "verdict": r.get("consensus_verdict"),
                    "content": r.get("opinion"), "citations": _loads(r.get("citations"), [])})
        if len(out) >= limit:
            break
    return out


#: verdict_cards.publication_state after a commission decision. "internal" is the unreviewed
#: state; nothing reaches a customer until commission_passed AND an attorney sign-off.
# Match the deployed state machine. Passing the model commission only requests
# attorney review; it never creates publication or customer-steering authority.
CARD_STATE = {"publish": "attorney_review", "steer_only": "attorney_review",
              "revise": "commission_review", "reject": "withdrawn"}


def run(limit: int = BATCH) -> dict:
    """Score a batch; persist decisions. Safe to run on a schedule."""
    tally = {"reviewed": 0, "publish": 0, "steer_only": 0, "revise": 0, "reject": 0, "deferred": 0, "persist_failed": 0}
    for art in _candidates(limit):
        rec = review_artifact(art)
        if rec["decision"] == "deferred":
            tally["deferred"] += 1
            # Do not spend four more reviewers when the first cannot execute.
            break
        try:
            detail = {"scores": rec["scores"], "rationales": rec["rationales"], "veto": rec["veto"],
                      "reviewed_at": rec["reviewed_at"]}
            prior = art.get("prior_review")
            if prior:
                # Preserve the exact prior verdict and repair provenance; do not
                # overwrite the only evidence that the original review failed.
                detail["previous_review"] = prior
                if len(json.dumps(detail).encode()) > 32000:
                    raise RuntimeError("review history requires archival")
            row = {
                "artifact_id": rec["artifact_id"],
                "artifact_type": rec["artifact_type"],
                "composite": rec["composite"],
                "decision": rec["decision"],
                "detail": detail,
            }
            if prior:
                row["created_at"] = rec["reviewed_at"]
            saved = (db.update("publication_reviews", {"id": prior["id"], "created_at": prior["created_at"]}, row)
                     if prior else db.insert("publication_reviews", row, upsert=True))
            if not saved:
                raise RuntimeError("review persistence unconfirmed")
        except Exception as e:
            tally["persist_failed"] += 1
            print(f"publication_commission: persist failed for {rec['artifact_id']}: {e}")
            continue
        tally["reviewed"] += 1
        tally[rec["decision"]] = tally.get(rec["decision"], 0) + 1
        if rec["artifact_type"] == "verdict_card":
            try:
                db.update("verdict_cards", {"id": rec["artifact_id"]},
                          {"publication_state": CARD_STATE.get(rec["decision"], "internal")})
            except Exception as e:
                tally["persist_failed"] += 1
                print(f"publication_commission: card state update failed for {rec['artifact_id']}: {e}")
        print(f"publication_commission: {rec['artifact_type']} {str(rec['artifact_id'])[:8]} -> "
              f"{rec['decision']} (composite {rec['composite']}, veto={rec['veto']})", flush=True)
    print("publication_commission: " + json.dumps(tally))
    return tally


if __name__ == "__main__":
    print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 else BATCH), indent=2))
