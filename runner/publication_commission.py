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
MECHANICAL_EVIDENCE = os.environ.get("PUBCOM_MECHANICAL_EVIDENCE", "true").lower() not in ("0", "false", "no", "off")
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


def check_citations(citations, fetcher=None, limit=40):
    """Fetch every cited URL ourselves and look for the quote on the page. -> (table, counts).

    The evidence reviewer used to be given web tools and asked to open the citations — the most
    expensive call in the commission, and one that only a Claude model with tools could make. The
    bytes are a better witness than a model: each citation comes back `confirmed` (quote found on
    the page), `absent` (page opened, quote not on it), `unreachable`, or `no_quote`."""
    import pathway_lab
    if fetcher is None:
        import local_research
        fetcher = local_research.fetch
    table, counts = [], {"confirmed": 0, "absent": 0, "unreachable": 0, "no_quote": 0, "no_url": 0}
    for c in [c for c in (citations or []) if isinstance(c, dict)][:limit]:
        r = pathway_lab.verify_citation({"url": c.get("url"), "quote": c.get("quote")}, fetcher)
        status = "confirmed" if r["verified"] else (r.get("check") if r.get("check") in counts else "absent")
        counts[status] = counts.get(status, 0) + 1
        table.append({"source": str(c.get("source") or "")[:120], "url": c.get("url"), "check": status,
                      "proposition": str(c.get("proposition") or "")[:200], "quote": str(c.get("quote") or "")[:300]})
    return table, counts


def _score_local(reviewer_key, instr, body):
    """An associate-finished card is reviewed at the associate's level (operator direction 2026-09-29:
    simple matters never escalate). Local model when one fits; the spot checks in escalation.py are
    what measure whether that trust is earned."""
    import local_llm
    r = local_llm.chat("ARTIFACT:\n" + body, system=instr, json_schema=SCORE_SCHEMA, max_tokens=400, temperature=0.0,
                       timeout=600, tag=f"pubcom.{reviewer_key}.local")
    return r.get("json") if isinstance(r.get("json"), dict) and not r.get("error") else None


def _score_one(reviewer_key: str, system_prompt: str, artifact: dict) -> dict:
    """Return {'score': 0..1, 'rationale': str}. Fail-closed on any error."""
    body = json.dumps({
        "title": artifact.get("title"),
        "verdict": artifact.get("verdict"),
        "content": artifact.get("content") or "",
        "citations": artifact.get("citations") or [],
    })
    mechanical = ""
    if reviewer_key == "evidence" and MECHANICAL_EVIDENCE:
        try:
            if "_citation_check" not in artifact:
                artifact["_citation_check"] = check_citations(artifact.get("citations"))
            table, counts = artifact["_citation_check"]
            mechanical = ("\n\nMECHANICAL CHECK — our system fetched every cited URL and searched the page for the quote. "
                          "`confirmed` = the quote is on the page; `absent` = the page opened and the quote is NOT on it "
                          "(treat as a failed citation); `unreachable` = the page could not be opened (unproven, not "
                          f"failed). COUNTS: {json.dumps(counts)}\n" + json.dumps(table)[:24000]
                          + "\nScore whether the CONFIRMED quotes actually support the propositions and the memo's "
                            "material assertions, and how much of the memo rests on unconfirmed or missing authority.")
        except Exception:
            mechanical = ""
    # Never slice serialized evidence: that previously removed the citations and
    # left malformed JSON. A large record needs an explicit bounded review route.
    if len(body.encode("utf-8")) > 96000:
        return {"score": 0.0, "rationale": "review input exceeds bounded envelope", "error": "review_input_oversized"}
    if frontier is None:
        return {"score": 0.0, "rationale": "frontier unavailable — fail-closed", "error": "frontier_unavailable"}
    instr = system_prompt + "\n\nReturn ONLY JSON: {\"score\": <0.0-1.0>, \"rationale\": \"<=200 chars\"}"
    try:
        data, tier = None, "frontier"
        if artifact.get("route") == "associate":
            data, tier = _score_local(reviewer_key, instr + mechanical, body), "local"
        if data is None and reviewer_key == "risk" and frontier.codex_available():
            r = frontier.codex_complete("ARTIFACT:\n" + body, system=instr, json_schema=SCORE_SCHEMA,
                                        tag="pubcom.risk")
            data = r.get("json") if not r.get("error") else None
            tier = "codex"
        if data is None:
            tools = frontier.WEB_TOOLS if (reviewer_key == "evidence" and not mechanical) else None
            # The artifact stays a single, complete JSON document; the check table rides in the
            # instructions so nothing is ever appended to (or cut from) the evidence itself.
            r = frontier.complete("ARTIFACT:\n" + body, system=instr + mechanical + (
                "\nOpen the cited URLs with WebFetch and check that each actually supports its "
                "proposition; a citation that does not resolve or does not say what is claimed is a "
                "FAILED citation." if tools else ""),
                need=REVIEWER_TIER.get(reviewer_key, 7), tools=tools,
                max_turns=(10 if tools else 1), json_schema=SCORE_SCHEMA,
                tag=f"pubcom.{reviewer_key}")
            data = r.get("json") if not r.get("error") else None
            if data is None and r.get("text") and not r.get("error"):
                data = frontier.extract_json(r["text"])
            tier = r.get("tier") or "frontier"
        # A local completion cannot open the evidence reviewer's cited URLs. An
        # unavailable reviewer is a deferred review, not an adverse merits decision.
        if not isinstance(data, dict):
            raise ValueError("no score returned")
        score = data.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("invalid score")
        return {"score": score, "tier": tier,
                "rationale": str(data.get("rationale", ""))[:200]}
    except Exception as e:
        return {"score": 0.0, "rationale": f"scoring error (fail-closed): {type(e).__name__}", "error": "reviewer_unavailable"}


# PANEL LADDER (2026-09-29). After evidence clears its floor, ONE call scores rigor, novelty, utility and
# exposure against the same four rubrics. Only a card whose panel composite puts it within
# PANEL_MARGIN of the publication bar goes on to the separate reviewers (independent judgements and the
# cross-vendor exposure check are what publication needs). Steering and revise decisions come from the
# panel: about four reviewer calls become one for most cards. Any panel failure falls back to the
# separate reviewers, so nothing is decided on a partial answer.
PANEL = os.environ.get("PUBCOM_PANEL", "true").lower() not in ("0", "false", "no", "off")
PANEL_MARGIN = float(os.environ.get("PUBCOM_PANEL_MARGIN", "0.06"))
PANEL_KEYS = ("rigor", "novelty", "utility", "risk")
PANEL_SCHEMA = {"type": "object", "required": list(PANEL_KEYS) + ["rationale"], "properties": {
    **{k: {"type": "number"} for k in PANEL_KEYS}, "rationale": {"type": "string"}}}


def _panel(artifact: dict):
    """-> ({key: score}, rationale, tier) or None. One call, four rubrics."""
    if frontier is None:
        return None
    rubrics = "\n".join(f"- {k}: {p}" for k, _w, p in REVIEWERS if k in PANEL_KEYS)
    instr = ("You are a review panel. Score the artifact independently on each rubric, 0.0-1.0, each as if "
             "it were the only question you were asked:\n" + rubrics +
             "\nReturn ONLY JSON: {\"rigor\": n, \"novelty\": n, \"utility\": n, \"risk\": n, "
             "\"rationale\": \"<=300 chars, the weakest point first\"}")
    body = json.dumps({"title": artifact.get("title"), "verdict": artifact.get("verdict"),
                       "content": artifact.get("content") or "", "citations": artifact.get("citations") or []})
    if len(body.encode("utf-8")) > 96000:
        return None
    try:
        if artifact.get("route") == "associate":
            import local_llm
            r = local_llm.chat("ARTIFACT:\n" + body, system=instr, json_schema=PANEL_SCHEMA, max_tokens=600,
                               temperature=0.0, timeout=900, tag="pubcom.panel.local")
            tier = "local"
        else:
            r = frontier.complete("ARTIFACT:\n" + body, system=instr, need=8, max_turns=1, json_schema=PANEL_SCHEMA,
                                  tag="pubcom.panel")
            tier = r.get("tier") or "frontier"
        data = r.get("json") if not r.get("error") else None
        if data is None and r.get("text") and not r.get("error"):
            data = frontier.extract_json(r["text"])
        if not isinstance(data, dict):
            return None
        out = {}
        for k in PANEL_KEYS:
            v = data.get(k)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1:
                return None
            out[k] = float(v)
        return out, str(data.get("rationale", ""))[:300], tier
    except Exception:
        return None


def review_artifact(artifact: dict) -> dict:
    """Run the full commission over one artifact. Returns the decision record."""
    scores, rationales, tiers = {}, {}, {}
    # MECHANICAL PRE-SCREEN (associate level). If not one cited quote is on its page and at least two
    # pages opened without the quote, the evidence has failed on the bytes; no reviewer is paid to say so.
    if MECHANICAL_EVIDENCE and artifact.get("citations"):
        try:
            if "_citation_check" not in artifact:
                artifact["_citation_check"] = check_citations(artifact.get("citations"))
            _, counts = artifact["_citation_check"]
            if counts.get("confirmed", 0) == 0 and counts.get("absent", 0) >= 2:
                return {"artifact_id": artifact.get("id"), "artifact_type": artifact.get("type", "committee_opinion"),
                        "composite": 0.0, "steer_composite": 0.0, "scores": {"evidence": 0.0},
                        "rationales": {"evidence": f"mechanical: no cited quote found on its page ({json.dumps(counts)})"},
                        "veto": "evidence floor", "posture": "standard", "publication_blocked": False,
                        "gate": GATE_VERSION, "short_circuit": True, "mechanical": True, "tiers": {"evidence": "mechanical"},
                        "provisional": False, "decision": "reject", "publish_bar": PUBLISH_BAR, "steer_bar": STEER_BAR,
                        "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        except Exception:
            pass
    # EVIDENCE FIRST (2026-09-28). Grounding is the one floor that rejects on every track, so it is
    # scored first and an ungrounded card stops there. The commission had been spending five
    # frontier reviewers on each of 50 cards that the evidence reviewer alone would have rejected.
    order = sorted(REVIEWERS, key=lambda r: 0 if r[0] == "evidence" else 1)
    ladder, panel_tried = "separate", False
    for key, _w, prompt in order:
        if key != "evidence" and PANEL and not panel_tried and "evidence" in scores:
            panel_tried = True
            p = _panel(artifact)
            if p is not None:
                pscores, prat, ptier = p
                trial = decide({**scores, **pscores})
                if trial["composite"] < PUBLISH_BAR - PANEL_MARGIN or trial["publication_blocked"]:
                    for k in PANEL_KEYS:
                        scores[k], rationales[k], tiers[k] = pscores[k], "panel: " + prat, ptier
                    ladder = "panel"
                    break
                ladder = "panel_then_separate"       # a publication candidate: independent reviewers decide
        r = _score_one(key, prompt, artifact)
        if r.get("error"):
            return {"artifact_id": artifact.get("id"), "artifact_type": artifact.get("type", "committee_opinion"),
                    "decision": "deferred", "reason": r["error"]}
        scores[key] = r["score"]
        rationales[key] = r["rationale"]
        tiers[key] = r.get("tier") or "frontier"
        if key == "evidence" and r["score"] < EVIDENCE_FLOOR:
            return {"artifact_id": artifact.get("id"), "artifact_type": artifact.get("type", "committee_opinion"),
                    "composite": round(r["score"] * dict((k, w) for k, w, _ in REVIEWERS)["evidence"], 4),
                    "steer_composite": round(r["score"] * STEER_WEIGHTS["evidence"], 4),
                    "scores": scores, "rationales": rationales, "veto": "evidence floor",
                    "posture": "standard", "publication_blocked": False, "gate": GATE_VERSION,
                    "short_circuit": True, "decision": "reject", "publish_bar": PUBLISH_BAR,
                    "tiers": tiers, "provisional": "local" in tiers.values(),
                    "steer_bar": STEER_BAR, "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    gate = decide(scores)
    associate_final = artifact.get("route") == "associate"
    if associate_final:
        tiers = {k: "local" for k in tiers} if not tiers else tiers
    # PROVISIONAL (2026-09-29, never-idle). A reviewer that answered on the LOCAL tier keeps the
    # commission moving while the cloud tiers are down, but it may not open publication, and its
    # adverse findings do not withdraw a card. The review is redone when a cloud reviewer is back.
    provisional = "local" in tiers.values() or associate_final
    if provisional and gate["decision"] == "publish":
        gate = {**gate, "decision": "steer_only"}
    return {
        "tiers": tiers, "provisional": provisional, "associate_final": associate_final, "ladder": ladder,
        "artifact_id": artifact.get("id"),
        "artifact_type": artifact.get("type", "committee_opinion"),
        "composite": gate["composite"],
        "steer_composite": gate["steer_composite"],
        "scores": scores,
        "rationales": rationales,
        "veto": gate["veto"],
        "posture": gate["posture"],
        "publication_blocked": gate["publication_blocked"],
        "gate": GATE_VERSION,
        "decision": gate["decision"],
        "publish_bar": PUBLISH_BAR,
        "steer_bar": STEER_BAR,
        "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# ── the gate ─────────────────────────────────────────────────────────────────────────────────────
# TWO TRACKS (operator direction 2026-09-28: "allow for more flexibility and creative risk taking").
# The first gate used ONE composite and TWO vetoes for two different uses. The exposure reviewer asks
# "would PUBLISHING this embarrass or endanger the publisher?" — and a low answer withdrew the card
# from INTERNAL STEERING as well. Six frontier cards with evidence 0.78-0.87 and utility 0.78-0.90
# were withdrawn for being "too directive to publish", which is precisely what an internal steering
# memo is supposed to be.
#
#   STEERING track   rigor, evidence, utility, novelty. Exposure does not enter. A card that is
#                    grounded and reasoned steers, however directive it is.
#   PUBLICATION track the full five-reviewer composite, and exposure must clear its floor.
#   EXPLORATORY      a genuinely novel position (novelty >= EXPLORE_NOVELTY) with sound evidence but
#                    a lower overall score is kept for steering, labelled exploratory, instead of
#                    being sent back — creative, untested reasoning is the point of a tribunal, and
#                    an attorney still reviews it before anything leaves the building.
#
# What did NOT loosen: the evidence floor. A card whose citations do not resolve or do not say what is
# claimed is rejected on either track. Risk-taking is about the position, never about the grounding.
GATE_VERSION = "two_track/2026-09-28"
STEER_WEIGHTS = {"rigor": 0.30, "evidence": 0.30, "utility": 0.25, "novelty": 0.15}
EVIDENCE_FLOOR = float(os.environ.get("PUBCOM_EVIDENCE_FLOOR", "0.40"))
RIGOR_FLOOR = float(os.environ.get("PUBCOM_RIGOR_FLOOR", "0.30"))
EXPOSURE_FLOOR = float(os.environ.get("PUBCOM_EXPOSURE_FLOOR", "0.40"))
EXPLORE_NOVELTY = float(os.environ.get("PUBCOM_EXPLORE_NOVELTY", "0.60"))
EXPLORE_EVIDENCE = float(os.environ.get("PUBCOM_EXPLORE_EVIDENCE", "0.50"))


def decide(scores: dict) -> dict:
    """Pure: reviewer scores -> decision. Used for new reviews and for re-gating stored ones."""
    g = lambda k: float(scores.get(k, 0) or 0)   # noqa: E731
    composite = round(sum(g(k) * w for k, w, _ in REVIEWERS), 4)
    steer = round(sum(g(k) * w for k, w in STEER_WEIGHTS.items()), 4)
    publication_blocked = g("risk") < EXPOSURE_FLOOR
    veto, posture = None, "standard"
    if g("evidence") < EVIDENCE_FLOOR:
        veto, decision = "evidence floor", "reject"
    elif composite >= PUBLISH_BAR and not publication_blocked:
        decision = "publish"
    elif steer >= STEER_BAR and g("rigor") >= RIGOR_FLOOR:
        decision = "steer_only"
    elif g("novelty") >= EXPLORE_NOVELTY and g("rigor") >= RIGOR_FLOOR and g("evidence") >= EXPLORE_EVIDENCE:
        decision, posture = "steer_only", "exploratory"
    else:
        decision = "revise"
    return {"decision": decision, "composite": composite, "steer_composite": steer, "veto": veto,
            "posture": posture, "publication_blocked": bool(publication_blocked and decision != "reject")}


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
    # Provisional (local-tier) reviews are redone as soon as a cloud reviewer can take them.
    if frontier is not None and getattr(frontier, "available", lambda **k: False)(min_tokens=20000):
        for r in reviews:
            d = _loads(r.get("detail"), {})
            if (r.get("artifact_type") == "verdict_card" and isinstance(d, dict) and d.get("provisional") is True
                    and not d.get("associate_final")):          # associate finals are sampled by spot checks instead
                repaired.setdefault(r.get("artifact_id"), {**r, "_provisional": True})
    done = {r.get("artifact_id") for r in reviews if r.get("artifact_id") not in repaired}
    out = []
    cards = db.select("verdict_cards", {
        "select": "id,vertical,question,verdict,position,citations,assumptions,dissent,flips_if,"
                  "conditions,unsettled,confidence,publication_state,status,minted_at,process",
        "status": "eq.fresh", "publication_state": "eq.internal",
        "order": "minted_at.desc", "limit": str(limit * 3)}) or []
    prov_ids = [k for k, v in repaired.items() if v.get("_provisional")]
    if prov_ids:
        extra = db.select("verdict_cards", {
            "select": "id,vertical,question,verdict,position,citations,assumptions,dissent,flips_if,"
                      "conditions,unsettled,confidence,publication_state,status,minted_at,process",
            "id": f"in.({','.join(prov_ids[:50])})", "publication_state": "in.(internal,attorney_review)"}) or []
        have = {c.get("id") for c in cards}
        cards = [c for c in extra if c.get("id") not in have] + cards
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
                    "citations": _loads(c.get("citations"), []),
                    "route": (_loads(c.get("process"), {}) or {}).get("route")}
        if c.get("id") in repaired and repaired[c.get("id")].get("_provisional"):
            prior = {k: v for k, v in repaired[c.get("id")].items() if k != "_provisional"}
            candidate["prior_review"] = prior
        elif c.get("id") in repaired:
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
                      "tiers": rec.get("tiers"), "provisional": bool(rec.get("provisional")),
                      "associate_final": bool(rec.get("associate_final")), "ladder": rec.get("ladder"),
                      "reviewed_at": rec["reviewed_at"], "gate": rec.get("gate"),
                      "steer_composite": rec.get("steer_composite"), "posture": rec.get("posture"),
                      "publication_blocked": rec.get("publication_blocked")}
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
                state = CARD_STATE.get(rec["decision"], "internal")
                if rec.get("provisional") and rec["decision"] in ("reject", "revise"):
                    state = "internal"          # a local-tier verdict never withdraws a card
                db.update("verdict_cards", {"id": rec["artifact_id"]}, {"publication_state": state})
            except Exception as e:
                tally["persist_failed"] += 1
                print(f"publication_commission: card state update failed for {rec['artifact_id']}: {e}")
        print(f"publication_commission: {rec['artifact_type']} {str(rec['artifact_id'])[:8]} -> "
              f"{rec['decision']} (composite {rec['composite']}, veto={rec['veto']})", flush=True)
    print("publication_commission: " + json.dumps(tally))
    return tally


def regate(apply=False, limit=2000) -> dict:
    """Re-decide STORED reviews under the current gate, from their stored scores. No model calls.

    A card moves only when its decision changes AND its publication_state is still the one the old
    decision put it in — a card a human has since published or moved is never touched."""
    rows = db.select("publication_reviews", {
        "select": "id,created_at,artifact_id,artifact_type,decision,composite,detail",
        "artifact_type": "eq.verdict_card", "order": "created_at.desc", "limit": str(limit)}) or []
    tally = {"examined": 0, "changed": 0, "restored_to_steering": 0, "unchanged": 0, "skipped_state": 0,
             "applied": bool(apply), "changes": []}
    for r in rows:
        det = _loads(r.get("detail"), {}) or {}
        scores = det.get("scores") or {}
        if not scores:
            continue
        tally["examined"] += 1
        new = decide(scores)
        if new["decision"] == r.get("decision"):
            tally["unchanged"] += 1
            continue
        cards = db.select("verdict_cards", {"select": "id,publication_state,status", "id": f"eq.{r['artifact_id']}",
                                            "limit": "1"}) or []
        if not cards or cards[0].get("publication_state") != CARD_STATE.get(r.get("decision")):
            tally["skipped_state"] += 1
            continue
        tally["changed"] += 1
        change = {"card": str(r["artifact_id"])[:8], "from": r.get("decision"), "to": new["decision"],
                  "steer_composite": new["steer_composite"], "posture": new["posture"],
                  "publication_blocked": new["publication_blocked"]}
        tally["changes"].append(change)
        if new["decision"] in ("steer_only", "publish") and r.get("decision") in ("reject", "revise"):
            tally["restored_to_steering"] += 1
        if not apply:
            continue
        det.update({"gate": GATE_VERSION, "steer_composite": new["steer_composite"], "posture": new["posture"],
                    "publication_blocked": new["publication_blocked"], "veto": new["veto"],
                    "regated": {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "previous_decision": r.get("decision"), "previous_veto": det.get("veto")}})
        try:
            db.update("publication_reviews", {"id": r["id"]}, {"decision": new["decision"], "detail": det})
            db.update("verdict_cards", {"id": r["artifact_id"]},
                      {"publication_state": CARD_STATE.get(new["decision"], "internal")})
        except Exception as e:
            print(f"publication_commission: regate failed for {r['artifact_id']}: {e}")
    print("publication_commission regate: " + json.dumps({k: v for k, v in tally.items() if k != "changes"}))
    return tally


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "regate":
        print(json.dumps(regate(apply="--apply" in sys.argv), indent=2))
    else:
        print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 else BATCH), indent=2))
