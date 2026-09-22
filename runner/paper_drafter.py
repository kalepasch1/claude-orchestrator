#!/usr/bin/env python3
"""paper_drafter.py — turn commission-passed verdict cards into REVIEW-ONLY paper drafts.

THE GAP (2026-09-11). 312 verdict cards had been minted and zero had ever become an article,
because (a) the commission that gates publication had never scored anything (dead `llm`
import) and (b) nothing consumed a passing score. This is the consumer: for each card the
commission marked `publish` — or `steer_only` with a strong novelty score — Fable 5.1 drafts
a full long-form piece in the Apparently Law / PMI voice, re-opening the cited sources so the
draft carries live URLs, and the draft lands as an `approvals` packet (the same review queue
editorial_program.py uses) plus a markdown file under docs/consilium/papers/.

IT NEVER PUBLISHES. Same gate as everything else: commission_review -> attorney_review ->
published. The packet is a draft with a banner; a human approves or discards it. The hedge
note is one quiet line (operator ask, see benchmark_redlines.py) and only where a Tomorrow
hedge on the issue is plausible; otherwise omitted.
"""
from __future__ import annotations
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import common_utils
import frontier

_s = common_utils.safe_string_coerce
BATCH = int(os.environ.get("ORCH_PAPER_BATCH", "2"))
NOVELTY_FLOOR = float(os.environ.get("ORCH_PAPER_NOVELTY_FLOOR", "0.72"))
PROJECT = os.environ.get("ORCH_PAPER_PROJECT", "apparently-law")
PAPERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "consilium", "papers")

SCHEMA = {"type": "object", "properties": {
    "title": {"type": "string"}, "dek": {"type": "string"}, "audience": {"type": "string"},
    "abstract": {"type": "string"}, "body_markdown": {"type": "string"},
    "what_to_do_this_week": {"type": "array", "items": {"type": "string"}},
    "forecast": {"type": "object", "properties": {
        "statement": {"type": "string"}, "probability": {"type": "number"}, "by": {"type": "string"}},
        "required": ["statement", "probability", "by"]},
    "hedge_note": {"type": "string"},
    "citations": {"type": "array", "items": {"type": "object", "properties": {
        "source": {"type": "string"}, "url": {"type": "string"}, "verified": {"type": "boolean"},
        "quote": {"type": "string"}}, "required": ["source", "url", "verified", "quote"]}},
    "novelty_claim": {"type": "string"}, "risk_flags": {"type": "array", "items": {"type": "string"}}},
    "required": ["title", "dek", "audience", "abstract", "body_markdown", "what_to_do_this_week",
                 "forecast", "hedge_note", "citations", "novelty_claim", "risk_flags"]}

SYSTEM = """You are the senior writer for Apparently Law (AI-native regulatory counsel for gaming, regulated
finance and AI/data) and the Prediction Markets Institute ("What if tomorrow was predictable?").
You turn a pre-debated, citation-backed verdict card into a publishable long-form piece for
General Counsels and founders. Standards:
 * Lead with the answer. A GC gives you thirty seconds.
 * Reason on the record: the operative rule -> application -> limits -> what would flip it.
 * Preserve the dissent honestly; a piece that hides its strongest objection is not credible.
 * Every material assertion carries a citation with a URL you OPENED (WebFetch) and a verbatim
   quote of at most 40 words; re-verify the card's citations rather than trusting them; drop any
   that do not resolve and say so in risk_flags.
 * Include a dated, probabilistic forecast — the house style is to publish forecasts and be scored.
 * 1,500-3,000 words of body_markdown, headed sections, no filler. Plain English, no hedged mush.
 * This is commentary on public law for a general professional audience, not legal advice; say so
   once, briefly, at the end. Never name a living person as an expert seat.
 * hedge_note: ONE quiet sentence framing what an adverse-outcome hedge on this issue would look
   like on Tomorrow, only if genuinely plausible; otherwise an empty string.
Return ONLY the JSON object matching the schema."""

USER = """VERDICT CARD (pre-debated by the Consilium, {citations_n} citations, red team severity {red}):
QUESTION: {question}
VERDICT: {verdict}
POSITION:
{position}

DISSENT: {dissent}
FLIPS IF: {flips_if}
CONDITIONS: {conditions}
UNSETTLED: {unsettled}
ASSUMPTIONS: {assumptions}
CITATIONS (JSON): {citations}
COMMISSION SCORES: {scores}
TODAY: {today}

Draft the piece now."""


def _loads(v, default):
    try:
        return json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    except Exception:
        return default


def _slug(text, n=60):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:n] or "paper"


def _candidates(limit):
    revs = db.select("publication_reviews", {
        "select": "artifact_id,decision,composite,detail,created_at", "artifact_type": "eq.verdict_card",
        "decision": "in.(publish,steer_only)", "order": "composite.desc", "limit": "200"}) or []
    out = []
    for rv in revs:
        det = _loads(rv.get("detail"), {})
        scores = (det or {}).get("scores") or {}
        if rv.get("decision") == "steer_only" and float(scores.get("novelty") or 0) < NOVELTY_FLOOR:
            continue
        slug = f"paper:{rv.get('artifact_id')}"
        if db.select("approvals", {"select": "id", "slug": f"eq.{slug}", "limit": "1"}):
            continue
        cards = db.select("verdict_cards", {"select": "*", "id": f"eq.{rv.get('artifact_id')}", "limit": "1"}) or []
        if not cards:
            continue
        out.append((cards[0], rv, scores))
        if len(out) >= limit:
            break
    return out


def draft(card, review, scores):
    cites = _loads(card.get("citations"), [])
    proc = _loads(card.get("process"), {})
    r = frontier.complete(USER.format(
        citations_n=len(cites) if isinstance(cites, list) else 0,
        red=(proc or {}).get("red_team_severity"),
        question=_s(card.get("question"))[:1500], verdict=_s(card.get("verdict"))[:800],
        position=_s(card.get("position"))[:11000], dissent=_s(card.get("dissent"))[:2500],
        flips_if=_s(card.get("flips_if"))[:1200], conditions=_s(card.get("conditions"))[:1200],
        unsettled=card.get("unsettled"), assumptions=json.dumps(_loads(card.get("assumptions"), []))[:2000],
        citations=json.dumps(cites)[:7000], scores=json.dumps(scores),
        today=datetime.date.today().isoformat()),
        system=SYSTEM, need=9, tools=frontier.WEB_TOOLS, max_turns=18, json_schema=SCHEMA,
        timeout=1500, tag="paper_drafter.draft")
    j = r.get("json")
    if r.get("error") or not isinstance(j, dict) or not j.get("body_markdown"):
        print(f"paper_drafter: draft failed for {card.get('id')}: {r.get('error') or 'malformed'}", flush=True)
        return None
    j["_model"] = r.get("model"); j["_tokens"] = (r.get("tokens_in"), r.get("tokens_out"))
    return j


def _markdown(card, review, j):
    today = datetime.date.today().isoformat()
    cites = j.get("citations") or []
    lines = [f"# {j.get('title')}", "",
             f"> DRAFT — NOT LEGAL ADVICE — attorney review required before publication. "
             f"Drafted {today} by the Consilium ({j.get('_model')}) from verdict card {card.get('id')} "
             f"(commission composite {review.get('composite')}, decision {review.get('decision')}).", "",
             f"*{j.get('dek')}*", "", f"**Audience:** {j.get('audience')}", "",
             "## Abstract", "", _s(j.get("abstract")), "", _s(j.get("body_markdown")), "",
             "## What to do this week", ""]
    lines += [f"- {x}" for x in (j.get("what_to_do_this_week") or [])]
    fc = j.get("forecast") or {}
    lines += ["", "## Forecast (scored)", "",
              f"{fc.get('statement')} — **p = {fc.get('probability')}** by {fc.get('by')}.", ""]
    if (j.get("hedge_note") or "").strip():
        lines += [f"_{j.get('hedge_note').strip()}_", ""]
    lines += ["## Sources", ""]
    for c in cites:
        flag = "✓" if c.get("verified") else "✗ unverified"
        lines.append(f"- {c.get('source')} — {c.get('url')} ({flag}) — \"{_s(c.get('quote'))[:160]}\"")
    if j.get("risk_flags"):
        lines += ["", "## Risk flags (for the reviewing attorney)", ""] + [f"- {x}" for x in j["risk_flags"]]
    lines += ["", f"_Novelty claim: {j.get('novelty_claim')}_", "",
              "_Commentary on public law for a professional audience; not legal advice and no "
              "attorney-client relationship._"]
    return "\n".join(lines)


def run(limit=BATCH):
    out = {"candidates": 0, "drafted": 0, "skipped": None}
    if not frontier.available(min_tokens=40000):
        out["skipped"] = "frontier unavailable"
        print("paper_drafter: " + json.dumps(out), flush=True)
        return out
    os.makedirs(PAPERS_DIR, exist_ok=True)
    for card, review, scores in _candidates(limit):
        out["candidates"] += 1
        j = draft(card, review, scores)
        if not j:
            continue
        slug = f"paper:{card.get('id')}"
        fname = f"{datetime.date.today().isoformat()}-{_slug(j.get('title'))}.md"
        path = os.path.join(PAPERS_DIR, fname)
        md = _markdown(card, review, j)
        try:
            with open(path, "w") as f:
                f.write(md)
        except Exception as e:
            print(f"paper_drafter: write failed {path}: {e}", flush=True)
        verified = sum(1 for c in (j.get("citations") or []) if c.get("verified"))
        try:
            db.insert("approvals", {
                "project": PROJECT, "slug": slug, "kind": "material",
                "title": f"Review draft paper — {_s(j.get('title'))[:120]}",
                "why": (f"Consilium verdict card passed the publication commission "
                        f"(composite {review.get('composite')}, {review.get('decision')}). "
                        f"{verified}/{len(j.get('citations') or [])} citations re-verified by URL."),
                "value": "A source-led, forecast-carrying authority piece for the Apparently Law / PMI channels.",
                "risk": "DRAFT ONLY — not legal advice; attorney review and sign-off required before any publication. "
                        + ("; ".join(j.get("risk_flags") or [])[:600]),
                "detail": json.dumps({"card_id": card.get("id"), "vertical": card.get("vertical"),
                                      "question": card.get("question"), "path": os.path.relpath(path, os.path.join(PAPERS_DIR, "..", "..", "..")),
                                      "abstract": j.get("abstract"), "forecast": j.get("forecast"),
                                      "citations": j.get("citations"), "model": j.get("_model"),
                                      "tokens": j.get("_tokens"), "draft_markdown": md[:60000]}),
                "alternatives": [
                    {"label": "Review and refine", "recommended": True,
                     "description": "Edit the draft; approve only the attorney-reviewed version for publication."},
                    {"label": "Steer only", "description": "Keep for internal steering; do not publish."},
                    {"label": "Discard", "description": "Reject the draft and re-queue the question for a deeper pass."}],
            })
        except Exception as e:
            print(f"paper_drafter: approvals insert failed for {slug}: {e}", flush=True)
        out["drafted"] += 1
        print(f"paper_drafter: drafted '{_s(j.get('title'))[:80]}' -> {fname} ({verified} verified cites)", flush=True)
    print("paper_drafter: " + json.dumps(out), flush=True)
    return out


if __name__ == "__main__":
    import single_instance
    _owned, _deadline = single_instance.guard("paper_drafter", interval_s=3600)
    if not _owned:
        print(json.dumps({"skipped": "paper_drafter already running"}))
        raise SystemExit(0)
    try:
        run(int(sys.argv[1]) if len(sys.argv) > 1 else BATCH)
    finally:
        if _deadline is not None:
            _deadline.cancel()
